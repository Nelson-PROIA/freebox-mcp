"""The FastMCP server builds from the spec and exposes the right tools."""

from __future__ import annotations

import respx

from freebox_mcp.server import create_server

DISCOVERY = {
    "box_model_name": "Freebox Server Test",
    "api_base_url": "/api/",
    "api_version": "16.0",
    "https_available": True,
    "api_domain": "test.fbxos.fr",
    "https_port": 55688,
    "uid": "test-uid",
}


@respx.mock
async def test_server_builds_and_exposes_tools(monkeypatch):
    monkeypatch.setenv("FREEBOX_TRANSPORT", "http")
    respx.get("http://mafreebox.freebox.fr/api_version").respond(json=DISCOVERY)

    mcp = create_server()
    tools = {t.name for t in await mcp.list_tools()}

    # lifecycle tools present
    assert {"freebox_status", "freebox_login", "freebox_authorize"} <= tools
    # representative generated tools present
    assert {"get_system", "get_connection", "get_wifi_config"} <= tools
    # login operations are excluded (handled by lifecycle tools)
    assert not any(t.startswith("get_login") or t.startswith("post_login") for t in tools)
    # the full surface is large
    assert len(tools) > 220


@respx.mock
async def test_section_include_filter(monkeypatch):
    monkeypatch.setenv("FREEBOX_TRANSPORT", "http")
    monkeypatch.setenv("FREEBOX_SECTIONS", "wifi,system")
    respx.get("http://mafreebox.freebox.fr/api_version").respond(json=DISCOVERY)

    mcp = create_server()
    tools = {t.name for t in await mcp.list_tools()}

    # only wifi + system generated tools, plus the always-on lifecycle tools
    assert "get_system" in tools and "get_wifi_config" in tools
    assert "get_connection" not in tools and "get_call_log" not in tools
    assert {"freebox_status", "freebox_login"} <= tools
