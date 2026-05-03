"""PolyAgent - Kite-native Polymarket copy-trading service."""

import re
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field, field_validator

from polyagent.db import get_db, init_db
from polyagent.passport import PassportClient, SessionInfo


passport: PassportClient | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global passport
    passport = PassportClient()
    await init_db()
    yield
    await passport.close()


app = FastAPI(
    title="PolyAgent",
    description="Polymarket copy-trading agent on Kite",
    version="0.0.3",
    lifespan=lifespan,
)


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
    target_wallet: str = Field(description="Polygon address of the whale to copy")

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


class SignalResponse(BaseModel):
    target_wallet: str
    market_id: str
    market_question: str
    side: str
    size_usdc: float
    price: float
    confidence: float
    reasoning: str
    subscriber_session: str
    remaining_budget_usdc: float


# --- Routes ---

@app.get("/health", response_model=HealthResponse)
async def health():
    return HealthResponse(status="ok", service="polyagent", version="0.0.3")


@app.post("/subscribe", response_model=SubscribeResponse)
async def subscribe(
    req: SubscribeRequest,
    session: Annotated[SessionInfo, Depends(require_active_session)],
):
    """Add a target whale wallet to copy-track for this session."""
    async with get_db() as db:
        try:
            cursor = await db.execute(
                "INSERT INTO subscriptions (session_id, agent_id, target_wallet) "
                "VALUES (?, ?, ?)",
                (session.session_id, session.agent_id, req.target_wallet),
            )
            await db.commit()
            sub_id = cursor.lastrowid
        except Exception as e:
            # UNIQUE constraint — already subscribed
            if "UNIQUE" in str(e):
                raise HTTPException(
                    409,
                    f"Already subscribed to {req.target_wallet}",
                )
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
    """List all active subscriptions for this session."""
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
    """Soft-delete a subscription. Caller must own the session."""
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


@app.get("/signal/sample", response_model=SignalResponse)
async def sample_signal(
    session: Annotated[SessionInfo, Depends(require_active_session)],
):
    return SignalResponse(
        target_wallet="0xPLACEHOLDER",
        market_id="0xPLACEHOLDER",
        market_question="Will BTC close above 100k on Dec 31?",
        side="YES",
        size_usdc=50.0,
        price=0.62,
        confidence=0.78,
        reasoning="Tracked whale opened position at 0.62",
        subscriber_session=session.session_id,
        remaining_budget_usdc=session.remaining_budget,
    )
