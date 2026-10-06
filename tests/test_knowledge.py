import tempfile
import unittest
from pathlib import Path

from agent.base import ToolContext
from agent.knowledge import style
from agent.knowledge.store import OntologyStore, link_target, parse_frontmatter
from agent.prompts import build_system_prompt
from agent.service import build_agent
from agent.tools import ontology as tool_module

RENEG = """---
tipo: conceito
sinonimos: [reneg, renegociar dívida]
relacoes:
  - {rel: executada_por, alvo: "[[CRM]]"}
  - {rel: gera, alvo: "[[Acordo]]"}
fontes: ["wiki:/Governança Ágil", "card:288965"]
status: validado
atualizado: 2026-10-06
---
A renegociação troca as condições de uma dívida em atraso. O cliente aceita uma proposta. O sistema cria o acordo.
"""
CRM = """---
tipo: sistema
sinonimos: [CRM Salesforce]
relacoes:
  - {rel: chama, alvo: "[[CobranSaaS]]"}
---
O CRM executa a renegociação.
"""
COBRANSAAS = """---
tipo: sistema
sinonimos: [Cobransaas]
relacoes: []
---
O CobranSaaS expõe a API de planos.
"""
RASCUNHO = """---
tipo: conceito
fontes: ["wiki:/QA"]
---
A parcela é uma fração do acordo.
"""
EVENTOS = """# Eventos 2026-10
- 2026-10-02 | card:288965 | Waiting Deploy → Done | [[Renegociação]]
- 2026-10-05 | card:300000 | To Do → In Progress | [[CobranSaaS]]
- 2026-09-20 | card:111111 | Refining → To Do | [[Negativação]]
"""


def make_ontology(root: Path) -> Path:
    (root / "Conceitos").mkdir(parents=True)
    (root / "Sistemas").mkdir()
    (root / "_rascunhos" / "conceito").mkdir(parents=True)
    (root / "Eventos").mkdir()
    (root / "Conceitos" / "Renegociação.md").write_text(RENEG, encoding="utf-8")
    (root / "Sistemas" / "CRM.md").write_text(CRM, encoding="utf-8")
    (root / "Sistemas" / "CobranSaaS.md").write_text(COBRANSAAS, encoding="utf-8")
    (root / "_rascunhos" / "conceito" / "Parcela.md").write_text(RASCUNHO, encoding="utf-8")
    (root / "Eventos" / "2026-10.md").write_text(EVENTOS, encoding="utf-8")
    (root / ".obsidian").mkdir()
    (root / ".obsidian" / "config.md").write_text("segredo", encoding="utf-8")
    return root


class FrontmatterTests(unittest.TestCase):
    def test_parse_listas_dicts_e_escalares(self):
        meta, body = parse_frontmatter(RENEG)
        self.assertEqual(meta["tipo"], "conceito")
        self.assertEqual(meta["sinonimos"], ["reneg", "renegociar dívida"])
        self.assertEqual(meta["relacoes"][0], {"rel": "executada_por", "alvo": "[[CRM]]"})
        self.assertEqual(meta["fontes"], ["wiki:/Governança Ágil", "card:288965"])
        self.assertTrue(body.startswith("A renegociação"))

    def test_sem_frontmatter(self):
        self.assertEqual(parse_frontmatter("só texto"), ({}, "só texto"))

    def test_link_target(self):
        self.assertEqual(link_target("[[Sistemas/CRM|o CRM]]"), "CRM")
        self.assertEqual(link_target("[[Acordo#Parcelas]]"), "Acordo")
        self.assertEqual(link_target("Acordo"), "Acordo")


class StoreTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.store = OntologyStore(make_ontology(Path(self._tmp.name)))

    def test_notas_validadas_e_rascunhos(self):
        by_name = {n.name: n for n in self.store.notes()}
        self.assertEqual(set(by_name), {"Renegociação", "CRM", "CobranSaaS", "Parcela"})
        self.assertFalse(by_name["Renegociação"].is_draft)
        self.assertTrue(by_name["Parcela"].is_draft)        # em _rascunhos
        self.assertNotIn("config", by_name)                 # pastas ocultas ignoradas

    def test_busca_por_sinonimo_sem_acento(self):
        self.assertEqual(self.store.search("RENEG")[0].name, "Renegociação")
        self.assertEqual(self.store.search("renegociacao")[0].name, "Renegociação")
        self.assertEqual(self.store.resolve("renegociar divida").name, "Renegociação")

    def test_rascunho_so_aparece_se_pedido(self):
        self.assertEqual(self.store.search("parcela"), [])
        self.assertEqual([n.name for n in self.store.search("parcela", include_drafts=True)], ["Parcela"])

    def test_vizinhos_nos_dois_sentidos(self):
        rows = self.store.neighbors("Renegociação", depth=1)
        self.assertIn((1, "→", "executada_por", "CRM"), rows)
        self.assertIn((1, "→", "gera", "Acordo (sem nota)"), rows)
        crm = self.store.neighbors("CRM", depth=1)
        self.assertIn((1, "←", "executada_por", "Renegociação"), crm)
        depth2 = self.store.neighbors("Renegociação", depth=2)
        self.assertIn((2, "→", "chama", "CobranSaaS"), depth2)

    def test_linha_do_tempo_por_conceito_sinonimo_e_card(self):
        self.assertEqual(len(self.store.timeline("Renegociação")), 1)
        self.assertEqual(len(self.store.timeline("reneg")), 1)
        self.assertEqual(len(self.store.timeline("card:300000")), 1)
        self.assertEqual(len(self.store.timeline("CobranSaaS", since="2026-10-06")), 0)
        self.assertTrue(self.store.event_lines_since()[0].startswith("- 2026-10-05"))   # mais novo primeiro

    def test_recarrega_quando_a_nota_muda(self):
        path = Path(self._tmp.name) / "Conceitos" / "Acordo.md"
        self.assertIsNone(self.store.resolve("Acordo"))
        path.write_text("---\ntipo: conceito\n---\nO acordo registra o que o cliente aceitou.", encoding="utf-8")
        self.assertEqual(self.store.resolve("Acordo").name, "Acordo")


