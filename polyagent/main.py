"""PolyAgent - Kite-native Polymarket copy-trading service."""

import asyncio
import logging
import re
import sqlite3
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from pydantic import BaseModel, field_validator

from polyagent.db import get_db, init_db
from polyagent.logging_setup import RequestIdMiddleware, configure_logging
from polyagent.passport import PassportClient, SessionInfo
from polyagent.polygon import Fill, PolygonClient
from polyagent.polymarket import PolymarketClient

log = logging.getLogger("polyagent")

passport: PassportClient | None = None
polygon: PolygonClient | None = None
polymarket: PolymarketClient | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global passport, polygon, polymarket
    configure_logging()
    passport = PassportClient()
    polygon = PolygonClient()
    polymarket = PolymarketClient()
    await init_db()
    log.info("polyagent startup complete")
    yield
    await passport.close()
    await polygon.close()
    await polymarket.close()
    log.info("polyagent shutdown complete")


app = FastAPI(
    title="PolyAgent",
    description="Polymarket copy-trading agent on Kite",
    version="0.0.6",
    lifespan=lifespan,
)
app.add_middleware(RequestIdMiddleware)


# --- Auth ---

async def require_active_session(
    x_kite_session: Annotated[str | None, Header()] = None,
) -> SessionInfo:
    if not x_kite_session:
        raise HTTPException(401, "Missing X-Kite-Session header.")
    session = await passport.get_session(x_kite_session)
    if session is None:
        raise HTTPException(403, f"Session {x_kite_session} not found.")
    if not session.is_active:
        raise HTTPException(403, f"Session is {session.status}, not active.")
    if session.remaining_budget <= 0:
        raise HTTPException(402, "Session budget exhausted.")
    return session


# --- Models ---

ETH_ADDR_RE = re.compile(r"^0x[a-fA-F0-9]{40}$")


class SubscribeRequest(BaseModel):
    target_wallet: str

    @field_validator("target_wallet")
    @classmethod
    def validate_address(cls, v: str) -> str:
        if not ETH_ADDR_RE.match(v):
            raise ValueError("target_wallet must be a 0x-prefixed 40-char hex address")
        return v.lower()


class Subscription(BaseModel):
    id: int
    session_id: str
    agent_id: str
    target_wallet: str
    created_at: str
    active: bool


class SubscribeResponse(BaseModel):
    subscription: Subscription
    remaining_budget_usdc: float


class SubscriptionListResponse(BaseModel):
    session_id: str
    count: int
    subscriptions: list[Subscription]


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str


class Signal(BaseModel):
    """An on-chain Polymarket fill, enriched with market context."""
    # On-chain
    block_number: int
    tx_hash: str
    target_wallet: str
    role: str                       # "maker" | "taker"
    side: str                       # "BUY" | "SELL"
    exchange: str                   # "ctf" | "negrisk"
    token_id: str
    usdc_amount: float
    token_amount: float
    fill_price: float

    # Enriched (None if market not found in gamma-api)
    market_question: str | None = None
    market_condition_id: str | None = None
    outcome: str | None = None
    current_market_price: float | None = None
    market_volume: float | None = None
    market_end_date: str | None = None
    market_slug: str | None = None


class SignalsResponse(BaseModel):
    target_wallet: str
    lookback_blocks: int
    fill_count: int
    signals: list[Signal]
    subscriber_session: str
    remaining_budget_usdc: float


# --- Routes ---

@app.get("/health", response_model=HealthResponse)
async def health():
    return HealthResponse(status="ok", service="polyagent", version="0.0.6")


@app.post("/subscribe", response_model=SubscribeResponse)
async def subscribe(
    req: SubscribeRequest,
    session: Annotated[SessionInfo, Depends(require_active_session)],
):
    async with get_db() as db:
        try:
            cursor = await db.execute(
                "INSERT INTO subscriptions (session_id, agent_id, target_wallet) "
                "VALUES (?, ?, ?)",
                (session.session_id, session.agent_id, req.target_wallet),
            )
            await db.commit()
            sub_id = cursor.lastrowid
        except sqlite3.IntegrityError as e:
            if "UNIQUE" in str(e):
                raise HTTPException(409, f"Already subscribed to {req.target_wallet}") from e
            raise

        row = await (await db.execute(
            "SELECT * FROM subscriptions WHERE id = ?", (sub_id,)
        )).fetchone()

    return SubscribeResponse(
        subscription=Subscription(
            id=row["id"],
            session_id=row["session_id"],
            agent_id=row["agent_id"],
            target_wallet=row["target_wallet"],
            created_at=row["created_at"],
            active=bool(row["active"]),
        ),
        remaining_budget_usdc=session.remaining_budget,
    )


