"""SQLite database — async, single-file, WAL mode for concurrent reads."""

import os
from contextlib import asynccontextmanager
from pathlib import Path

import aiosqlite


def _resolve_db_path() -> Path:
    override = os.environ.get("POLYAGENT_DB_PATH")
    if override:
        return Path(override)
    return Path(__file__).parent.parent / "polyagent.db"


DB_PATH = _resolve_db_path()


SCHEMA = """
CREATE TABLE IF NOT EXISTS subscriptions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id      TEXT NOT NULL,
    agent_id        TEXT NOT NULL,
    target_wallet   TEXT NOT NULL,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    active          INTEGER NOT NULL DEFAULT 1,
    UNIQUE(session_id, target_wallet)
);

CREATE INDEX IF NOT EXISTS idx_sub_session ON subscriptions(session_id);
CREATE INDEX IF NOT EXISTS idx_sub_target  ON subscriptions(target_wallet);
"""


async def init_db() -> None:
    """Create tables if they don't exist. Idempotent."""
    async with aiosqlite.connect(_resolve_db_path()) as db:
        await db.executescript(SCHEMA)
        await db.execute("PRAGMA journal_mode=WAL")
        await db.commit()


@asynccontextmanager
async def get_db():
    """Async context manager for a database connection."""
    async with aiosqlite.connect(_resolve_db_path()) as db:
        db.row_factory = aiosqlite.Row
        yield db