class StyleTests(unittest.TestCase):
    def test_texto_curto_e_ativo_sem_avisos(self):
        self.assertEqual(style.check("O CRM executa a renegociação. O cliente aceita a proposta."), ["sigla sem definição: CRM"])
        self.assertEqual(style.check("O Customer Relationship Management (CRM) executa a renegociação."), [])

    def test_frase_longa(self):
        text = " ".join(["palavra"] * 30) + "."
        self.assertTrue(any(w.startswith("frase longa (30") for w in style.check(text)))

    def test_paragrafo_longo(self):
        text = " ".join(f"Frase {i}." for i in range(8))
        self.assertTrue(any(w.startswith("parágrafo longo (8") for w in style.check(text)))

    def test_voz_passiva_etc_e_parenteses(self):
        warnings = style.check("A renegociação é feita pelo sistema, boletos, acordos etc. (veja também a página longa de regras do time na wiki)")
        text = " | ".join(warnings)
        self.assertIn("voz passiva", text)
        self.assertIn("etc.", text)
        self.assertIn("parênteses longos", text)

    def test_termo_nao_aprovado(self):
        warnings = style.check("A reneg gera um acordo.", {"reneg": "Renegociação"})
        self.assertIn("termo não aprovado «reneg»: use «Renegociação»", warnings)
        self.assertEqual(style.check("A renegociação gera um acordo.", {"reneg": "Renegociação"}), [])

    def test_ignora_wikilinks_codigo_e_marcacao(self):
        self.assertEqual(style.check("Veja [[Renegociação]] e `reneg`."), [])

    def test_avisos_aparecem_na_nota(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "A.md").write_text("---\nsinonimos: [coisa]\n---\nA coisa é feita pelo time.", encoding="utf-8")
            note = OntologyStore(root).resolve("A")
            self.assertTrue(any("voz passiva" in w for w in note.warnings))
            self.assertTrue(any("termo não aprovado" in w for w in note.warnings))


class ToolsTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = make_ontology(Path(self._tmp.name))
        self.settings = {"ontology": {"dir": str(self.root)}}

    def tools(self):
        return {t.name: t for t in tool_module.get_tools(ToolContext(settings=self.settings, root=self.root))}

    def test_desligada_sem_pasta(self):
        self.assertEqual(tool_module.get_tools(ToolContext(settings={"ontology": {"dir": ""}}, root=self.root)), [])
        self.assertEqual(tool_module.get_tools(ToolContext(settings={}, root=self.root)), [])
        self.assertEqual(tool_module.get_tools(ToolContext(settings={"ontology": {"dir": str(self.root / "nao-existe")}}, root=self.root)), [])

    def test_quatro_tools_de_leitura(self):
        tools = self.tools()
        self.assertEqual(set(tools), {"ontologia_buscar", "ontologia_conceito", "ontologia_vizinhos", "ontologia_linha_do_tempo"})
        self.assertTrue(all(t.group == "ontology" and not t.needs_approval for t in tools.values()))

    def test_buscar_mostra_aviso_de_rascunho_oculto(self):
        tools = self.tools()
        out = tools["ontologia_buscar"].fn(texto="parcela")
        self.assertIn("1 rascunho(s)", out)
        out = tools["ontologia_buscar"].fn(texto="parcela", incluir_rascunhos="sim")
        self.assertIn("NÃO CONFIRMADO", out)

    def test_conceito_e_vizinhos_e_linha_do_tempo(self):
        tools = self.tools()
        self.assertIn("Termos não aprovados (sinônimos): reneg", tools["ontologia_conceito"].fn(nome="reneg"))
        self.assertIn("não encontrado", tools["ontologia_conceito"].fn(nome="Inexistente"))
        self.assertIn("→ executada_por: CRM", tools["ontologia_vizinhos"].fn(nome="Renegociação"))
        self.assertIn("Waiting Deploy → Done", tools["ontologia_linha_do_tempo"].fn(assunto="Renegociação"))

    def test_argumentos_validados_pela_ontologia_de_tools(self):
        tool = self.tools()["ontologia_vizinhos"]
        self.assertEqual(tool.check_args({"nome": "CRM", "profundidade": "2"}), {"nome": "CRM", "profundidade": 2})


class AgentIntegrationTests(unittest.TestCase):
    def test_ontologia_liga_sozinha_quando_configurada(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_ontology(Path(tmp) / "ont")
            from server import settings as cfg
            settings = cfg.load_settings()
            settings["ontology"]["dir"] = str(root)
            agent = build_agent(settings, [], memory_path=Path(tmp) / "m.json")
            names = {t.name for t in agent.tools}
            self.assertIn("ontologia_buscar", names)
            self.assertIn("Ontologia de Cobrança: disponível", agent.system_prompt)
            settings["ontology"]["dir"] = ""
            names = {t.name for t in build_agent(settings, [], memory_path=Path(tmp) / "m.json").tools}
            self.assertNotIn("ontologia_buscar", names)

    def test_prompt_marca_ontologia_indisponivel(self):
        prompt = build_system_prompt("p", "", "", ["ontology"], {})
        self.assertIn("Ontologia de Cobrança: indisponível", prompt)


if __name__ == "__main__":
    unittest.main()