@app.get("/subscriptions", response_model=SubscriptionListResponse)
async def list_subscriptions(
    session: Annotated[SessionInfo, Depends(require_active_session)],
):
    async with get_db() as db:
        rows = await (await db.execute(
            "SELECT * FROM subscriptions WHERE session_id = ? AND active = 1 "
            "ORDER BY created_at DESC",
            (session.session_id,),
        )).fetchall()

    subs = [
        Subscription(
            id=r["id"],
            session_id=r["session_id"],
            agent_id=r["agent_id"],
            target_wallet=r["target_wallet"],
            created_at=r["created_at"],
            active=bool(r["active"]),
        )
        for r in rows
    ]
    return SubscriptionListResponse(
        session_id=session.session_id,
        count=len(subs),
        subscriptions=subs,
    )


@app.delete("/subscriptions/{sub_id}")
async def unsubscribe(
    sub_id: int,
    session: Annotated[SessionInfo, Depends(require_active_session)],
):
    async with get_db() as db:
        cursor = await db.execute(
            "UPDATE subscriptions SET active = 0 "
            "WHERE id = ? AND session_id = ?",
            (sub_id, session.session_id),
        )
        await db.commit()
        if cursor.rowcount == 0:
            raise HTTPException(404, "Subscription not found or not yours.")

    return {"status": "unsubscribed", "id": sub_id}


async def _is_subscribed(session_id: str, wallet: str) -> bool:
    async with get_db() as db:
        row = await (await db.execute(
            "SELECT 1 FROM subscriptions "
            "WHERE session_id = ? AND target_wallet = ? AND active = 1",
            (session_id, wallet.lower()),
        )).fetchone()
    return row is not None


def _fill_role(fill: Fill, wallet: str) -> str:
    return "maker" if fill.maker.lower() == wallet.lower() else "taker"


async def _enrich(fill: Fill, wallet: str) -> Signal:
    info = await polymarket.get_market_by_token(str(fill.token_id))
    return Signal(
        block_number=fill.block_number,
        tx_hash=fill.tx_hash,
        target_wallet=wallet.lower(),
        role=_fill_role(fill, wallet),
        side=fill.side_label,
        exchange=fill.exchange,
        token_id=str(fill.token_id),
        usdc_amount=fill.usdc_amount,
        token_amount=fill.token_amount,
        fill_price=fill.price,
        market_question=info["question"] if info else None,
        market_condition_id=info["condition_id"] if info else None,
        outcome=info["outcome"] if info else None,
        current_market_price=info["current_price"] if info else None,
        market_volume=info["volume"] if info else None,
        market_end_date=info["end_date"] if info else None,
        market_slug=info["slug"] if info else None,
    )


@app.get("/signals/recent", response_model=SignalsResponse)
async def signals_recent(
    session: Annotated[SessionInfo, Depends(require_active_session)],
    wallet: str = Query(..., description="Target whale wallet to query fills for"),
    limit: int = Query(10, ge=1, le=50),
    lookback_blocks: int = Query(10000, ge=100, le=100000),
):
    """Fetch recent on-chain fills for a tracked whale, enriched with market context.

    Caller must have an active subscription to `wallet` for this session.
    """
    if not ETH_ADDR_RE.match(wallet):
        raise HTTPException(422, "wallet must be a 0x-prefixed 40-char hex address")

    wallet = wallet.lower()

    if not await _is_subscribed(session.session_id, wallet):
        raise HTTPException(
            403,
            f"Not subscribed to {wallet}. POST /subscribe first.",
        )

    fills = await polygon.get_fills_for_wallet(
        wallet, lookback_blocks=lookback_blocks
    )
    fills = fills[:limit]

    signals = await asyncio.gather(*[_enrich(f, wallet) for f in fills])

    return SignalsResponse(
        target_wallet=wallet,
        lookback_blocks=lookback_blocks,
        fill_count=len(signals),
        signals=signals,
        subscriber_session=session.session_id,
        remaining_budget_usdc=session.remaining_budget,
    )
