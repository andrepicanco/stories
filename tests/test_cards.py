"""Testes da criação de cards (Azure DevOps simulado): validações, payload, campos ausentes e travamento."""
import tempfile
import unittest
from pathlib import Path

from integrations import azure_client
from integrations.board_url import parse_board_url
from server import cards, history
from server import settings as cfg

URL = "https://dev.azure.com/Org/Meu%20Projeto/_boards/board/t/Meu%20Time/Stories"
DESC, AC, RES = "System.Description", "Microsoft.VSTS.Common.AcceptanceCriteria", "Custom.recursos"


class FakeAzure:
    """Mesma interface que `azure_client` usa em cards.py; o patch é o real."""

    def __init__(self, children=(10, 11), missing=(), types=None):
        self.children, self.missing, self.types = list(children), set(missing), types or {}
        self.created = []
        self.build_create_patch = azure_client.build_create_patch

    def list_children(self, ctx, epic_id):
        return [{"id": i} for i in self.children]

    def resolve_field_refs(self, ctx, wit, names):
        refs = {"description": DESC, "acceptance_criteria": AC, "impacted_resources": RES}
        return {k: v for k, v in refs.items() if k not in self.missing}, sorted(self.missing)

    def field_type(self, ctx, ref):
        return self.types.get(ref, "html")

    def team_area_paths(self, ctx):
        return "Meu Projeto\\Meu Time", [("Meu Projeto\\Meu Time", False)]

    def create_work_item(self, ctx, wit, patch):
        self.created.append((wit, patch))
        return {"id": 777, "url": "https://dev.azure.com/Org/Meu%20Projeto/_workitems/edit/777"}


def request(**overrides) -> cards.CardRequest:
    base = dict(card_type="Technical Story", epic_id=5, related=[10], title="Meu card",
                card_html="<h2>Contexto</h2><p>Texto</p>", resources_html="<ul><li>repo-a</li></ul>",
                criteria_html="<p><strong>CA1</strong> — x</p>")
    base.update(overrides)
    return cards.CardRequest(**base)


