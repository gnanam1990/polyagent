WALLET = "0x" + "ab" * 20
WALLET_2 = "0x" + "cd" * 20


async def test_subscribe_creates_subscription(client, auth_headers):
    resp = await client.post(
        "/subscribe", json={"target_wallet": WALLET}, headers=auth_headers
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["subscription"]["target_wallet"] == WALLET
    assert body["subscription"]["active"] is True
    assert body["remaining_budget_usdc"] == 100.0


async def test_subscribe_rejects_invalid_address(client, auth_headers):
    resp = await client.post(
        "/subscribe", json={"target_wallet": "not-an-address"}, headers=auth_headers
    )
    assert resp.status_code == 422


async def test_subscribe_normalises_to_lowercase(client, auth_headers):
    upper = "0x" + "AB" * 20
    resp = await client.post(
        "/subscribe", json={"target_wallet": upper}, headers=auth_headers
    )
    assert resp.status_code == 200
    assert resp.json()["subscription"]["target_wallet"] == upper.lower()


async def test_duplicate_subscribe_returns_409(client, auth_headers):
    await client.post("/subscribe", json={"target_wallet": WALLET}, headers=auth_headers)
    resp = await client.post(
        "/subscribe", json={"target_wallet": WALLET}, headers=auth_headers
    )
    assert resp.status_code == 409


async def test_list_subscriptions_returns_only_active_for_session(client, auth_headers):
    await client.post("/subscribe", json={"target_wallet": WALLET}, headers=auth_headers)
    await client.post("/subscribe", json={"target_wallet": WALLET_2}, headers=auth_headers)
    resp = await client.get("/subscriptions", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 2
    wallets = {s["target_wallet"] for s in body["subscriptions"]}
    assert wallets == {WALLET, WALLET_2}


async def test_unsubscribe_marks_inactive(client, auth_headers):
    create = await client.post(
        "/subscribe", json={"target_wallet": WALLET}, headers=auth_headers
    )
    sub_id = create.json()["subscription"]["id"]

    delete = await client.delete(f"/subscriptions/{sub_id}", headers=auth_headers)
    assert delete.status_code == 200

    listing = await client.get("/subscriptions", headers=auth_headers)
    assert listing.json()["count"] == 0


async def test_unsubscribe_unknown_returns_404(client, auth_headers):
    resp = await client.delete("/subscriptions/9999", headers=auth_headers)
    assert resp.status_code == 404
