# PolyAgent — Hard-Earned Context

This file captures non-obvious decisions and verified facts. Do NOT change these without checking the original investigation. Each was discovered through real RPC queries and live testing.

## What this is

PolyAgent is a Polymarket copy-trading signal service that runs on Kite Mainnet (launched April 30, 2026). It exposes auth-gated endpoints that subscribers hit via the kpass CLI. Every request is verified against Kite Passport before returning data.

## Architectural decisions (do not undo)

### 1. Auth uses kpass CLI as a subprocess, NOT a Kite Passport REST API

The Kite Passport REST API is not publicly documented as of May 2026. Kite ships only the kpass CLI for client interactions. PolyAgent's passport.py shells out to `kpass user sessions --session-id {id} --output json` and parses the JSON response. This is the official supported path, not a workaround.

DO NOT replace this with a guessed REST endpoint like `/v1/agent/sessions/{id}` — that path returns 404. We verified.

### 2. Settlement is NOT generic x402

Kite USDC at `0x7aB6f3ed87C42eF0aDb67Ed95090f8bF5240149e` is bridged USDC.e. It does NOT implement EIP-3009 (verified by inspection of the token name "Bridged USDC (Kite AI)" and the bridge architecture via Lucid + LayerZero). Standard coinbase/x402 Python SDK with the `exact` scheme requires EIP-3009 and will not work on Kite.

When we add settlement (Block C), we use `kpass wallet send` for direct wallet-to-wallet transfers, NOT generic x402.

### 3. Polymarket fills come from on-chain, NOT data-api

`https://data-api.polymarket.com/trades?user=...` is geoblocked from many regions (returns silent `[]` instead of 403). We verified this from India.

PolyAgent reads OrderFilled events directly from Polygon. This is more sovereign and not geoblocked.

## Verified facts

### Polymarket V2 contracts (deployed March 2026)

- CTFExchangeV2:        `0xE111180000d2663C0091e4f400237545B87B996B`
- NegRiskCtfExchangeV2: `0xe2222d279d744050d28e00520010520000310F59`

V1 contracts (`0x4bFb41d5...` and `0xC5d563A3...`) are still on chain but mostly unused. DO NOT query them as primary sources.

### V2 OrderFilled event signature

```
event OrderFilled(
    bytes32 indexed orderHash,
    address indexed maker,
    address indexed taker,
    uint8   side,            // 0 = BUY, 1 = SELL
    uint256 tokenId,
    uint256 makerAmountFilled,
    uint256 takerAmountFilled,
    uint256 fee,
    bytes32 builder,
    bytes32 metadata
)
```

Topic hash: `0xd543adfd945773f1a62f74f0ee55a5e3b9b1a28262980ba90b1a89f2ea84d8ee`

This differs from V1 (which had makerAssetId/takerAssetId pair instead of side/tokenId). DO NOT use the V1 signature `0xd0a08e8c4...` — we verified it returns zero matches against V2 contracts.

### Polygon RPC endpoints (verified working from India, no VPN needed)

Priority order (with failover):
1. `https://polygon-bor-rpc.publicnode.com`
2. `https://polygon.drpc.org`
3. `https://1rpc.io/matic`

Verified NOT working from India:
- `polygon-rpc.com` (returns "API key disabled, tenant disabled")
- `rpc.ankr.com/polygon` (requires API key)
- `polygon.llamarpc.com` (empty response)
- `polygon.blockpi.network` (521 error)

### Kite Mainnet

- Chain ID: 2366 (`0x93e`)
- RPC: `https://rpc.gokite.ai/`
- Bridged USDC.e contract: `0x7aB6f3ed87C42eF0aDb67Ed95090f8bF5240149e` (6 decimals)
- Mainnet launched April 30, 2026
- Passport backend: `https://passport.prod.gokite.ai` (used by kpass internally)

### Polymarket gamma-api (works from India)

- Base URL: `https://gamma-api.polymarket.com`
- Market lookup by token ID: `GET /markets?clob_token_ids={token_id}&limit=1`
- Returns `outcomes`, `clobTokenIds`, `outcomePrices` as JSON-encoded strings inside the JSON response (must double-parse)

## Project state at handoff

Working endpoints:
- `GET /health` (open)
- `POST /subscribe` (kpass auth)
- `GET /subscriptions` (kpass auth)
- `DELETE /subscriptions/{id}` (kpass auth)
- `GET /signals/recent?wallet=...` (kpass auth + subscription gate)

End-to-end verified working: subscriber creates kpass session → calls /signals/recent → gets real on-chain Polymarket fills enriched with market context.

Files:
- `polyagent/main.py` — FastAPI app, routes, auth dependency
- `polyagent/passport.py` — Kite Passport client (kpass subprocess)
- `polyagent/db.py` — aiosqlite + schema
- `polyagent/polygon.py` — Polygon RPC client, OrderFilled decoder
- `polyagent/polymarket.py` — gamma-api enrichment client

Not yet built:
- Settlement (Block C) — needs funded wallet
- WebSocket subscription for real-time fills
- Tests (only manual curl tests so far)
- Proper logging
- Docker
- CI

## Out of scope for now

- Don't add web3.py — overkill for our needs and pulls in many deps
- Don't switch from aiosqlite to Postgres until multi-tenant load is real
- Don't try to write our own x402 facilitator — Kite hasn't shipped one and we use kpass-native instead
