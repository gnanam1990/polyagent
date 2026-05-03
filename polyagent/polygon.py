"""Polygon RPC client — reads OrderFilled events from Polymarket V2 exchanges.

Both CTFExchangeV2 and NegRiskCtfExchangeV2 emit:

  event OrderFilled(
      bytes32 indexed orderHash,
      address indexed maker,
      address indexed taker,
      uint8   side,              // 0 = BUY, 1 = SELL
      uint256 tokenId,
      uint256 makerAmountFilled,
      uint256 takerAmountFilled,
      uint256 fee,
      bytes32 builder,
      bytes32 metadata
  )

Side semantics (from the maker's perspective):
  BUY  → maker bought tokenId outcome tokens with USDC
  SELL → maker sold tokenId outcome tokens for USDC
"""

import asyncio
from dataclasses import dataclass
from typing import Optional

import httpx
from eth_utils import keccak


# Polymarket V2 exchange contracts on Polygon (deployed March 2026)
CTF_EXCHANGE     = "0xE111180000d2663C0091e4f400237545B87B996B"
NEGRISK_EXCHANGE = "0xe2222d279d744050d28e00520010520000310F59"

# V2 OrderFilled event signature
ORDERFILLED_TOPIC = "0x" + keccak(
    b"OrderFilled(bytes32,address,address,uint8,uint256,uint256,uint256,uint256,bytes32,bytes32)"
).hex()

# RPC endpoints in priority order — verified working from India (no VPN)
RPC_URLS = [
    "https://polygon-bor-rpc.publicnode.com",
    "https://polygon.drpc.org",
    "https://1rpc.io/matic",
]

# Decimals
USDC_DECIMALS  = 6   # PMCT/USDC.e on Polygon
TOKEN_DECIMALS = 6   # CTF outcome tokens are 6-decimal


@dataclass
class Fill:
    """A single decoded V2 OrderFilled event."""
    order_hash: str
    maker: str
    taker: str
    side: int               # 0 = BUY, 1 = SELL (maker's side)
    token_id: int           # CTF outcome token ID
    maker_amount: int       # raw uint256
    taker_amount: int       # raw uint256
    fee: int
    builder: str            # bytes32, attribution
    metadata: str           # bytes32, hashed metadata
    block_number: int
    tx_hash: str
    log_index: int
    exchange: str           # "ctf" | "negrisk"

    @property
    def is_buy(self) -> bool:
        return self.side == 0

    @property
    def side_label(self) -> str:
        return "BUY" if self.is_buy else "SELL"

    @property
    def usdc_amount(self) -> float:
        """Total USDC moved.

        For BUY: maker provides USDC (makerAmount), receives tokens (takerAmount).
        For SELL: maker provides tokens (makerAmount), receives USDC (takerAmount).
        """
        raw = self.maker_amount if self.is_buy else self.taker_amount
        return raw / 10**USDC_DECIMALS

    @property
    def token_amount(self) -> float:
        """Total outcome tokens moved."""
        raw = self.taker_amount if self.is_buy else self.maker_amount
        return raw / 10**TOKEN_DECIMALS

    @property
    def price(self) -> float:
        """Implied price per token in USDC, between 0.0 and 1.0."""
        if self.token_amount == 0:
            return 0.0
        return self.usdc_amount / self.token_amount


def _addr_to_topic(addr: str) -> str:
    """Convert 20-byte address to 32-byte topic (left-padded with zeros)."""
    return "0x" + "0" * 24 + addr.lower().removeprefix("0x")


def _decode_uint(hex_data: str, offset: int) -> int:
    """Read a uint256 starting at byte offset from hex data string."""
    start = 2 + offset * 2  # skip '0x', then 2 hex chars per byte
    return int(hex_data[start : start + 64], 16)


def _decode_bytes32(hex_data: str, offset: int) -> str:
    """Read 32 raw bytes at offset, return as 0x-prefixed hex."""
    start = 2 + offset * 2
    return "0x" + hex_data[start : start + 64]


