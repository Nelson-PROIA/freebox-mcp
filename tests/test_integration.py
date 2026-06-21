"""End-to-end flow against a mocked Freebox (respx): discover -> session -> call.

Exercises the request hook (version prefix + token), the HMAC session open, and
the envelope-unwrapping transport together, with no real network.
"""

from __future__ import annotations

import respx

from freebox_mcp.auth import BoxCredentials, TokenStore, compute_password
from freebox_mcp.client import build_client, build_session_manager
from freebox_mcp.config import Settings
from freebox_mcp.discovery import choose_endpoint, fetch_discovery

DISCOVERY = {
    "box_model_name": "Freebox Server Test",
    "api_base_url": "/api/",
    "api_version": "8.0",
    "https_available": False,
    "api_domain": "test.fbxos.fr",
    "https_port": 55688,
    "uid": "box-uid",
}


@respx.mock
async def test_full_call_flow(tmp_path, monkeypatch):
    monkeypatch.setenv("FREEBOX_TRANSPORT", "http")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    base = "http://mafreebox.freebox.fr"

    respx.get(f"{base}/api_version").respond(json=DISCOVERY)
    respx.get(f"{base}/api/v8/login/").respond(
        json={"success": True, "result": {"challenge": "chA", "logged_in": False}}
    )
    session_route = respx.post(f"{base}/api/v8/login/session/").respond(
        json={
            "success": True,
            "result": {"session_token": "S-TOKEN", "permissions": {"settings": True}},
        }
    )
    system_route = respx.get(f"{base}/api/v8/system/").respond(
        json={"success": True, "result": {"firmware_version": "4.12.1"}}
    )

    settings = Settings()
    store = TokenStore(settings.credentials_path)
    store.set("box-uid", BoxCredentials(app_id="freebox-mcp", app_token="APPTOKEN"))

    endpoint = choose_endpoint(settings, fetch_discovery(settings))
    session = build_session_manager(settings, endpoint, store)
    client = build_client(settings, endpoint, session)
    try:
        resp = await client.get("/system/")
    finally:
        await client.aclose()

    assert resp.json() == {"firmware_version": "4.12.1"}
    assert session.permissions == {"settings": True}
    # the session password must be HMAC-SHA1(app_token, challenge)
    sent = session_route.calls.last.request
    import json as _json

    assert _json.loads(sent.content)["password"] == compute_password("APPTOKEN", "chA")
    # the data call carried the session token and the version-prefixed path
    sys_req = system_route.calls.last.request
    assert sys_req.headers["X-Fbx-App-Auth"] == "S-TOKEN"
    assert sys_req.url.path == "/api/v8/system/"
