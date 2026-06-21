"""Auth primitives: HMAC-SHA1 session password + secure token storage."""

from __future__ import annotations

import json
import stat

from freebox_mcp.auth import BoxCredentials, TokenStore, compute_password


def test_hmac_sha1_known_vector():
    # HMAC-SHA1(key="appToken123", msg="challengeABC")
    assert (
        compute_password("appToken123", "challengeABC")
        == "866f9fbd227cfeee97e4725699bf346ba3585d82"
    )
    assert len(compute_password("k", "c")) == 40  # sha1 hex, not sha256


def test_token_store_roundtrip_and_permissions(tmp_path):
    path = tmp_path / "credentials.json"
    store = TokenStore(path)
    assert store.get("uid-1") is None
    store.set("uid-1", BoxCredentials(app_id="freebox-mcp", app_token="deadbeef", track_id=7))
    got = store.get("uid-1")
    assert got.app_token == "deadbeef"
    assert got.app_id == "freebox-mcp"
    # file must be owner-read/write only (0600)
    mode = stat.S_IMODE(path.stat().st_mode)
    assert mode == 0o600, oct(mode)
    # second box does not clobber the first
    store.set("uid-2", BoxCredentials(app_id="freebox-mcp", app_token="cafe"))
    data = json.loads(path.read_text())
    assert set(data["boxes"]) == {"uid-1", "uid-2"}
