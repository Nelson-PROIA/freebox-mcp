"""Discovery parsing and transport selection (no network)."""

from __future__ import annotations

from freebox_mcp.config import Settings
from freebox_mcp.discovery import Discovery, choose_endpoint


def _disc(**kw) -> Discovery:
    base = dict(
        api_domain="abcд.fbxos.fr",
        https_port=55688,
        https_available=True,
        api_base_url="/api/",
        api_version="16.0",
        box_model_name="Freebox Server",
        uid="uid",
    )
    base.update(kw)
    return Discovery(**base)


def test_api_major_and_prefix():
    assert _disc(api_version="16.0").api_major == 16
    assert _disc(api_version="8.1").api_major == 8
    assert _disc(api_version="garbage").api_major == 8  # safe fallback
    assert _disc(api_version="16.0").api_path_prefix == "/api/v16"


def test_choose_endpoint_http_forced():
    settings = Settings(transport="http")
    ep = choose_endpoint(settings, _disc())
    assert ep.base_url == "http://mafreebox.freebox.fr"
    assert ep.secure is False
    assert ep.api_path_prefix == "/api/v16"


def test_choose_endpoint_override():
    settings = Settings(base_url_override="https://box.example:443")
    ep = choose_endpoint(settings, _disc())
    assert ep.base_url == "https://box.example:443"
    assert ep.secure is True


def test_choose_endpoint_https_forced_without_domain_errors():
    settings = Settings(transport="https")
    try:
        choose_endpoint(settings, _disc(api_domain=None, https_port=None))
        raise AssertionError("expected RuntimeError")
    except RuntimeError:
        pass
