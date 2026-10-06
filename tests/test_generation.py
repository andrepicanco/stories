"""Testes da geração: sanitização de HTML, contrato de saída, conserto de JSON e memória a partir do feedback."""
import json
import tempfile
import unittest
from pathlib import Path

from agent.generation import GenerationError, GenerationInput, build_task, generate, parse_output
from agent.memory import Memory
from integrations.html_sanitize import ensure_html, sanitize_html
from server import settings as cfg
from server.jobs import JobStore
from tests.test_agent import FakeLLM, FakeMessage


def reply_json(**overrides) -> str:
    data = {"mode": "draft", "title": "📝 Consulta de planos", "card_html": "<h2>Contexto</h2><p>Texto</p>",
            "impacted_resources_html": "<ul><li>repo-a</li></ul>",
            "acceptance_criteria_html": "<p><strong>CA1</strong> — algo</p>",
            "comment": "Fiz X.", "questions": [], "feedback": {"sentiment": "none", "learnings": []}}
    data.update(overrides)
    return json.dumps(data, ensure_ascii=False)


class SanitizerTests(unittest.TestCase):
    def test_removes_dangerous_content(self):
        dirty = ('<p onclick="x()">oi <script>alert(1)</script><b>forte</b></p>'
                 '<a href="javascript:alert(1)">mau</a><a href="https://ok.com/x?a=1&b=2">bom</a>'
                 '<style>p{}</style><img src=x onerror=alert(1)><iframe src=y></iframe>')
        clean = sanitize_html(dirty)
        self.assertNotIn("script", clean)
        self.assertNotIn("onclick", clean)
        self.assertNotIn("javascript", clean)
        self.assertIn("mau", clean)                      # o texto do link perigoso permanece, sem link
        self.assertNotIn("<a>", clean)
        self.assertNotIn("<img", clean)
        self.assertNotIn("iframe", clean)
        self.assertIn("<b>forte</b>", clean)
        self.assertIn('href="https://ok.com/x?a=1&amp;b=2"', clean)
        self.assertIn('rel="noopener noreferrer"', clean)

    def test_closes_unbalanced_tags_and_escapes_text(self):
        self.assertEqual(sanitize_html("<ul><li>a<li>b"), "<ul><li>a<li>b</li></li></ul>")
        self.assertEqual(sanitize_html("1 < 2 & 3"), "1 &lt; 2 &amp; 3")
        self.assertEqual(sanitize_html("<p>a</i></p>"), "<p>a</p>")
        self.assertEqual(sanitize_html(None), "")

    def test_ensure_html_wraps_plain_text(self):
        self.assertEqual(ensure_html("linha 1\nlinha 2\n\nsegundo & último"),
                         "<p>linha 1<br>linha 2</p><p>segundo &amp; último</p>")
        self.assertEqual(ensure_html("a\n\nb"), "<p>a</p><p>b</p>")
        self.assertEqual(ensure_html("<p>já é html</p>"), "<p>já é html</p>")
        self.assertEqual(ensure_html("   "), "")


class ParseTests(unittest.TestCase):
    def test_draft_with_fences_and_title_cleanup(self):
        parsed = parse_output("```json\n" + reply_json() + "\n```")
        self.assertEqual(parsed["mode"], "draft")
        self.assertEqual(parsed["title"], "Consulta de planos")
        self.assertIn("<h2>Contexto</h2>", parsed["card_html"])
        self.assertIn("repo-a", parsed["resources_html"])

    def test_text_around_json_is_tolerated(self):
        self.assertEqual(parse_output("Aqui está:\n" + reply_json() + "\nFim.")["comment"], "Fiz X.")

    def test_questions_mode_builds_comment_and_clears_texts(self):
        parsed = parse_output(reply_json(mode="questions", questions=["Q1?", "Q2?", "Q3?"], card_html="<p>x</p>"))
        self.assertEqual(parsed["questions"], ["Q1?", "Q2?"])               # no máximo 2
        self.assertIn("1. Q1?", parsed["comment"])
        self.assertEqual((parsed["card_html"], parsed["title"]), ("", ""))

    def test_invalid_outputs(self):
        for bad in ["sem json", reply_json(card_html=""), reply_json(mode="outro"), reply_json(mode="questions", questions=[])]:
            with self.assertRaises((ValueError, json.JSONDecodeError)):
                parse_output(bad)

    def test_script_in_model_html_is_removed(self):
        parsed = parse_output(reply_json(card_html="<p>ok</p><script>x</script>"))
        self.assertNotIn("script", parsed["card_html"])

    def test_learnings_are_capped_and_sentiment_normalized(self):
        parsed = parse_output(reply_json(feedback={"sentiment": "POSITIVE", "learnings": ["a", "b", "c", "d"]}))
        self.assertEqual((parsed["sentiment"], len(parsed["learnings"])), ("positive", 2))
        self.assertEqual(parse_output(reply_json(feedback={"sentiment": "???"}))["sentiment"], "none")