class PolygonClient:
    """Async Polygon RPC client with RPC failover."""

    def __init__(self, rpc_urls: list[str] = RPC_URLS):
        self.rpc_urls = rpc_urls
        self._client = httpx.AsyncClient(timeout=15.0)

    async def close(self):
        await self._client.aclose()

    async def _rpc(self, method: str, params: list) -> dict:
        """Call JSON-RPC with failover across configured URLs."""
        last_err = None
        for url in self.rpc_urls:
            try:
                resp = await self._client.post(
                    url,
                    json={"jsonrpc": "2.0", "method": method, "params": params, "id": 1},
                )
                resp.raise_for_status()
                payload = resp.json()
                if "error" in payload:
                    last_err = payload["error"]
                    continue
                return payload["result"]
            except httpx.HTTPError as e:
                last_err = str(e)
                continue
        raise RuntimeError(f"All RPC URLs failed: {last_err}")

    async def latest_block(self) -> int:
        result = await self._rpc("eth_blockNumber", [])
        return int(result, 16)

    async def get_fills_for_wallet(
        self,
        wallet: str,
        lookback_blocks: int = 10000,
    ) -> list[Fill]:
        """Get recent OrderFilled events where wallet is maker OR taker.

        Lookback of 10000 blocks ≈ 6 hours on Polygon (2s block time).
        """
        latest = await self.latest_block()
        from_block = max(0, latest - lookback_blocks)
        wallet_topic = _addr_to_topic(wallet)

        queries = []
        for exchange_addr, exchange_name in [
            (CTF_EXCHANGE, "ctf"),
            (NEGRISK_EXCHANGE, "negrisk"),
        ]:
            queries.append(self._get_logs(
                exchange_addr, from_block, latest,
                topics=[ORDERFILLED_TOPIC, None, wallet_topic],
                exchange=exchange_name,
            ))
            queries.append(self._get_logs(
                exchange_addr, from_block, latest,
                topics=[ORDERFILLED_TOPIC, None, None, wallet_topic],
                exchange=exchange_name,
            ))

        results = await asyncio.gather(*queries, return_exceptions=True)
        fills: list[Fill] = []
        for r in results:
            if isinstance(r, Exception):
                continue
            fills.extend(r)

        # Dedupe by tx_hash + log_index
        seen = set()
        unique = []
        for f in fills:
            key = (f.tx_hash, f.log_index)
            if key not in seen:
                seen.add(key)
                unique.append(f)

        unique.sort(key=lambda f: (f.block_number, f.log_index), reverse=True)
        return unique

    async def _get_logs(
        self,
        address: str,
        from_block: int,
        to_block: int,
        topics: list[Optional[str]],
        exchange: str,
    ) -> list[Fill]:
        params = [{
            "address": address,
            "fromBlock": hex(from_block),
            "toBlock": hex(to_block),
            "topics": topics,
        }]
        logs = await self._rpc("eth_getLogs", params)
        return [self._decode_log(log, exchange) for log in logs]

    def _decode_log(self, log: dict, exchange: str) -> Fill:
        """Parse a raw V2 OrderFilled log."""
        topics = log["topics"]
        data = log["data"]

        # Indexed: orderHash, maker, taker
        order_hash = topics[1]
        maker      = "0x" + topics[2][-40:]
        taker      = "0x" + topics[3][-40:]

        # Non-indexed (in `data`): side, tokenId, makerAmount, takerAmount, fee, builder, metadata
        # uint8 still occupies a full 32-byte slot — only the last byte matters
        side          = _decode_uint(data, 0) & 0xFF
        token_id      = _decode_uint(data, 32)
        maker_amount  = _decode_uint(data, 64)
        taker_amount  = _decode_uint(data, 96)
        fee           = _decode_uint(data, 128)
        builder       = _decode_bytes32(data, 160)
        metadata      = _decode_bytes32(data, 192)

        return Fill(
            order_hash=order_hash,
            maker=maker,
            taker=taker,
            side=side,
            token_id=token_id,
            maker_amount=maker_amount,
            taker_amount=taker_amount,
            fee=fee,
            builder=builder,
            metadata=metadata,
            block_number=int(log["blockNumber"], 16),
            tx_hash=log["transactionHash"],
            log_index=int(log["logIndex"], 16),
            exchange=exchange,
        )
