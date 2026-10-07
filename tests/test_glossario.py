"""Testes do glossário de Cobrança: conversão da planilha, índice de aliases, tool e prompt (sem rede).
Os dados são sintéticos: nada do glossário real entra no repositório."""
import copy
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from openpyxl import Workbook

from agent import tools as tools_pkg
from agent.base import CORE, ToolContext
from agent.generation import GenerationInput, generate
from agent.glossary import Glossary, aliases, load_entries
from agent.prompts import build_system_prompt
from agent.registry import discover_tools, filter_tools
from agent.tools import glossario
from scripts import glossario_build as build
from server import settings as cfg
from tests.test_agent import FakeLLM, FakeMessage, tool_call
from tests.test_generation import reply_json

HEADER = ["tipo", "nome_canonico", "sinonimos", "nota", "status"]


def make_xlsx(path: Path, rows, header=HEADER, sheet="Entidades") -> Path:
    wb = Workbook()
    wb.active.title = "Leia-me"
    ws = wb.create_sheet(sheet)
    ws.append(header)
    for row in rows:
        ws.append(row)
    wb.save(path)
    return path


ROWS = [
    ["Processo", "Repactuação", "reneg; repac; Reparcelamento", "Termo mais usado na loja", "ativo"],
    ["Sistema", "Sistema Beta", None, None, "ativo"],
    [None, None, None, None, None],                                        # linha em branco
    ["Processo", "Positivação", "positivação (o oposto); restrição", "", "ativo"],
    ["Projeto", "Rascunho Gama", "gama", "ainda sem validação", "revisar"],   # não entra
    ["Projeto", "Migração Alfa/Beta", "Alfa/Beta; alfa/beta; s/ juros; ; Migração Alfa/Beta", "", " Ativo "],
]


class BuildTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def read(self, rows=ROWS, **kw):
        return build.read_entities(make_xlsx(self.dir / "g.xlsx", rows, **kw))

    def test_only_active_rows_in_sheet_order_and_skipped_are_counted(self):
        entries, skipped = self.read()
        self.assertEqual([e["nome_canonico"] for e in entries],
                         ["Repactuação", "Sistema Beta", "Positivação", "Migração Alfa/Beta"])
        self.assertEqual(dict(skipped), {"revisar": 1})
        self.assertTrue(all(e["status"] == "ativo" for e in entries))

    def test_synonyms_split_on_semicolon_only_deduped_and_without_the_canonical_name(self):
        entries, _ = self.read()
        by_name = {e["nome_canonico"]: e for e in entries}
        self.assertEqual(by_name["Repactuação"]["sinonimos"], ["reneg", "repac", "Reparcelamento"])
        self.assertEqual(by_name["Sistema Beta"]["sinonimos"], [])
        self.assertEqual(by_name["Migração Alfa/Beta"]["sinonimos"], ["Alfa/Beta", "s/ juros"])   # '/' fica no nome
        self.assertEqual(by_name["Repactuação"]["nota"], "Termo mais usado na loja")
        self.assertEqual(by_name["Sistema Beta"]["nota"], "")

    def test_output_is_idempotent_and_has_no_timestamps(self):
        entries, _ = self.read()
        out = self.dir / "g.json"
        self.assertTrue(build.write_glossary(entries, out))
        first = out.read_bytes()
        self.assertFalse(build.write_glossary(entries, out))               # nada mudou: não regrava
        entries_again, _ = self.read()
        build.write_glossary(entries_again, out)
        self.assertEqual(out.read_bytes(), first)
        self.assertEqual(json.loads(first.decode("utf-8"))[0]["nome_canonico"], "Repactuação")
        self.assertIn("Repactuação", first.decode("utf-8"))                  # UTF-8 legível, sem ç

    def test_errors_are_clear(self):
        with self.assertRaisesRegex(build.BuildError, "sem a\\(s\\) coluna\\(s\\): nota"):
            self.read(header=["tipo", "nome_canonico", "sinonimos", "status"], rows=[["P", "X", "", "ativo"]])
        with self.assertRaisesRegex(build.BuildError, "aba 'Entidades' não encontrada"):
            self.read(sheet="Outra")
        with self.assertRaisesRegex(build.BuildError, "linha 3: 'tipo' e 'nome_canonico'"):
            self.read(rows=[["P", "X", "", "", "ativo"], ["P", "", "sin", "", "ativo"]])
        with self.assertRaisesRegex(build.BuildError, "duplicado 'Repactuacao' \\(já aparece na linha 2\\)"):
            self.read(rows=[["P", "Repactuação", "", "", "ativo"], ["P", "Repactuacao", "", "", "ativo"]])
        with self.assertRaisesRegex(build.BuildError, "não encontrada"):
            build.read_entities(self.dir / "nao-existe.xlsx")

    def test_incomplete_rows_that_are_not_active_do_not_break_the_build(self):
        entries, skipped = self.read(rows=[["P", "X", "", "", "ativo"], ["", "", "so uma nota", "", "revisar"]])
        self.assertEqual(len(entries), 1)
        self.assertEqual(dict(skipped), {"revisar": 1})

    def test_main_writes_next_to_the_spreadsheet_and_reports(self):
        xlsx = make_xlsx(self.dir / "g.xlsx", ROWS + [["Projeto", "Outra Coisa", "reneg", "", "ativo"]])
        import contextlib
        import io
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.assertEqual(build.main([str(xlsx)]), 0)
        self.assertTrue((self.dir / build.DEFAULT_NAME).is_file())
        report = buf.getvalue()
        self.assertIn("5 entradas ativas", report)
        self.assertIn("1x 'revisar'", report)
        self.assertIn("'reneg' -> Repactuação, Outra Coisa", report)       # alias ambíguo listado
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(build.main([str(self.dir / "faltando.xlsx")]), 1)


