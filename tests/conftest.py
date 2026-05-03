"""Test fixtures.

We build a fresh SQLite file per test (POLYAGENT_DB_PATH) and substitute
the FastAPI app's `passport`, `polygon`, `polymarket` globals with
AsyncMock clients so no real subprocess / RPC / HTTP calls are made.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient

from polyagent.passport import SessionInfo


def _future_iso(seconds: int = 3600) -> str:
    return (datetime.now(UTC) + timedelta(seconds=seconds)).isoformat().replace(
        "+00:00", "Z"
    )


def _past_iso(seconds: int = 3600) -> str:
    return (datetime.now(UTC) - timedelta(seconds=seconds)).isoformat().replace(
        "+00:00", "Z"
    )


def make_session(
    session_id: str = "sess_test_123",
    agent_id: str = "agent_polyagent",
    status: str = "active",
    expires_at: str | None = None,
    max_total: float = 100.0,
    spent: float = 0.0,
    reserved: float = 0.0,
) -> SessionInfo:
    return SessionInfo(
        id=session_id,
        agent_id=agent_id,
        status=status,
        max_amount_per_tx=10.0,
        max_total_amount=max_total,
        spent_total=spent,
        reserved_total=reserved,
        expires_at=expires_at or _future_iso(),
    )


@pytest.fixture
def db_path(tmp_path, monkeypatch):
    p = tmp_path / "test.db"
    monkeypatch.setenv("POLYAGENT_DB_PATH", str(p))
    return p


@pytest.fixture
async def app(db_path, monkeypatch):
    """Return the FastAPI app with mocked external clients and an initialised DB."""
    from polyagent import main as main_module
    from polyagent.db import init_db

    await init_db()

    fake_passport = AsyncMock()
    fake_passport.get_session = AsyncMock(return_value=make_session())
    fake_passport.close = AsyncMock()

    fake_polygon = AsyncMock()
    fake_polygon.get_fills_for_wallet = AsyncMock(return_value=[])
    fake_polygon.close = AsyncMock()

    fake_polymarket = AsyncMock()
    fake_polymarket.get_market_by_token = AsyncMock(return_value=None)
    fake_polymarket.close = AsyncMock()

    monkeypatch.setattr(main_module, "passport", fake_passport)
    monkeypatch.setattr(main_module, "polygon", fake_polygon)
    monkeypatch.setattr(main_module, "polymarket", fake_polymarket)

    return main_module.app


@pytest.fixture
async def client(app) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture
def auth_headers() -> dict:
    return {"X-Kite-Session": "sess_test_123"}