class TaskTests(unittest.TestCase):
    def test_first_generation_task(self):
        task = build_task(GenerationInput(card_type="Spike", epic={"id": 7, "title": "Épico X"},
                                          related=[{"id": 9, "title": "Card Y"}], brief="Investigar Z"))
        for fragment in ("Spike", "#7 — Épico X", "#9 — Card Y", "Investigar Z", "load_skill"):
            self.assertIn(fragment, task)
        self.assertNotIn("RESPOSTA DO USUÁRIO", task)

    def test_reply_task_resends_current_texts_and_history(self):
        task = build_task(GenerationInput(
            brief="b", title="T", card_html="<p>texto atual</p>", resources_html="<p>r</p>", criteria_html="<p>c</p>",
            chat=[{"role": "assistant", "content": "comentário anterior"}], reply="Deixe mais curto"))
        for fragment in ("texto atual", "comentário anterior", "RESPOSTA DO USUÁRIO", "Deixe mais curto", "feedback"):
            self.assertIn(fragment, task)


class GenerateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.memory_path = Path(self.tmp.name) / "memory.json"
        self.settings = cfg.load_settings()

    def tearDown(self):
        self.tmp.cleanup()

    def run_generate(self, replies, **inp):
        llm = FakeLLM([FakeMessage(r) for r in replies])
        result = generate(llm, self.settings, GenerationInput(brief="b", **inp), memory_path=self.memory_path, wait_for_mcp=False)
        return result, llm

    def test_draft(self):
        result, llm = self.run_generate([reply_json()])
        self.assertEqual((result.mode, result.title), ("draft", "Consulta de planos"))
        system = llm.calls[0][0][0]["content"]
        self.assertIn("Formato da resposta", system)
        self.assertIn("Skills disponíveis", system)
        self.assertEqual(Memory(self.memory_path).facts(), [])      # sem resposta do usuário, nada vai para a memória

    def test_invalid_json_is_repaired_once(self):
        result, llm = self.run_generate(["isso não é json", reply_json()])
        self.assertEqual(result.mode, "draft")
        self.assertEqual(len(llm.calls), 2)
        self.assertEqual(llm.calls[1][1], [])                       # o conserto é sem tools
        self.assertIn("SOMENTE o objeto JSON", llm.calls[1][0][-1]["content"])

    def test_invalid_twice_raises(self):
        with self.assertRaises(GenerationError):
            self.run_generate(["lixo", "mais lixo"])

    def test_reply_saves_learnings_to_memory_without_duplicates(self):
        feedback = {"sentiment": "negative", "learnings": ["Prefere critérios curtos", "prefere critérios curtos"]}
        result, _ = self.run_generate([reply_json(feedback=feedback)], reply="Está longo demais", card_html="<p>x</p>")
        self.assertEqual(result.learnings_saved, ["Prefere critérios curtos"])
        self.assertEqual(Memory(self.memory_path).facts(), ["Prefere critérios curtos"])
        self.assertEqual(result.sentiment, "negative")

    def test_memory_is_injected_into_next_run(self):
        Memory(self.memory_path).add("Escreve para devs experientes")
        _, llm = self.run_generate([reply_json()])
        self.assertIn("Escreve para devs experientes", llm.calls[0][0][0]["content"])

    def test_questions_mode(self):
        result, _ = self.run_generate([reply_json(mode="questions", questions=["Qual o escopo?"])])
        self.assertEqual((result.mode, result.questions, result.card_html), ("questions", ["Qual o escopo?"], ""))


class JobTests(unittest.TestCase):
    def wait(self, job):
        import time
        for _ in range(100):
            if job.status != "running":
                return
            time.sleep(0.02)

    def test_success_steps_and_error(self):
        store = JobStore()
        ok = store.start(lambda on_step: (on_step({"tool": "x"}), {"v": 1})[1])
        self.wait(ok)
        self.assertEqual((ok.status, ok.result, ok.steps), ("done", {"v": 1}, [{"tool": "x"}]))

        def boom(on_step):
            raise RuntimeError("falhou")
        bad = store.start(boom)
        self.wait(bad)
        self.assertEqual((bad.status, bad.error), ("error", "falhou"))
        self.assertIs(store.get(ok.id), ok)
        self.assertIsNone(store.get("nao-existe"))


if __name__ == "__main__":
    unittest.main()
