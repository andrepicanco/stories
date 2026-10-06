"""Testes do núcleo do agente (sem rede). Rodar na raiz: python -m unittest discover -s tests -t ."""
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from agent.base import CORE, Param, Tool, ToolContext
from agent.harness import run_turn
from agent.memory import Memory
from agent.ontology import Effect, OntologyError
from agent.prompts import build_system_prompt
from agent.registry import discover_tools, filter_tools
from agent.skills import SkillRegistry, parse_frontmatter
from agent.tools import obsidian
from integrations.board_url import InvalidBoardUrl, parse_board_url
from integrations.html_text import html_to_text


# ---------- LLM falso ----------
def tool_call(name, args, call_id="c1"):
    return SimpleNamespace(id=call_id, function=SimpleNamespace(name=name, arguments=json.dumps(args)))


class FakeMessage:
    def __init__(self, content=None, tool_calls=None):
        self.content, self.tool_calls = content, tool_calls

    def model_dump(self, exclude_none=True):
        data = {"role": "assistant", "content": self.content}
        if self.tool_calls:
            data["tool_calls"] = [{"id": c.id, "type": "function",
                                   "function": {"name": c.function.name, "arguments": c.function.arguments}}
                                  for c in self.tool_calls]
        return {k: v for k, v in data.items() if v is not None}


class FakeLLM:
    def __init__(self, replies):
        self.replies, self.calls = list(replies), []

    def chat(self, messages, tools):
        self.calls.append((list(messages), tools))
        return self.replies.pop(0)


def echo_tool(**kw):
    return Tool("echo", "ecoa", lambda text: f"eco:{text}", inputs={"text": Param("Text", "texto")})


class HarnessTests(unittest.TestCase):
    def test_tool_then_final_answer(self):
        llm = FakeLLM([FakeMessage(tool_calls=[tool_call("echo", {"text": "oi"})]), FakeMessage("pronto")])
        result = run_turn(llm, "sys", [{"role": "user", "content": "x"}], [echo_tool()])
        self.assertEqual(result.text, "pronto")
        self.assertEqual([s.output for s in result.steps], ["eco:oi"])
        self.assertFalse(result.hit_step_limit)
        self.assertEqual(llm.calls[0][0][0], {"role": "system", "content": "sys"})

    def test_unknown_tool_and_bad_args_become_observations(self):
        llm = FakeLLM([FakeMessage(tool_calls=[tool_call("nada", {}, "a"), tool_call("echo", {"x": 1}, "b")]),
                       FakeMessage("ok")])
        result = run_turn(llm, "s", [], [echo_tool()])
        self.assertTrue(all(s.error for s in result.steps))
        self.assertIn("não existe", result.steps[0].output)
        self.assertIn("desconhecido", result.steps[1].output)

    def test_step_limit_forces_final_answer_without_tools(self):
        looping = [FakeMessage(tool_calls=[tool_call("echo", {"text": "a"}, f"c{i}")]) for i in range(3)]
        llm = FakeLLM(looping + [FakeMessage("resposta parcial")])
        result = run_turn(llm, "s", [], [echo_tool()], max_steps=3)
        self.assertTrue(result.hit_step_limit)
        self.assertEqual(result.text, "resposta parcial")
        self.assertEqual(llm.calls[-1][1], [])          # última chamada sem tools

    def test_output_truncation(self):
        big = Tool("big", "grande", lambda: "x" * 500, inputs={})
        llm = FakeLLM([FakeMessage(tool_calls=[tool_call("big", {})]), FakeMessage("ok")])
        result = run_turn(llm, "s", [], [big], max_tool_output=100)
        self.assertIn("truncado", result.steps[0].output)
        self.assertLess(len(result.steps[0].output), 200)

    def test_write_world_requires_approval(self):
        danger = Tool("danger", "perigosa", lambda: "feito", inputs={}, effect=Effect.WRITE_WORLD)
        for approve, expected in [(None, "negado"), (lambda n, a: False, "negado"), (lambda n, a: True, "feito")]:
            llm = FakeLLM([FakeMessage(tool_calls=[tool_call("danger", {})]), FakeMessage("ok")])
            result = run_turn(llm, "s", [], [danger], approve=approve)
            self.assertIn(expected, result.steps[0].output)

    def test_raw_schema_tool(self):
        schema = {"type": "object", "properties": {"q": {"type": "string"}}, "required": ["q"]}
        mcp = Tool("srv__search", "mcp", lambda **kw: f"achou {kw['q']}", schema=schema)
        self.assertEqual(mcp.spec()["function"]["parameters"], schema)
        llm = FakeLLM([FakeMessage(tool_calls=[tool_call("srv__search", {})]),
                       FakeMessage(tool_calls=[tool_call("srv__search", {"q": "abc"}, "c2")]), FakeMessage("ok")])
        result = run_turn(llm, "s", [], [mcp])
        self.assertIn("falta", result.steps[0].output)
        self.assertEqual(result.steps[1].output, "achou abc")

    def test_tool_needs_exactly_one_of_inputs_or_schema(self):
        with self.assertRaises(ValueError):
            Tool("t", "d", lambda: "")
        with self.assertRaises(ValueError):
            Tool("t", "d", lambda: "", inputs={}, schema={})


