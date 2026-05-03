async def test_health_open(client):
    resp = await client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["service"] == "polyagent"
    assert body["version"]


async def test_health_emits_request_id(client):
    resp = await client.get("/health")
    assert "x-request-id" in {k.lower() for k in resp.headers}


async def test_health_passes_through_supplied_request_id(client):
    resp = await client.get("/health", headers={"X-Request-ID": "abc123"})
    assert resp.headers["x-request-id"] == "abc123"