def entry(nome, sinonimos=(), tipo="Processo", nota=""):
    return {"tipo": tipo, "nome_canonico": nome, "sinonimos": list(sinonimos), "nota": nota, "status": "ativo"}


class GlossaryIndexTests(unittest.TestCase):
    def setUp(self):
        self.g = Glossary([
            entry("Repactuação", ["reneg", "Reparcelamento"], nota="Termo mais usado na loja"),
            entry("Positivação", ["positivação (o oposto)", "restrição"]),
            entry("Serasa", ["birô"], tipo="Sistema"),
            entry("SPC", ["birô"], tipo="Sistema"),
        ])

    def names(self, term):
        return [e["nome_canonico"] for e in self.g.lookup(term)]

    def test_exact_match_ignores_case_accents_and_extra_spaces(self):
        for term in ("reneg", "RENEG", "  Reneg  ", "REPACTUAÇÃO", "repactuacao", "reparcelamento"):
            self.assertEqual(self.names(term), ["Repactuação"], term)

    def test_no_partial_or_fuzzy_match(self):
        for term in ("reneg algo", "reparc", "repactuacoes", ""):
            self.assertEqual(self.names(term), [], term)

    def test_annotated_synonym_also_matches_without_the_parenthetical(self):
        self.assertEqual(self.names("positivacao"), ["Positivação"])
        self.assertEqual(self.names("Positivação (o oposto)"), ["Positivação"])
        self.assertEqual(aliases(entry("X", ["a (v0)"])), ["X", "a (v0)", "a"])

    def test_shared_alias_returns_every_candidate_and_is_reported_as_ambiguous(self):
        self.assertEqual(self.names("BIRÔ"), ["Serasa", "SPC"])
        self.assertEqual(self.g.ambiguous(), {"biro": ["Serasa", "SPC"]})

    def test_load_entries_validates_the_shape(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "g.json"
            for bad in ('{"a": 1}', '[{"nome_canonico": ""}]', '[{"nome_canonico": "X", "sinonimos": "a"}]', "não é json"):
                path.write_text(bad, encoding="utf-8")
                with self.assertRaises(ValueError):          # JSONDecodeError também é ValueError
                    load_entries(path)
            path.write_text(json.dumps([entry("X")]), encoding="utf-8")
            self.assertEqual(load_entries(path)[0]["nome_canonico"], "X")


class ToolTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.path = self.dir / "glossario.json"
        self.path.write_text(json.dumps([
            entry("Repactuação", ["reneg"], nota="Termo mais usado na loja"),
            entry("Serasa", ["birô"], tipo="Sistema"),
            entry("SPC", ["birô"], tipo="Sistema"),
        ], ensure_ascii=False), encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def ctx(self, path):
        return ToolContext(settings={"glossary": {"path": str(path)}}, root=self.dir)

    def call(self, tool, term):
        return tool.fn(**tool.check_args({"term": term}))

    def test_no_tool_without_a_configured_existing_file(self):
        self.assertEqual(glossario.get_tools(ToolContext(settings={}, root=self.dir)), [])
        self.assertEqual(glossario.get_tools(self.ctx("")), [])
        self.assertEqual(glossario.get_tools(self.ctx(self.dir / "nao-existe.json")), [])
        empty = self.dir / "vazio.json"
        empty.write_text("[]", encoding="utf-8")
        self.assertEqual(glossario.get_tools(self.ctx(empty)), [])

    def test_relative_path_is_resolved_from_the_project_root(self):
        tools = glossario.get_tools(ToolContext(settings={"glossary": {"path": "glossario.json"}}, root=self.dir))
        self.assertEqual([t.name for t in tools], ["glossario_buscar"])

    def test_tool_is_read_only_and_survives_the_group_filter(self):
        (tool,) = glossario.get_tools(self.ctx(self.path))
        self.assertEqual((tool.name, tool.group, tool.effect.value), ("glossario_buscar", CORE, "READ"))
        self.assertFalse(tool.needs_approval)
        # regressão: um grupo fora dos checkboxes da tela seria descartado por filter_tools
        self.assertEqual([t.name for t in filter_tools([tool], [])], ["glossario_buscar"])

    def test_hit_returns_canonical_name_type_synonyms_and_note(self):
        (tool,) = glossario.get_tools(self.ctx(self.path))
        out = self.call(tool, "RENEG")
        for fragment in ("Repactuação (Processo)", "Sinônimos: reneg", "Nota: Termo mais usado na loja", "buscas separadas"):
            self.assertIn(fragment, out)

    def test_ambiguous_term_lists_all_candidates(self):
        (tool,) = glossario.get_tools(self.ctx(self.path))
        out = self.call(tool, "birô")
        self.assertIn("casa com 2 entradas", out)
        self.assertIn("Serasa (Sistema)", out)
        self.assertIn("SPC (Sistema)", out)

    def test_miss_says_so_without_guessing(self):
        (tool,) = glossario.get_tools(self.ctx(self.path))
        out = self.call(tool, "xyz")
        self.assertIn("não consta no glossário", out)
        self.assertNotIn("Repactuação", out)

    def test_corrupt_json_becomes_a_warning_and_other_tools_survive(self):
        tools_dir = self.dir / "tools"
        tools_dir.mkdir()
        shutil.copy(Path(tools_pkg.__file__).parent / "glossario.py", tools_dir / "glossario.py")
        (tools_dir / "ok.py").write_text(
            "from agent.base import Tool\ndef get_tools(ctx):\n    return [Tool('ok_tool', 'd', lambda: 'x', inputs={})]\n",
            encoding="utf-8")
        bad = self.dir / "quebrado.json"
        bad.write_text("{ isso não é json", encoding="utf-8")
        tools, errors = discover_tools(tools_dir, self.ctx(bad))
        self.assertEqual([t.name for t in tools], ["ok_tool"])
        self.assertEqual(len(errors), 1)
        self.assertIn("glossario.py", errors[0])
        tools, errors = discover_tools(tools_dir, self.ctx(self.path))
        self.assertEqual(sorted(t.name for t in tools), ["glossario_buscar", "ok_tool"])
        self.assertEqual(errors, [])


class PromptAndAgentTests(unittest.TestCase):
    def test_prompt_mentions_the_glossary_only_when_the_tool_exists(self):
        with_g = build_system_prompt("", "", "", [], {}, has_glossary=True)
        without = build_system_prompt("", "", "", [], {})
        self.assertIn("glossario_buscar", with_g)
        self.assertIn("termo desconhecido", with_g)
        self.assertNotIn("glossario_buscar", without)
        self.assertIn("Nenhuma fonte externa habilitada", with_g)       # o glossário não é fonte externa

    def test_generation_exposes_the_tool_and_the_model_can_use_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "g.json"
            path.write_text(json.dumps([entry("Repactuação", ["reneg"])], ensure_ascii=False), encoding="utf-8")
            settings = copy.deepcopy(cfg.load_settings())
            settings["glossary"] = {"path": str(path)}
            llm = FakeLLM([FakeMessage(tool_calls=[tool_call("glossario_buscar", {"term": "reneg"})]),
                           FakeMessage(reply_json())])
            result = generate(llm, settings, GenerationInput(brief="faça a reneg"), wait_for_mcp=False,
                              memory_path=Path(tmp) / "memory.json")
        self.assertEqual([s["tool"] for s in result.steps], ["glossario_buscar"])
        self.assertFalse(result.steps[0]["error"])
        system = llm.calls[0][0][0]["content"]
        self.assertIn("Glossário de Cobrança", system)
        self.assertNotIn("Repactuação", system)                         # o conteúdo do glossário nunca vai ao prompt
        tool_names = [t["function"]["name"] for t in llm.calls[0][1]]
        self.assertIn("glossario_buscar", tool_names)
        observed = [m for m in llm.calls[1][0] if m.get("role") == "tool"]
        self.assertIn("Repactuação (Processo)", observed[0]["content"])

    def test_generation_without_a_configured_file_has_no_glossary(self):
        settings = copy.deepcopy(cfg.load_settings())
        settings["glossary"] = {"path": ""}
        with tempfile.TemporaryDirectory() as tmp:
            llm = FakeLLM([FakeMessage(reply_json())])
            generate(llm, settings, GenerationInput(brief="b"), wait_for_mcp=False, memory_path=Path(tmp) / "m.json")
        self.assertNotIn("glossario_buscar", llm.calls[0][0][0]["content"])
        self.assertNotIn("glossario_buscar", [t["function"]["name"] for t in llm.calls[0][1]])


if __name__ == "__main__":
    unittest.main()
