import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from agent.generation import parse_output
from agent.knowledge import events, ingest
from agent.knowledge.store import OntologyStore
from agent.knowledge.suggestions import save_suggestions
from integrations import azure_client as az

BOARD = "https://dev.azure.com/Org/Proj/_boards/board/t/Time/Stories"


def make_root(tmp: Path) -> Path:
    root = tmp / "ont"
    (root / "Conceitos").mkdir(parents=True)
    (root / "Conceitos" / "Renegociação.md").write_text(
        "---\ntipo: conceito\nsinonimos: [reneg]\n---\nA renegociação troca as condições de uma dívida.", encoding="utf-8")
    (root / "_rascunhos" / "conceito").mkdir(parents=True)
    (root / "_rascunhos" / "conceito" / "Parcela.md").write_text("---\ntipo: conceito\n---\nA parcela divide o acordo.", encoding="utf-8")
    return root


class EventFilesTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = make_root(Path(self._tmp.name))

    def test_link_so_para_conceitos_validados_e_palavra_inteira(self):
        store = OntologyStore(self.root)
        self.assertEqual(events.link_concepts(store, "[RENEG] Consulta de planos"), ["Renegociação"])
        self.assertEqual(events.link_concepts(store, "Ajuste da parcela do acordo"), [])      # Parcela é rascunho
        self.assertEqual(events.link_concepts(store, "renegociações em lote"), [])           # não é palavra inteira

    def test_formata_sem_barra_vertical_no_texto(self):
        line = events.format_event("2026-10-02", "card:1", "A | B → C: título | com barra", ["Renegociação"])
        self.assertEqual(line.count(" | "), 3)
        self.assertTrue(line.endswith("[[Renegociação]]"))

    def test_add_events_ordena_deduplica_e_separa_por_mes(self):
        a = events.format_event("2026-10-05", "card:1", "To Do → Done: A", [])
        b = events.format_event("2026-10-02", "card:2", "criado em To Do: B", [])
        c = events.format_event("2026-09-30", "card:3", "To Do → Done: C", [])
        self.assertEqual(events.add_events(self.root, [a, b, c, a]), 3)
        self.assertEqual(events.add_events(self.root, [a, b]), 0)                              # idempotente
        october = (self.root / "Eventos" / "2026-10.md").read_text(encoding="utf-8")
        self.assertLess(october.index("2026-10-02"), october.index("2026-10-05"))
        self.assertTrue((self.root / "Eventos" / "2026-09.md").exists())
        store = OntologyStore(self.root)
        self.assertEqual(store.events()[0][0], "2026-10-05")                                   # lido pela timeline

    def test_card_criado_gera_evento_com_link(self):
        settings = {"ontology": {"dir": str(self.root)}}
        events.card_created(settings, 300912, "Consulta de reneg via API", "Technical Story", epic_id=267048)
        text = (self.root / "Eventos" / f"{date.today():%Y-%m}.md").read_text(encoding="utf-8")
        self.assertIn("card:300912", text)
        self.assertIn("criado (Technical Story)", text)
        self.assertIn("[[Renegociação]]", text)

    def test_card_criado_nunca_levanta(self):
        events.card_created({"ontology": {"dir": ""}}, 1, "t", "Spike")                          # desligada: nada acontece
        with mock.patch.object(events, "add_events", side_effect=OSError("disco cheio")), \
             mock.patch.object(ingest, "log"):
            events.card_created({"ontology": {"dir": str(self.root)}}, 1, "t", "Spike")


class FakeClient:
    """Cliente educado simulado: devolve WIQL, lote de campos e updates por card."""

    def __init__(self, ids, updates, fields=None):
        self.ids, self.updates, self.requests = ids, updates, 0
        self.fields = fields or {i: {"System.Title": f"Card {i} de reneg", "System.WorkItemType": "User Story",
                                     "System.ChangedDate": "2026-10-05T10:00:00Z"} for i in ids}
        self.urls = []

    def post_json(self, url, body):
        self.requests += 1
        self.urls.append(url)
        if "/wiql" in url:
            return {"workItems": [{"id": i} for i in self.ids]}
        return {"value": [{"id": i, "fields": f} for i, f in self.fields.items()]}

    def get_json(self, url):
        self.requests += 1
        self.urls.append(url)
        card = int(url.split("/workitems/")[1].split("/")[0])
        return {"value": self.updates[card]}


def update(day, old=None, new=None):
    fields = {"System.ChangedDate": {"newValue": f"{day}T09:00:00Z"}}
    if new:
        fields["System.State"] = {"newValue": new, **({"oldValue": old} if old else {})}
    return {"fields": fields}


class SyncEventsTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        tmp = Path(self._tmp.name)
        self.root = make_root(tmp)
        self.settings = {"azure": {"board_url": BOARD}, "ontology": {"dir": str(self.root), "events_max_items": 100}}
        for name, value in (("STATE_PATH", tmp / "state.json"), ("LOG_PATH", tmp / "log.txt")):
            patcher = mock.patch.object(ingest, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = mock.patch.object(az, "team_area_paths", return_value=("Proj\\Time", [("Proj\\Time", True)]))
        patcher.start()
        self.addCleanup(patcher.stop)

    def sync(self, client, **kw):
        return events.sync_events(self.settings, client=client, today=date(2026, 10, 6), **kw)

    def test_ensaio_conta_cards_e_nao_grava(self):
        client = FakeClient([1, 2], {})
        summary = self.sync(client, dry_run=True)
        self.assertEqual(summary["cards_alterados"], 2)
        self.assertEqual(summary["desde"], "2026-09-06")                                       # padrão: 30 dias
        self.assertEqual(client.requests, 1)                                                   # só a consulta WIQL
        self.assertFalse((self.root / "Eventos").exists())

    def test_grava_mudancas_de_estado_e_avanca_a_marca(self):
        updates = {
            1: [update("2026-09-01", None, "To Do"), update("2026-10-02", "Waiting Deploy", "Done"), update("2026-10-03")],
            2: [update("2026-10-04", "To Do", "In Progress")],
        }
        summary = self.sync(FakeClient([1, 2], updates), dry_run=False)
        self.assertEqual(summary["eventos_novos"], 2)                                          # a de 01/09 é anterior à janela
        text = (self.root / "Eventos" / "2026-10.md").read_text(encoding="utf-8")
        self.assertIn("2026-10-02 | card:1 | Waiting Deploy → Done: Card 1 de reneg | [[Renegociação]]", text)
        self.assertIn("card:2 | To Do → In Progress", text)
        self.assertEqual(json.loads(ingest.STATE_PATH.read_text(encoding="utf-8"))["events"]["since"], "2026-10-05")
        again = self.sync(FakeClient([1, 2], updates), dry_run=False)
        self.assertEqual(again["eventos_novos"], 0)                                            # idempotente

    def test_teto_limita_e_nao_passa_da_marca(self):
        self.settings["ontology"]["events_max_items"] = 1
        summary = self.sync(FakeClient([1, 2], {1: [update("2026-10-02", "A", "B")]}), dry_run=False)
        self.assertTrue(summary["limitado_pelo_teto"])
        self.assertEqual(summary["cards_alterados"], 1)

    def test_sem_board_ou_pasta(self):
        self.settings["azure"]["board_url"] = ""
        with self.assertRaises(ingest.IngestError):
            self.sync(FakeClient([], {}))


class SuggestionTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        tmp = Path(self._tmp.name)
        self.root = make_root(tmp)
        self.settings = {"ontology": {"dir": str(self.root)}}
        for name, value in (("STATE_PATH", tmp / "state.json"), ("LOG_PATH", tmp / "log.txt")):
            patcher = mock.patch.object(ingest, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_grava_rascunho_com_fonte_e_descarta_sem_fonte(self):
        raw = [{"nome": "Acordo", "tipo": "conceito", "descricao": "O acordo registra o que o cliente aceitou.", "fonte": "card:288965"},
               {"nome": "Sem fonte", "tipo": "conceito", "descricao": "Texto qualquer."}]
        self.assertEqual(save_suggestions(None, self.settings, raw), ["Acordo"])
        note = OntologyStore(self.root).resolve("Acordo")
        self.assertTrue(note.is_draft)
        self.assertEqual(note.sources, ["geracao:card:288965"])
        self.assertIsNone(OntologyStore(self.root).resolve("Sem fonte"))

    def test_sem_pasta_ou_sem_sugestoes_nao_faz_nada(self):
        self.assertEqual(save_suggestions(None, {"ontology": {"dir": ""}}, [{"nome": "X", "descricao": "Y", "fonte": "z"}]), [])
        self.assertEqual(save_suggestions(None, self.settings, []), [])

    def test_aplica_padrao_ste_com_uma_reescrita(self):
        long_text = " ".join(["palavra"] * 30) + "."

        class LLM:
            calls = 0

            def chat(self, messages, tools):
                LLM.calls += 1
                return SimpleNamespace(content="O acordo registra a aceitação do cliente.")

        raw = [{"nome": "Acordo", "descricao": long_text, "fonte": "wiki:/A"}]
        self.assertEqual(save_suggestions(LLM(), self.settings, raw), ["Acordo"])
        self.assertEqual(LLM.calls, 1)
        self.assertIn("aceitação do cliente", OntologyStore(self.root).resolve("Acordo").body)


class ContractTests(unittest.TestCase):
    def test_parse_output_le_e_limita_as_sugestoes(self):
        data = {"mode": "draft", "card_html": "<p>x</p>", "title": "t", "ontology_suggestions": [
            {"nome": f"C{i}", "descricao": "d", "fonte": "f"} for i in range(5)] + ["lixo"]}
        parsed = parse_output(json.dumps(data))
        self.assertEqual(len(parsed["ontology_suggestions"]), 3)
        self.assertEqual(parse_output(json.dumps({"card_html": "<p>x</p>"}))["ontology_suggestions"], [])


if __name__ == "__main__":
    unittest.main()
