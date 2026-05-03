from polyagent.polygon import Fill

WALLET = "0x" + "ab" * 20


def _fake_fill() -> Fill:
    return Fill(
        order_hash="0x" + "11" * 32,
        maker=WALLET,
        taker="0x" + "ee" * 20,
        side=0,                          # BUY
        token_id=12345678901234567890,
        maker_amount=10_000_000,         # 10.0 USDC
        taker_amount=20_000_000,         # 20.0 outcome tokens
        fee=0,
        builder="0x" + "00" * 32,
        metadata="0x" + "00" * 32,
        block_number=70_000_000,
        tx_hash="0x" + "ab" * 32,
        log_index=0,
        exchange="ctf",
    )


async def test_signals_requires_subscription(client, auth_headers):
    resp = await client.get(f"/signals/recent?wallet={WALLET}", headers=auth_headers)
    assert resp.status_code == 403


async def test_signals_rejects_invalid_wallet(client, auth_headers):
    resp = await client.get("/signals/recent?wallet=not-an-address", headers=auth_headers)
    assert resp.status_code == 422


async def test_signals_returns_enriched_fills(client, auth_headers, app):
    from polyagent import main as main_module

    main_module.polygon.get_fills_for_wallet.return_value = [_fake_fill()]
    main_module.polymarket.get_market_by_token.return_value = {
        "question": "Will X happen?",
        "condition_id": "0xcond",
        "outcome": "Yes",
        "current_price": 0.42,
        "volume": 1234.56,
        "end_date": "2026-12-31T00:00:00Z",
        "slug": "will-x-happen",
    }

    await client.post("/subscribe", json={"target_wallet": WALLET}, headers=auth_headers)
    resp = await client.get(f"/signals/recent?wallet={WALLET}", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["fill_count"] == 1
    sig = body["signals"][0]
    assert sig["target_wallet"] == WALLET
    assert sig["side"] == "BUY"
    assert sig["role"] == "maker"
    assert sig["exchange"] == "ctf"
    assert sig["usdc_amount"] == 10.0
    assert sig["token_amount"] == 20.0
    assert sig["fill_price"] == 0.5
    assert sig["market_question"] == "Will X happen?"
    assert sig["outcome"] == "Yes"


async def test_signals_handles_missing_market_metadata(client, auth_headers, app):
    from polyagent import main as main_module

    main_module.polygon.get_fills_for_wallet.return_value = [_fake_fill()]
    main_module.polymarket.get_market_by_token.return_value = None

    await client.post("/subscribe", json={"target_wallet": WALLET}, headers=auth_headers)
    resp = await client.get(f"/signals/recent?wallet={WALLET}", headers=auth_headers)
    assert resp.status_code == 200
    sig = resp.json()["signals"][0]
    assert sig["market_question"] is None
    assert sig["outcome"] is None
