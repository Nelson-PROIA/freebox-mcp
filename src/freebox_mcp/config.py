"""Runtime configuration, loaded from the environment with safe defaults."""

from __future__ import annotations

import os
import socket
from dataclasses import dataclass, field
from pathlib import Path

from . import __version__

CERT_BUNDLE = Path(__file__).resolve().parent / "certs" / "freebox_rootca.pem"


def _default_credentials_path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
    return Path(base) / "freebox-mcp" / "credentials.json"


@dataclass(frozen=True)
class Settings:
    # Identity shown in the Freebox "authorized apps" list.
    app_id: str = field(default_factory=lambda: os.environ.get("FREEBOX_APP_ID", "freebox-mcp"))
    app_name: str = field(default_factory=lambda: os.environ.get("FREEBOX_APP_NAME", "Freebox MCP"))
    app_version: str = field(
        default_factory=lambda: os.environ.get("FREEBOX_APP_VERSION", __version__)
    )
    device_name: str = field(
        default_factory=lambda: os.environ.get("FREEBOX_DEVICE_NAME") or socket.gethostname()
    )

    # Discovery / transport.
    discovery_url: str = field(
        default_factory=lambda: os.environ.get(
            "FREEBOX_DISCOVERY_URL", "http://mafreebox.freebox.fr/api_version"
        )
    )
    # Explicit base override, e.g. "https://6gs1dyx4.fbxos.fr:55688" — skips auto-selection.
    base_url_override: str | None = field(
        default_factory=lambda: os.environ.get("FREEBOX_API_BASE_URL") or None
    )
    # "auto" (prefer verified HTTPS, fall back to LAN HTTP), "https", or "http".
    transport: str = field(default_factory=lambda: os.environ.get("FREEBOX_TRANSPORT", "auto"))
    https_probe_timeout: float = field(
        default_factory=lambda: float(os.environ.get("FREEBOX_HTTPS_PROBE_TIMEOUT", "3"))
    )
    request_timeout: float = field(
        default_factory=lambda: float(os.environ.get("FREEBOX_REQUEST_TIMEOUT", "20"))
    )

    # Optional tool-surface scoping. Tools are tagged with their API section
    # (wifi, lan, downloads, pvr, ...). Set FREEBOX_SECTIONS to expose only those
    # sections, or FREEBOX_EXCLUDE_SECTIONS to hide some. Keeps the 230-tool
    # surface manageable for an LLM when you only care about a few areas.
    include_sections: tuple[str, ...] = field(
        default_factory=lambda: tuple(
            s.strip() for s in os.environ.get("FREEBOX_SECTIONS", "").split(",") if s.strip()
        )
    )
    exclude_sections: tuple[str, ...] = field(
        default_factory=lambda: tuple(
            s.strip()
            for s in os.environ.get("FREEBOX_EXCLUDE_SECTIONS", "").split(",")
            if s.strip()
        )
    )

    credentials_path: Path = field(default_factory=_default_credentials_path)
    cert_bundle: Path = CERT_BUNDLE

    def __post_init__(self) -> None:  # pragma: no cover - trivial
        # frozen dataclass: nothing to mutate, kept for clarity / future validation.
        pass


def load_settings() -> Settings:
    return Settings()
