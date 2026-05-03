"""Polymarket gamma-api client — market metadata enrichment.

Used to enrich on-chain fills with human-readable market context
(question, condition_id, current price, etc.).

This endpoint is publicly accessible from India without VPN.
The data-api/trades endpoint is geoblocked, but gamma-api/markets is not.
"""

import httpx
from typing import Optional


GAMMA_BASE = "https://gamma-api.polymarket.com"


class PolymarketClient:
    """Async client for Polymarket gamma-api."""

    def __init__(self):
        self._client = httpx.AsyncClient(timeout=10.0)
        # In-memory cache: token_id -> market_info (markets don't change often)
        self._token_cache: dict[str, dict] = {}

    async def close(self):
        await self._client.aclose()

    async def get_market_by_token(self, token_id: str) -> Optional[dict]:
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

        # Determine which outcome our token_id corresponds to
        clob_ids_raw = m.get("clobTokenIds", "[]")
        if isinstance(clob_ids_raw, str):
            import json
            try:
                clob_ids = json.loads(clob_ids_raw)
            except json.JSONDecodeError:
                clob_ids = []
        else:
            clob_ids = clob_ids_raw

        outcomes_raw = m.get("outcomes", '["Yes", "No"]')
        if isinstance(outcomes_raw, str):
            import json
            try:
                outcomes = json.loads(outcomes_raw)
            except json.JSONDecodeError:
                outcomes = ["Yes", "No"]
        else:
            outcomes = outcomes_raw

        outcome = "Unknown"
        for i, tid in enumerate(clob_ids):
            if str(tid) == str(token_id) and i < len(outcomes):
                outcome = outcomes[i]
                break

        prices_raw = m.get("outcomePrices", "[]")
        if isinstance(prices_raw, str):
            import json
            try:
                prices = json.loads(prices_raw)
            except json.JSONDecodeError:
                prices = []
        else:
            prices = prices_raw

        current_price = None
        for i, tid in enumerate(clob_ids):
            if str(tid) == str(token_id) and i < len(prices):
                try:
                    current_price = float(prices[i])
                except (TypeError, ValueError):
                    pass
                break

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

