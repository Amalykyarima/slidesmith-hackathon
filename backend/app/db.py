import json
import sqlite3
from contextlib import contextmanager
from typing import Any, Iterator

from .config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS styles (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    filename TEXT NOT NULL,
    path TEXT NOT NULL,
    profile TEXT NOT NULL,
    preview_status TEXT NOT NULL DEFAULT 'pending',
    preview_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS images (
    id TEXT PRIMARY KEY,
    filename TEXT NOT NULL,
    path TEXT NOT NULL,
    width INTEGER,
    height INTEGER,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS generations (
    id TEXT PRIMARY KEY,
    style_id TEXT,
    title TEXT,
    mode TEXT NOT NULL,
    request TEXT NOT NULL,
    slides TEXT NOT NULL,
    warnings TEXT NOT NULL DEFAULT '[]',
    path TEXT NOT NULL,
    preview_status TEXT NOT NULL DEFAULT 'pending',
    preview_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with connect() as conn:
        conn.executescript(SCHEMA)
        # Added later: who owns each row (the signed-in teacher; "" when sign-in is off),
        # and how many times a deck has been edited (so browsers fetch fresh previews).
        added = [(t, "owner TEXT NOT NULL DEFAULT ''") for t in ("styles", "images", "generations")]
        added.append(("generations", "rev INTEGER NOT NULL DEFAULT 0"))
        for table, column in added:
            try:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {column}")
            except sqlite3.OperationalError:
                pass  # already there


def one(sql: str, params: tuple = ()) -> dict[str, Any] | None:
    with connect() as conn:
        row = conn.execute(sql, params).fetchone()
        return dict(row) if row else None


def many(sql: str, params: tuple = ()) -> list[dict[str, Any]]:
    with connect() as conn:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]


def run(sql: str, params: tuple = ()) -> None:
    with connect() as conn:
        conn.execute(sql, params)


def dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False)


def loads(text: str | None, default: Any = None) -> Any:
    if not text:
        return default
    return json.loads(text)
