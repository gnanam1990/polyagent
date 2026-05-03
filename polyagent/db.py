"""SQLite database — async, single-file, WAL mode for concurrent reads."""

import aiosqlite
from contextlib import asynccontextmanager
from pathlib import Path


DB_PATH = Path(__file__).parent.parent / "polyagent.db"


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


async def init_db():
    """Create tables if they don't exist. Idempotent."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript(SCHEMA)
        await db.execute("PRAGMA journal_mode=WAL")
        await db.commit()


@asynccontextmanager
async def get_db():
    """Async context manager for a database connection."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        yield db
