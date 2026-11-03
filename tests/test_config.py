"""Section scoping and TLS defaults."""

from __future__ import annotations

import ssl

import pytest

from freebox_mcp.config import CERT_BUNDLE, Settings
from freebox_mcp.tls import freebox_ssl_context


def test_sections_are_parsed_as_a_comma_list(monkeypatch):
    monkeypatch.delenv("FREEBOX_EXCLUDE_SECTIONS", raising=False)
    monkeypatch.setenv("FREEBOX_SECTIONS", "wifi, lan")

    assert Settings().include_sections == ("wifi", "lan")


def test_no_scope_variables_expose_every_section(monkeypatch):
    monkeypatch.delenv("FREEBOX_SECTIONS", raising=False)
    monkeypatch.delenv("FREEBOX_EXCLUDE_SECTIONS", raising=False)

    settings = Settings()
    assert settings.include_sections == ()
    assert settings.exclude_sections == ()


def test_include_and_exclude_together_are_rejected(monkeypatch):
    monkeypatch.setenv("FREEBOX_SECTIONS", "wifi")
    monkeypatch.setenv("FREEBOX_EXCLUDE_SECTIONS", "pvr")

    with pytest.raises(ValueError, match="not both"):
        Settings()


def test_tls_context_trusts_the_bundled_roots_without_strict_mode():
    context = freebox_ssl_context(str(CERT_BUNDLE))

    assert context.verify_flags & ssl.VERIFY_X509_STRICT == 0
    assert context.cert_store_stats()["x509_ca"] >= 2
