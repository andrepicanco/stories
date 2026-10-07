"""Contagem de iterações por história (toda resposta do agente) no history.db. Sem rede e sem Azure."""
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

from agent.generation import GenerationResult
from server import history
from server import main as server_main


class IterationsDbTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._old = history.DB_PATH
        history.DB_PATH = Path(self.tmp.name) / "h.db"

    def tearDown(self):
        history.DB_PATH = self._old
        self.tmp.cleanup()

    def test_new_story_starts_at_zero_and_each_call_adds_one(self):
        story = history.create()
        self.assertEqual(story["iterations"], 0)
        self.assertEqual([history.add_iteration(story["id"]) for _ in range(3)], [1, 2, 3])
        self.assertEqual(history.get(story["id"])["iterations"], 3)

    def test_unknown_story_returns_none(self):
        self.assertIsNone(history.add_iteration("nao-existe"))

    def test_stories_count_independently_and_keep_rating(self):
        a, b = history.create("A"), history.create("B")
        history.set_rating(a["id"], "good")
        history.add_iteration(a["id"])
        history.add_iteration(a["id"])
        history.add_iteration(b["id"])
        self.assertEqual((history.get(a["id"])["iterations"], history.get(a["id"])["rating"]), (2, "good"))
        self.assertEqual((history.get(b["id"])["iterations"], history.get(b["id"])["rating"]), (1, None))

    def test_counting_does_not_change_recent_order_or_survive_autosave_overwrite(self):
        old = history.create("Antiga")
        time.sleep(0.02)
        new = history.create("Nova")
        before = history.get(old["id"])["updated_at"]
        history.add_iteration(old["id"])
        self.assertEqual(history.get(old["id"])["updated_at"], before)
        self.assertEqual([s["id"] for s in history.list_recent()], [new["id"], old["id"]])
        history.save_draft(old["id"], "Antiga", {"chat": []})            # o autosave da tela não zera o contador
        self.assertEqual(history.get(old["id"])["iterations"], 1)

    def test_database_with_only_the_rating_column_gets_iterations(self):
        history.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(history.DB_PATH)
        conn.execute(
            """CREATE TABLE stories (id TEXT PRIMARY KEY, title TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'draft',
               card_id INTEGER, card_url TEXT, state TEXT NOT NULL DEFAULT '{}',
               created_at REAL NOT NULL, updated_at REAL NOT NULL, rating TEXT)""")
        conn.execute("INSERT INTO stories (id, title, created_at, updated_at, rating) VALUES ('a', 'Antiga', 1, 1, 'bad')")
        conn.commit()
        conn.close()
        story = history.get("a")                                           # abrir o banco aplica a migração
        self.assertEqual((story["title"], story["rating"], story["iterations"]), ("Antiga", "bad", 0))
        self.assertEqual(history.add_iteration("a"), 1)


def fake_result() -> GenerationResult:
    return GenerationResult(mode="draft", title="T", card_html="<p>x</p>", resources_html="", criteria_html="",
                            comment="ok", questions=[], sentiment="none", learnings_saved=[], steps=[],
                            warnings=[], hit_step_limit=False)


class IterationsRouteTests(unittest.TestCase):
    """Gerar e Responder pelas rotas reais, com o agente simulado: cada resposta bem-sucedida soma 1."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._old = history.DB_PATH
        history.DB_PATH = Path(self.tmp.name) / "h.db"
        self.client = TestClient(server_main.app)    # sem `with`: não sobe as conexões MCP
        self.story = history.create()

    def tearDown(self):
        history.DB_PATH = self._old
        self.tmp.cleanup()

    def run_job(self, path, generate_mock, **extra):
        body = {"story_id": self.story["id"], "brief": "<p>objetivo</p>", **extra}
        with mock.patch.object(server_main, "generate", generate_mock), mock.patch.object(server_main, "LLM"):
            job = self.client.post(path, json=body)
            self.assertEqual(job.status_code, 200, job.text)
            deadline = time.time() + 10
            while time.time() < deadline:
                data = self.client.get(f"/api/jobs/{job.json()['id']}").json()
                if data["status"] != "running":
                    return data
                time.sleep(0.02)
        self.fail("a execução não terminou")

    def iterations(self):
        return history.get(self.story["id"])["iterations"]

    def test_generate_then_replies_count_every_agent_response(self):
        ok = mock.Mock(return_value=fake_result())
        self.assertEqual(self.run_job("/api/generate", ok)["status"], "done")
        self.assertEqual(self.iterations(), 1)                              # o primeiro Gerar já é a iteração 1
        self.assertEqual(self.run_job("/api/reply", ok, reply="<p>ajuste</p>")["status"], "done")
        self.assertEqual(self.run_job("/api/reply", ok, reply="<p>mais um</p>")["status"], "done")
        self.assertEqual(self.iterations(), 3)
        self.assertEqual(self.run_job("/api/generate", ok)["status"], "done")   # gerar de novo também é resposta
        self.assertEqual(self.iterations(), 4)

    def test_failed_run_does_not_count(self):
        boom = mock.Mock(side_effect=RuntimeError("modelo indisponível"))
        job = self.run_job("/api/generate", boom)
        self.assertEqual(job["status"], "error")
        self.assertEqual(self.iterations(), 0)

    def test_request_rejected_before_running_does_not_count(self):
        ok = mock.Mock(return_value=fake_result())
        with mock.patch.object(server_main, "generate", ok):
            res = self.client.post("/api/reply", json={"story_id": self.story["id"], "brief": "<p>x</p>", "reply": ""})
        self.assertEqual(res.status_code, 422)
        ok.assert_not_called()
        self.assertEqual(self.iterations(), 0)

    def test_counter_failure_keeps_the_generation_result_and_warns(self):
        ok = mock.Mock(return_value=fake_result())
        with mock.patch.object(history, "add_iteration", side_effect=sqlite3.OperationalError("disco cheio")):
            job = self.run_job("/api/generate", ok)
        self.assertEqual(job["status"], "done")
        self.assertEqual(job["result"]["card_html"], "<p>x</p>")
        self.assertTrue(any("registrar a iteração" in w for w in job["result"]["warnings"]))


if __name__ == "__main__":
    unittest.main()
