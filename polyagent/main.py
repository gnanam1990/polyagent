"""PolyAgent - Kite-native Polymarket copy-trading service."""

from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel

from polyagent.passport import PassportClient, SessionInfo


# Singleton client, set up at startup
passport: PassportClient | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global passport
    passport = PassportClient()
    yield
    await passport.close()


app = FastAPI(
    title="PolyAgent",
    description="Polymarket copy-trading agent on Kite",
    version="0.0.2",
    lifespan=lifespan,
)


# --- Auth dependency ---

async def require_active_session(
    x_kite_session: Annotated[str | None, Header()] = None,
) -> SessionInfo:
    """Reject requests that don't carry a valid, active kpass session."""
    if not x_kite_session:
        raise HTTPException(
            status_code=401,
            detail="Missing X-Kite-Session header. Pass your kpass session ID.",
        )

    session = await passport.get_session(x_kite_session)
    if session is None:
        raise HTTPException(
            status_code=403,
            detail=f"Session {x_kite_session} not found in Kite Passport.",
        )

    if not session.is_active:
        raise HTTPException(
            status_code=403,
            detail=f"Session is {session.status}, not active.",
        )

    if session.remaining_budget <= 0:
        raise HTTPException(
            status_code=402,
            detail="Session budget exhausted. Create a new session.",
        )

    return session


# --- Models ---

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
    return HealthResponse(status="ok", service="polyagent", version="0.0.2")


@app.get("/signal/sample", response_model=SignalResponse)
async def sample_signal(
    session: Annotated[SessionInfo, Depends(require_active_session)],
):
    """Returns a sample signal. Requires a valid kpass session."""
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
