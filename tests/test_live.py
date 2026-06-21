"""Opt-in live tests against a real Freebox.

Run with:  FREEBOX_TEST=1 uv run pytest -m live
Requires the app to be authorized already (`freebox-mcp authorize`).
"""

from __future__ import annotations

import os

import pytest

from freebox_mcp.client import build_client, build_session_manager
from freebox_mcp.auth import TokenStore
from freebox_mcp.config import load_settings
from freebox_mcp.discovery import choose_endpoint

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(not os.environ.get("FREEBOX_TEST"), reason="set FREEBOX_TEST=1 to run"),
]


async def test_live_session_and_system():
    settings = load_settings()
    endpoint = choose_endpoint(settings)
    store = TokenStore(settings.credentials_path)
    session = build_session_manager(settings, endpoint, store)
    assert session.registered, "run `freebox-mcp authorize` first"

    client = build_client(settings, endpoint, session)
    try:
        await session.refresh()
        resp = await client.get("/system/")
    finally:
        await client.aclose()

    data = resp.json()
    assert "firmware_version" in data
    assert isinstance(session.permissions, dict) and session.permissions
