"""Polymarket gamma-api client — market metadata enrichment.

Used to enrich on-chain fills with human-readable market context
(question, condition_id, current price, etc.).

This endpoint is publicly accessible from India without VPN.
The data-api/trades endpoint is geoblocked, but gamma-api/markets is not.
"""

import json
from typing import Any

import httpx

GAMMA_BASE = "https://gamma-api.polymarket.com"


def _parse_json_field(value: Any, default: Any) -> Any:
    """gamma-api returns several fields as JSON-encoded strings inside JSON.
    Accept the raw value if already decoded, else json.loads it.
    """
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return default
    return value if value is not None else default


class PolymarketClient:
    """Async client for Polymarket gamma-api."""

    def __init__(self):
        self._client = httpx.AsyncClient(timeout=10.0)
        # In-memory cache: token_id -> market_info (markets don't change often)
        self._token_cache: dict[str, dict] = {}

    async def close(self):
        await self._client.aclose()

    async def get_market_by_token(self, token_id: str) -> dict | None:
        """Look up market metadata by CTF token_id.

        Returns dict with: question, condition_id, outcome (YES/NO),
        current_price, volume, end_date, slug. None if not found.
        """
        if token_id in self._token_cache:
            return self._token_cache[token_id]

        # gamma-api supports filtering by clob_token_ids
        try:
            resp = await self._client.get(
                f"{GAMMA_BASE}/markets",
                params={"clob_token_ids": token_id, "limit": 1},
            )
            resp.raise_for_status()
            markets = resp.json()
        except httpx.HTTPError:
            return None

        if not markets:
            return None

        m = markets[0]

        clob_ids = _parse_json_field(m.get("clobTokenIds"), [])
        outcomes = _parse_json_field(m.get("outcomes"), ["Yes", "No"])
        prices = _parse_json_field(m.get("outcomePrices"), [])

        token_idx = next(
            (i for i, tid in enumerate(clob_ids) if str(tid) == str(token_id)),
            None,
        )

        outcome = outcomes[token_idx] if token_idx is not None and token_idx < len(outcomes) else "Unknown"

        current_price: float | None = None
        if token_idx is not None and token_idx < len(prices):
            try:
                current_price = float(prices[token_idx])
            except (TypeError, ValueError):
                current_price = None

        info = {
            "question":       m.get("question", "(unknown)"),
            "condition_id":   m.get("conditionId"),
            "outcome":        outcome,
            "current_price":  current_price,
            "volume":         float(m.get("volumeNum", 0) or 0),
            "end_date":       m.get("endDateIso"),
            "slug":           m.get("slug"),
        }
        self._token_cache[token_id] = info
        return info

