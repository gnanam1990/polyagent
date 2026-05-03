from tests.conftest import _past_iso, make_session


async def test_missing_session_header_returns_401(client):
    resp = await client.get("/subscriptions")
    assert resp.status_code == 401


async def test_unknown_session_returns_403(client, app, auth_headers):
    from polyagent import main as main_module

    main_module.passport.get_session.return_value = None
    resp = await client.get("/subscriptions", headers=auth_headers)
    assert resp.status_code == 403


async def test_inactive_session_returns_403(client, app, auth_headers):
    from polyagent import main as main_module

    main_module.passport.get_session.return_value = make_session(status="revoked")
    resp = await client.get("/subscriptions", headers=auth_headers)
    assert resp.status_code == 403


async def test_expired_session_returns_403(client, app, auth_headers):
    from polyagent import main as main_module

    main_module.passport.get_session.return_value = make_session(expires_at=_past_iso())
    resp = await client.get("/subscriptions", headers=auth_headers)
    assert resp.status_code == 403


async def test_exhausted_budget_returns_402(client, app, auth_headers):
    from polyagent import main as main_module

    main_module.passport.get_session.return_value = make_session(spent=100.0)
    resp = await client.get("/subscriptions", headers=auth_headers)
    assert resp.status_code == 402