class OntologyTests(unittest.TestCase):
    def test_types(self):
        tool = Tool("t", "d", lambda **k: "", inputs={
            "id": Param("WorkItemId", "id"), "p": Param("Path", "p", optional=True)})
        self.assertEqual(tool.check_args({"id": "42"}), {"id": 42})
        for bad in ({"id": 0}, {"id": "abc"}, {"id": 1.5}, {"id": 3, "p": "../x"}, {"id": 3, "p": "/etc"}, {"id": 3, "p": "C:/x"}):
            with self.assertRaises(OntologyError, msg=str(bad)):
                tool.check_args(bad)
        self.assertEqual(tool.spec()["function"]["parameters"]["properties"]["id"]["type"], "integer")


class FilterTests(unittest.TestCase):
    def test_allowlist_by_group(self):
        tools = [Tool(n, "d", lambda: "", inputs={}, group=g)
                 for n, g in [("a", "notion"), ("b", "azure"), ("c", "obsidian"), ("d", CORE)]]
        self.assertEqual({t.name for t in filter_tools(tools, [])}, {"d"})
        self.assertEqual({t.name for t in filter_tools(tools, ["azure", "obsidian"])}, {"b", "c", "d"})


class SkillTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        (base / "alpha").mkdir()
        (base / "alpha" / "SKILL.md").write_text('---\nname: alpha\ndescription: "Faz A: com dois pontos"\n---\n# Corpo A\n', encoding="utf-8")
        (base / "alpha" / "ref.md").write_text("referencia", encoding="utf-8")
        (base / "sem-desc").mkdir()
        (base / "sem-desc" / "SKILL.md").write_text("---\nname: x\n---\ncorpo", encoding="utf-8")
        (base / "outra").mkdir()
        (base / "outra" / "SKILL.md").write_text("---\ndescription: usa nome da pasta\n---\nB", encoding="utf-8")
        self.reg = SkillRegistry(base)

    def tearDown(self):
        self.tmp.cleanup()

    def test_index_and_load(self):
        self.assertEqual(set(self.reg.skills), {"alpha", "outra"})
        self.assertEqual(self.reg.skills["alpha"].description, "Faz A: com dois pontos")
        self.assertIn("sem 'description'", self.reg.errors[0])
        self.assertIn("**alpha**", self.reg.index_block())
        self.assertEqual(self.reg.load("alpha").strip(), "# Corpo A")
        self.assertEqual(self.reg.load("alpha", "ref.md"), "referencia")

    def test_load_skill_blocks_escape_and_unknown(self):
        with self.assertRaises(ValueError):
            self.reg.load("alpha", "../outra/SKILL.md")
        with self.assertRaises(ValueError):
            self.reg.load("nao-existe")
        tool = self.reg.tool()
        self.assertEqual(tool.check_args({"name": "alpha"}), {"name": "alpha"})
        with self.assertRaises(OntologyError):
            tool.check_args({"name": "nao-existe"})

    def test_project_skills_are_valid(self):
        real = SkillRegistry(Path(__file__).resolve().parent.parent / "agent" / "skills")
        self.assertEqual(real.errors, [])
        self.assertIn("user-story-writer-cobranca", real.skills)
        self.assertIn("notion-navigator-cobranca", real.skills)

    def test_frontmatter_without_header(self):
        self.assertEqual(parse_frontmatter("só texto"), ({}, "só texto"))


class ObsidianTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name) / "vault"
        (root / "Projetos").mkdir(parents=True)
        (root / ".obsidian").mkdir()
        (root / ".obsidian" / "config.md").write_text("segredo oculto", encoding="utf-8")
        (root / "Projetos" / "Renegociação.md").write_text("# Reneg\nTaxa de juros reduzida\nOutra linha", encoding="utf-8")
        (root / "Projetos" / "Outro.md").write_text("nada relevante", encoding="utf-8")
        (root / "grande.md").write_text("a" * 1000, encoding="utf-8")
        (Path(self.tmp.name) / "fora.md").write_text("fora do vault", encoding="utf-8")
        self.root = root
        ctx = ToolContext(settings={"obsidian": {"root_dir": str(root)}}, root=root, max_tool_output=800)
        self.tools = {t.name: t for t in obsidian.get_tools(ctx)}

    def tearDown(self):
        self.tmp.cleanup()

    def call(self, name, **args):
        tool = self.tools[name]
        return tool.fn(**tool.check_args(args))

    def test_without_root_no_tools(self):
        ctx = ToolContext(settings={"obsidian": {"root_dir": ""}}, root=self.root)
        self.assertEqual(obsidian.get_tools(ctx), [])

    def test_list_hides_dotfolders(self):
        out = self.call("obsidian_list")
        self.assertIn("[pasta] Projetos/", out)
        self.assertNotIn(".obsidian", out)

    def test_search_is_accent_and_case_insensitive(self):
        out = self.call("obsidian_search", query="RENEGOCIACAO juros")
        self.assertIn("Projetos/Renegociação.md", out)
        self.assertNotIn("Outro.md", out)
        self.assertIn("nenhuma nota", self.call("obsidian_search", query="inexistente zzz"))

    def test_search_skips_hidden(self):
        self.assertIn("nenhuma nota", self.call("obsidian_search", query="segredo"))

    def test_read_and_paging(self):
        self.assertIn("Taxa de juros", self.call("obsidian_read", path="Projetos/Renegociação.md"))
        first = self.call("obsidian_read", path="grande.md")
        self.assertIn("start=", first)
        self.assertEqual(self.call("obsidian_read", path="grande.md", start=900), "a" * 100)

    def test_path_escape_blocked(self):
        with self.assertRaises(OntologyError):
            self.call("obsidian_read", path="../fora.md")
        with self.assertRaises(ValueError):
            self.call("obsidian_read", path=".obsidian/config.md")
        with self.assertRaises(ValueError):
            self.call("obsidian_read", path="Projetos")          # pasta, não nota


class PromptAndRegistryTests(unittest.TestCase):
    def test_prompt_marks_unavailable_sources(self):
        prompt = build_system_prompt("", "", "", ["obsidian", "notion"], {"obsidian": 3})
        self.assertIn("Obsidian (anotações locais): disponível", prompt)
        self.assertIn("Notion: indisponível", prompt)
        self.assertIn("redator técnico", prompt)                 # persona padrão

    def test_prompt_uses_custom_persona_and_keeps_rules(self):
        prompt = build_system_prompt("Sou o copiloto X.", "", "", [], {})
        self.assertTrue(prompt.startswith("Sou o copiloto X."))
        self.assertIn("Nunca invente", prompt)
        self.assertIn("Nenhuma fonte externa", prompt)

    def test_discover_tools_isolates_broken_modules(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "ok.py").write_text(
                "from agent.base import Tool\n"
                "def get_tools(ctx):\n    return [Tool('ok_tool', 'd', lambda: 'x', inputs={})]\n", encoding="utf-8")
            (Path(tmp) / "quebrado.py").write_text("raise RuntimeError('boom')", encoding="utf-8")
            (Path(tmp) / "sem_funcao.py").write_text("X = 1", encoding="utf-8")
            (Path(tmp) / "_privado.py").write_text("raise SystemExit", encoding="utf-8")
            tools, errors = discover_tools(Path(tmp), ToolContext(settings={}, root=Path(tmp)))
        self.assertEqual([t.name for t in tools], ["ok_tool"])
        self.assertEqual(len(errors), 2)


class MemoryTests(unittest.TestCase):
    def test_dedup_and_block(self):
        with tempfile.TemporaryDirectory() as tmp:
            memory = Memory(Path(tmp) / "m" / "memory.json")
            self.assertEqual(memory.prompt_block(), "")
            self.assertTrue(memory.add("Prefere  critérios curtos"))
            self.assertFalse(memory.add("prefere critérios curtos"))
            self.assertFalse(memory.add("   "))
            self.assertIn("- Prefere critérios curtos", memory.prompt_block())
            memory.remove(0)
            self.assertEqual(memory.facts(), [])


class IntegrationHelperTests(unittest.TestCase):
    def test_html_to_text(self):
        html = "<div>Linha<br>dois</div><ul><li>a</li><li>b&nbsp;c</li></ul>"
        self.assertEqual(html_to_text(html), "Linha\ndois\n\n- a\n- b c")
        self.assertEqual(html_to_text(None), "")
        self.assertEqual(html_to_text('<p>veja <a href="https://x.com/a">o doc</a> e <a href="https://y.com">https://y.com</a></p>'),
                         "veja o doc (https://x.com/a) e https://y.com")

    def test_board_url(self):
        url = "https://dev.azure.com/Org/Meu%20Projeto/_boards/board/t/Meu%20Time/Stories"
        ctx = parse_board_url(url)
        self.assertEqual((ctx.organization, ctx.project, ctx.team, ctx.backlog_level),
                         ("Org", "Meu Projeto", "Meu Time", "Stories"))
        with self.assertRaises(InvalidBoardUrl):
            parse_board_url("Renegociacao e Cobranca")


if __name__ == "__main__":
    unittest.main()
