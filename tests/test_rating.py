import json
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path

from server import history, settings


class RatingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._old = history.DB_PATH
        history.DB_PATH = Path(self.tmp.name) / "h.db"

    def tearDown(self):
        history.DB_PATH = self._old
        self.tmp.cleanup()

    def test_new_story_has_no_rating(self):
        self.assertIsNone(history.create()["rating"])

    def test_set_rating_overwrites_the_previous_one(self):
        story = history.create()
        self.assertEqual(history.set_rating(story["id"], "bad")["rating"], "bad")
        self.assertEqual(history.set_rating(story["id"], "good")["rating"], "good")
        self.assertEqual(history.get(story["id"])["rating"], "good")

    def test_invalid_rating_is_rejected_and_nothing_is_saved(self):
        story = history.create()
        for bad in ("", "great", "GOOD", None):
            with self.assertRaises(ValueError):
                history.set_rating(story["id"], bad)
        self.assertIsNone(history.get(story["id"])["rating"])

    def test_unknown_story_returns_none(self):
        self.assertIsNone(history.set_rating("nao-existe", "good"))

    def test_rating_does_not_change_the_recent_order(self):
        old = history.create("Antiga")
        time.sleep(0.02)                              # garante timestamps distintos no Windows
        new = history.create("Nova")
        before = history.get(old["id"])["updated_at"]
        history.set_rating(old["id"], "neutral")
        self.assertEqual(history.get(old["id"])["updated_at"], before)
        self.assertEqual([s["id"] for s in history.list_recent()], [new["id"], old["id"]])

    def test_autosave_keeps_the_rating(self):
        story = history.create()
        history.set_rating(story["id"], "good")
        history.save_draft(story["id"], "Título", {"rating": None})
        self.assertEqual(history.get(story["id"])["rating"], "good")

    def test_old_database_without_rating_column_is_migrated(self):
        history.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(history.DB_PATH)
        conn.execute(
            """CREATE TABLE stories (id TEXT PRIMARY KEY, title TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'draft',
               card_id INTEGER, card_url TEXT, state TEXT NOT NULL DEFAULT '{}',
               created_at REAL NOT NULL, updated_at REAL NOT NULL)""")
        conn.execute("INSERT INTO stories (id, title, created_at, updated_at) VALUES ('a', 'Antiga', 1, 1)")
        conn.commit()
        conn.close()

        story = history.get("a")                     # abrir o banco aplica a migração
        self.assertEqual((story["title"], story["rating"]), ("Antiga", None))
        self.assertEqual(history.set_rating("a", "good")["rating"], "good")
        self.assertEqual(history.get("a")["rating"], "good")   # e uma segunda abertura não repete o ALTER


class FeedbackSettingTests(unittest.TestCase):
    def test_default_requires_human_feedback(self):
        defaults = json.loads(settings.SETTINGS_PATH.read_text(encoding="utf-8"))
        self.assertIs(defaults["evals"]["require_human_feedback"], True)


if __name__ == "__main__":
    unittest.main()
