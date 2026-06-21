"""Transport behaviour: envelope unwrap, error surfacing, auth retry, path prefix."""

from __future__ import annotations

import httpx

from freebox_mcp.client import FreeboxTransport, _make_request_hook


class _Session:
    def __init__(self, registered=True, token="sess-tok"):
        self._registered = registered
        self._token = token
        self.refreshed = 0

    @property
    def registered(self):
        return self._registered

    async def get_token(self):
        return self._token

    async def refresh(self):
        self.refreshed += 1
        self._token = "refreshed-tok"
        return self._token


def _req(url="http://box/api/v16/system/"):
    return httpx.Request("GET", url)


async def test_unwrap_success():
    inner = httpx.MockTransport(
        lambda r: httpx.Response(
            200, json={"success": True, "result": {"firmware_version": "4.12"}}
        )
    )
    t = FreeboxTransport(inner, _Session())
    resp = await t.handle_async_request(_req())
    assert resp.status_code == 200
    assert resp.json() == {"firmware_version": "4.12"}


async def test_error_surfaced():
    inner = httpx.MockTransport(
        lambda r: httpx.Response(
            200, json={"success": False, "error_code": "noent", "msg": "no such entry"}
        )
    )
    t = FreeboxTransport(inner, _Session(registered=False))
    resp = await t.handle_async_request(_req())
    assert resp.status_code == 409
    body = resp.json()
    assert body["freebox_error"] and body["error_code"] == "noent"


async def test_auth_required_triggers_one_retry():
    calls = {"n": 0}

    def handler(r: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(200, json={"success": False, "error_code": "auth_required"})
        return httpx.Response(200, json={"success": True, "result": {"ok": 1}})

    session = _Session(registered=True)
    t = FreeboxTransport(httpx.MockTransport(handler), session)
    resp = await t.handle_async_request(_req())
    assert resp.json() == {"ok": 1}
    assert session.refreshed == 1
    assert calls["n"] == 2


async def test_non_json_passthrough():
    inner = httpx.MockTransport(
        lambda r: httpx.Response(
            200, content=b"BINARYDATA", headers={"content-type": "application/octet-stream"}
        )
    )
    t = FreeboxTransport(inner, _Session())
    resp = await t.handle_async_request(_req())
    assert resp.content == b"BINARYDATA"


async def test_request_hook_prefixes_path_and_injects_token():
    hook = _make_request_hook(_Session(), "/api/v16")
    req = httpx.Request("GET", "http://box/wifi/config/")
    await hook(req)
    assert req.url.path == "/api/v16/wifi/config/"
    assert req.headers["X-Fbx-App-Auth"] == "sess-tok"


async def test_request_hook_skips_login_auth_header():
    hook = _make_request_hook(_Session(), "/api/v16")
    req = httpx.Request("GET", "http://box/login/")
    await hook(req)
    assert req.url.path == "/api/v16/login/"
    assert "X-Fbx-App-Auth" not in req.headers