class PrepareTests(unittest.TestCase):
    def setUp(self):
        self.ctx = parse_board_url(URL)
        self.settings = cfg.load_settings()

    def prepare(self, azure=None, **overrides):
        return cards.prepare(self.ctx, self.settings, request(**overrides), azure or FakeAzure())

    def ops(self, prepared):
        return {(o["path"], o["value"] if isinstance(o["value"], str) else o["value"]["rel"]) for o in prepared.patch}

    def test_payload_has_fields_html_parent_and_related(self):
        prepared = self.prepare()
        by_path = {}
        for op in prepared.patch:
            by_path.setdefault(op["path"], []).append(op["value"])
        self.assertEqual(by_path["/fields/System.Title"], ["Meu card"])
        self.assertEqual(by_path["/fields/System.AreaPath"], ["Meu Projeto\\Meu Time"])
        self.assertEqual(by_path[f"/fields/{DESC}"], ["<h2>Contexto</h2><p>Texto</p>"])
        self.assertIn("<strong>CA1</strong>", by_path[f"/fields/{AC}"][0])
        self.assertEqual(by_path[f"/fields/{RES}"], ["<ul><li>repo-a</li></ul>"])
        rels = {v["rel"]: v["url"] for v in by_path["/relations/-"]}
        self.assertTrue(rels["System.LinkTypes.Hierarchy-Reverse"].endswith("/workItems/5"))
        self.assertTrue(rels["System.LinkTypes.Related"].endswith("/workItems/10"))
        self.assertEqual(prepared.work_item_type, "Technical Story")
        self.assertEqual(prepared.warnings, [])

    def test_html_is_sanitized_before_sending(self):
        prepared = self.prepare(card_html="<p>ok</p><script>alert(1)</script>")
        sent = next(o["value"] for o in prepared.patch if o["path"] == f"/fields/{DESC}")
        self.assertEqual(sent, "<p>ok</p>")

    def test_validations(self):
        cases = [
            (dict(title=""), "título"),
            (dict(title="Nova História"), "título"),
            (dict(title="x" * 256), "limite"),
            (dict(card_html=""), "vazio"),
            (dict(card_html="<script>x</script>"), "vazio"),
            (dict(epic_id=None), "Épico"),
            (dict(card_type="Bug"), "inválido"),
            (dict(related=[10, 999]), "#999"),
        ]
        for overrides, fragment in cases:
            with self.assertRaises(cards.CardError, msg=str(overrides)) as ctx:
                self.prepare(**overrides)
            self.assertIn(fragment, str(ctx.exception), msg=str(overrides))

    def test_related_are_deduplicated_and_blank_fields_omitted(self):
        prepared = self.prepare(related=[10, 10, 11], resources_html="", criteria_html="")
        related = [o for o in prepared.patch if o["path"] == "/relations/-" and o["value"]["rel"].endswith("Related")]
        self.assertEqual(len(related), 2)
        paths = {o["path"] for o in prepared.patch}
        self.assertNotIn(f"/fields/{AC}", paths)
        self.assertNotIn(f"/fields/{RES}", paths)

    def test_type_without_resources_field_appends_to_description(self):
        prepared = self.prepare(FakeAzure(missing={"impacted_resources"}), card_type="Spike")
        paths = {o["path"] for o in prepared.patch}
        self.assertNotIn(f"/fields/{RES}", paths)
        description = next(o["value"] for o in prepared.patch if o["path"] == f"/fields/{DESC}")
        self.assertIn("<h2>Recursos impactados</h2><ul><li>repo-a</li></ul>", description)
        self.assertEqual(len(prepared.warnings), 1)

    def test_missing_description_field_is_an_error(self):
        with self.assertRaises(cards.CardError):
            self.prepare(FakeAzure(missing={"description"}))

    def test_plain_text_field_receives_text_not_html(self):
        prepared = self.prepare(FakeAzure(types={RES: "plainText"}))
        sent = next(o["value"] for o in prepared.patch if o["path"] == f"/fields/{RES}")
        self.assertEqual(sent, "- repo-a")

    def test_create_returns_link_and_sends_once(self):
        azure = FakeAzure()
        prepared = cards.prepare(self.ctx, self.settings, request(), azure)
        result = cards.create(self.ctx, prepared, azure)
        self.assertEqual((result["id"], result["title"]), (777, "Meu card"))
        self.assertTrue(result["url"].endswith("/_workitems/edit/777"))
        self.assertEqual(len(azure.created), 1)
        self.assertEqual(azure.created[0][0], "Technical Story")

    def test_dry_run_style_prepare_does_not_create(self):
        azure = FakeAzure()
        cards.prepare(self.ctx, self.settings, request(), azure)
        self.assertEqual(azure.created, [])


class HistoryLockTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._old = history.DB_PATH
        history.DB_PATH = Path(self.tmp.name) / "h.db"

    def tearDown(self):
        history.DB_PATH = self._old
        self.tmp.cleanup()

    def test_created_story_is_locked_and_keeps_final_title(self):
        story = history.create()
        history.save_draft(story["id"], "Rascunho", {"text": "<p>a</p>"})
        history.mark_created(story["id"], 777, "https://x/777", "Título final")
        locked = history.save_draft(story["id"], "Tentativa", {"text": "<p>b</p>"})
        self.assertEqual((locked["status"], locked["title"], locked["card_id"]), ("created", "Título final", 777))
        self.assertEqual(locked["state"], {"text": "<p>a</p>"})          # estado final preservado
        recent = history.list_recent()[0]
        self.assertEqual((recent["status"], recent["card_id"], recent["card_url"]), ("created", 777, "https://x/777"))


if __name__ == "__main__":
    unittest.main()
