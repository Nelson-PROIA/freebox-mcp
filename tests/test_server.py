"""The FastMCP server's tools are the raw output of the generator — no hand-adds."""

from __future__ import annotations

import respx

from freebox_mcp.server import create_server
from freebox_mcp.spec import load_spec

DISCOVERY = {
    "box_model_name": "Freebox Server Test",
    "api_base_url": "/api/",
    "api_version": "16.0",
    "https_available": True,
    "api_domain": "test.fbxos.fr",
    "https_port": 55688,
    "uid": "test-uid",
}


def _spec_operation_ids() -> set[str]:
    spec = load_spec()
    return {
        op["operationId"]
        for item in spec["paths"].values()
        for m, op in item.items()
        if m in ("get", "post", "put", "delete")
    }


@respx.mock
async def test_tools_are_raw_generated_output(monkeypatch):
    monkeypatch.setenv("FREEBOX_TRANSPORT", "http")
    respx.get("http://mafreebox.freebox.fr/api_version").respond(json=DISCOVERY)

    mcp = create_server()
    tools = {t.name for t in await mcp.list_tools()}

    # CONTRACT: every tool is an operationId from the generated spec — nothing
    # hand-added, edited, or post-processed.
    assert tools <= _spec_operation_ids(), f"non-generated tools: {tools - _spec_operation_ids()}"
    # representative generated tools present; auth handshake excluded (transport-handled)
    assert {"get_system", "get_connection", "get_wifi_config"} <= tools
    assert not any(t.startswith(("get_login", "post_login")) for t in tools)
    assert len(tools) > 220


@respx.mock
async def test_section_include_filter(monkeypatch):
    monkeypatch.setenv("FREEBOX_TRANSPORT", "http")
    monkeypatch.setenv("FREEBOX_SECTIONS", "wifi,system")
    respx.get("http://mafreebox.freebox.fr/api_version").respond(json=DISCOVERY)

    mcp = create_server()
    tools = {t.name for t in await mcp.list_tools()}

    assert tools <= _spec_operation_ids()
    assert "get_system" in tools and "get_wifi_config" in tools
    assert "get_connection" not in tools and "get_call_log" not in tools
