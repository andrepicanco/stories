"""Histórico persistente (SQLite) das histórias, incluindo o estado completo da página."""
import json
import os
import sqlite3
from contextlib import contextmanager
import time
import uuid
from pathlib import Path

DB_PATH = Path(os.environ.get("STORIES_DB_PATH") or Path(__file__).resolve().parent.parent / "storage" / "history.db")


@contextmanager
def _conn():
    """Conexão que confirma a transação ao sair e SEMPRE é fechada (o `with` do sqlite3 não fecha,
    o que deixava o arquivo do banco preso no Windows)."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        with conn:
            conn.execute(
                """CREATE TABLE IF NOT EXISTS stories (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'draft',
                    card_id INTEGER,
                    card_url TEXT,
                    state TEXT NOT NULL DEFAULT '{}',
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    rating TEXT,
                    iterations INTEGER NOT NULL DEFAULT 0
                )"""
            )
            # Bancos criados antes dessas colunas ganham-nas na primeira abertura.
            columns = {col["name"] for col in conn.execute("PRAGMA table_info(stories)")}
            if "rating" not in columns:
                conn.execute("ALTER TABLE stories ADD COLUMN rating TEXT")
            if "iterations" not in columns:
                conn.execute("ALTER TABLE stories ADD COLUMN iterations INTEGER NOT NULL DEFAULT 0")
            yield conn
    finally:
        conn.close()


def create(title: str = "Nova História") -> dict:
    now = time.time()
    story_id = uuid.uuid4().hex
    with _conn() as conn:
        conn.execute(
            "INSERT INTO stories (id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
            (story_id, title, now, now),
        )
    return get(story_id)


def get(story_id: str) -> dict | None:
    with _conn() as conn:
        row = conn.execute("SELECT * FROM stories WHERE id = ?", (story_id,)).fetchone()
    return _row(row) if row else None


def delete(story_id: str) -> bool:
    """Remove só do histórico local; nada é alterado no Azure DevOps."""
    with _conn() as conn:
        return conn.execute("DELETE FROM stories WHERE id = ?", (story_id,)).rowcount > 0


RATINGS = ("good", "neutral", "bad")


def set_rating(story_id: str, rating: str) -> dict | None:
    """Grava o último feedback humano (bom/neutro/ruim) da história, sobrescrevendo o anterior.
    Não altera `updated_at`: avaliar não deve reordenar a lista de recentes."""
    if rating not in RATINGS:
        raise ValueError(f"Avaliação inválida: {rating!r}. Use {', '.join(RATINGS)}.")
    with _conn() as conn:
        conn.execute("UPDATE stories SET rating = ? WHERE id = ?", (rating, story_id))
    return get(story_id)


def add_iteration(story_id: str) -> int | None:
    """Soma 1 às iterações da história (toda resposta do agente, Gerar ou Responder) e devolve o total, ou None se
    a história não existir. Soma no próprio UPDATE, sem ler antes, e não altera `updated_at`."""
    with _conn() as conn:
        if conn.execute("UPDATE stories SET iterations = iterations + 1 WHERE id = ?", (story_id,)).rowcount == 0:
            return None
        return conn.execute("SELECT iterations FROM stories WHERE id = ?", (story_id,)).fetchone()["iterations"]


def list_recent(limit: int = 30) -> list[dict]:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT id, title, status, card_id, card_url, updated_at FROM stories "
            "ORDER BY updated_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def save_draft(story_id: str, title: str, state: dict) -> dict | None:
    """Autosave. Histórias já criadas no Azure ficam travadas e não aceitam alterações."""
    current = get(story_id)
    if current is None:
        return None
    if current["status"] == "created":
        return current
    with _conn() as conn:
        conn.execute(
            "UPDATE stories SET title = ?, state = ?, updated_at = ? WHERE id = ?",
            (title, json.dumps(state, ensure_ascii=False), time.time(), story_id),
        )
    return get(story_id)


def mark_created(story_id: str, card_id: int, card_url: str, title: str | None = None) -> dict | None:
    """Trava a história: depois de criada no Azure DevOps ela não aceita mais alterações."""
    with _conn() as conn:
        conn.execute(
            "UPDATE stories SET status = 'created', card_id = ?, card_url = ?, updated_at = ?, "
            "title = COALESCE(?, title) WHERE id = ?",
            (card_id, card_url, time.time(), title, story_id),
        )
    return get(story_id)


def _row(row: sqlite3.Row) -> dict:
    data = dict(row)
    data["state"] = json.loads(data["state"] or "{}")
    return data
