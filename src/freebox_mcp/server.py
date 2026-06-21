"""Brick 3 — the generated client.

Three bricks, one contract:
    scraper    tools/scrape.py          official docs        -> tools/cache/
    generator  tools/build*.py          cache                -> spec/freebox-openapi.json
    client     FastMCP.from_openapi()    spec                 -> MCP tools

The MCP tool surface is the **raw output** of ``FastMCP.from_openapi`` over the
generated spec. No tool is hand-added, edited, or post-processed — `create_server`
configures the generator (route maps, the authenticated client) and returns its
output verbatim. The only hand-written code is the transport the generated client
runs *on* (auth / discovery / TLS / envelope) — things no API spec can express —
and that is generic, not edited per endpoint. App registration / session login
live in the CLI (`freebox-mcp authorize`), not as injected tools.
"""

from __future__ import annotations

import logging

from fastmcp import FastMCP
from fastmcp.server.providers.openapi import MCPType, RouteMap

from .auth import TokenStore
from .client import build_client, build_session_manager
from .config import Settings, load_settings
from .discovery import Discovery, Endpoint, choose_endpoint
from .spec import load_spec

log = logging.getLogger("freebox_mcp.server")

_DEFAULT_DISCOVERY = Discovery(
    api_domain=None,
    https_port=None,
    https_available=False,
    api_base_url="/api/",
    api_version="8.0",
    box_model_name=None,
    uid=None,
)


def _resolve_endpoint(settings: Settings) -> Endpoint:
    try:
        return choose_endpoint(settings)
    except Exception as exc:  # noqa: BLE001
        log.warning("Freebox discovery failed (%r); defaulting to LAN HTTP.", exc)
        return Endpoint(
            base_url="http://mafreebox.freebox.fr",
            secure=False,
            api_path_prefix=_DEFAULT_DISCOVERY.api_path_prefix,
            discovery=_DEFAULT_DISCOVERY,
        )


def _route_maps(settings: Settings) -> list[RouteMap]:
    """Generation parameters (not post-edits): which routes become tools.

    /login/ is the auth handshake (handled by the transport); /ws/ endpoints are
    WebSocket channels that can't work as plain HTTP tools — exclude both.
    FREEBOX_SECTIONS optionally narrows the surface by section tag.
    """
    maps = [RouteMap(pattern=r"^/(login|ws)/", mcp_type=MCPType.EXCLUDE)]
    if settings.include_sections:
        for section in settings.include_sections:
            maps.append(RouteMap(tags={section}, mcp_type=MCPType.TOOL))
        maps.append(RouteMap(mcp_type=MCPType.EXCLUDE))
    else:
        for section in settings.exclude_sections:
            maps.append(RouteMap(tags={section}, mcp_type=MCPType.EXCLUDE))
        maps.append(RouteMap(mcp_type=MCPType.TOOL))
    return maps


def create_server(settings: Settings | None = None) -> FastMCP:
    settings = settings or load_settings()
    spec = load_spec()
    store = TokenStore(settings.credentials_path)
    endpoint = _resolve_endpoint(settings)
    session = build_session_manager(settings, endpoint, store)
    client = build_client(settings, endpoint, session)

    # The tool surface is the verbatim output of the generator — nothing added,
    # nothing edited afterwards.
    return FastMCP.from_openapi(
        spec,
        client=client,
        name="Freebox OS",
        route_maps=_route_maps(settings),
        validate_output=False,
    )
