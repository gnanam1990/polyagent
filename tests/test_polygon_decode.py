"""Unit tests for the OrderFilled decoder — protects topic hash + slot offsets."""

from polyagent.polygon import ORDERFILLED_TOPIC, PolygonClient, _addr_to_topic


def test_topic_hash_matches_v2_signature():
    # The hash is verified against on-chain V2 contracts (see CONTEXT.md).
    assert ORDERFILLED_TOPIC == (
        "0xd543adfd945773f1a62f74f0ee55a5e3b9b1a28262980ba90b1a89f2ea84d8ee"
    )


def test_addr_to_topic_left_pads_to_32_bytes():
    addr = "0xAbCdEf0123456789012345678901234567890aBc"
    topic = _addr_to_topic(addr)
    assert topic.startswith("0x" + "0" * 24)
    assert topic.lower().endswith(addr.lower().removeprefix("0x"))
    assert len(topic) == 2 + 64


def _slot(value: int) -> str:
    return f"{value:064x}"


def test_decode_log_parses_v2_orderfilled():
    maker = "0x" + "aa" * 20
    taker = "0x" + "bb" * 20
    side = 0                     # BUY
    token_id = 12345
    maker_amount = 10_000_000
    taker_amount = 20_000_000
    fee = 0

    data = "0x" + "".join(
        [
            _slot(side),
            _slot(token_id),
            _slot(maker_amount),
            _slot(taker_amount),
            _slot(fee),
            "11" * 32,            # builder
            "22" * 32,            # metadata
        ]
    )
    log = {
        "topics": [
            ORDERFILLED_TOPIC,
            "0x" + "33" * 32,         # orderHash
            "0x" + "00" * 12 + maker.removeprefix("0x"),
            "0x" + "00" * 12 + taker.removeprefix("0x"),
        ],
        "data": data,
        "blockNumber": "0x10",
        "transactionHash": "0x" + "44" * 32,
        "logIndex": "0x1",
    }

    fill = PolygonClient()._decode_log(log, "ctf")

    assert fill.maker == maker
    assert fill.taker == taker
    assert fill.side == 0
    assert fill.is_buy
    assert fill.token_id == token_id
    assert fill.maker_amount == maker_amount
    assert fill.taker_amount == taker_amount
    assert fill.usdc_amount == 10.0
    assert fill.token_amount == 20.0
    assert fill.price == 0.5
    assert fill.exchange == "ctf"
