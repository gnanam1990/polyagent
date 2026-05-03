"""Kite Passport client — invokes the kpass CLI as a subprocess.

The Kite Passport REST API isn't publicly documented, but the kpass CLI knows
how to talk to the backend. We shell out to kpass and parse its JSON output.
"""

import asyncio
import json
from datetime import UTC, datetime

from pydantic import BaseModel, Field


class SessionInfo(BaseModel):
    """Subset of session fields we care about."""
    session_id: str = Field(alias="id")
    agent_id: str
    status: str
    max_amount_per_tx: float
    max_total_amount: float
    spent_total: float
    reserved_total: float
    expires_at: str

    model_config = {"populate_by_name": True}

    @property
    def is_active(self) -> bool:
        if self.status != "active":
            return False
        # kpass returns RFC3339 with trailing Z — parse explicitly
        try:
            exp = datetime.fromisoformat(self.expires_at.replace("Z", "+00:00"))
            return datetime.now(UTC) < exp
        except ValueError:
            return False

    @property
    def remaining_budget(self) -> float:
        return max(
            0.0,
            self.max_total_amount - self.spent_total - self.reserved_total,
        )


class PassportClient:
    """Async client for Kite Passport via the kpass CLI."""

    def __init__(self, kpass_path: str = "kpass"):
        self.kpass_path = kpass_path

    async def get_session(self, session_id: str) -> SessionInfo | None:
        """Look up a session by ID. Returns None if not found or invalid."""
        proc = await asyncio.create_subprocess_exec(
            self.kpass_path,
            "user",
            "sessions",
            "--session-id",
            session_id,
            "--output",
            "json",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()

        if proc.returncode != 0:
            return None

        try:
            payload = json.loads(stdout.decode())
        except json.JSONDecodeError:
            return None

        if payload.get("status") != "success":
            return None

        sessions = payload.get("sessions", [])
        if not sessions:
            return None

        raw = sessions[0]
        delegation = raw.get("delegation", {})
        policy = delegation.get("payment_policy", {})
        usage = raw.get("usage", {})

        return SessionInfo(
            id=raw["id"],
            agent_id=raw["agent_id"],
            status=raw["status"],
            max_amount_per_tx=float(policy.get("max_amount_per_tx", 0)),
            max_total_amount=float(policy.get("max_total_amount", 0)),
            spent_total=float(usage.get("spent_total", 0)),
            reserved_total=float(usage.get("reserved_total", 0)),
            expires_at=raw["expires_at"],
        )

    async def close(self):
        """No-op for subprocess client. Kept for API compatibility."""
        pass
