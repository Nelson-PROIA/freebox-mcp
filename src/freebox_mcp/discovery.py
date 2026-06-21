"""Freebox discovery: find the box and choose a base URL.

The box advertises itself at ``http://mafreebox.freebox.fr/api_version`` (and via
mDNS). From that we learn the API major version and the remote-access domain.
We then pick the best transport: verified HTTPS when reachable, else LAN HTTP.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx

from .config import Settings

log = logging.getLogger("freebox_mcp.discovery")


@dataclass(frozen=True)
class Discovery:
    api_domain: str | None
    https_port: int | None
    https_available: bool
    api_base_url: str  # e.g. "/api/"
    api_version: str  # e.g. "16.0"
    box_model_name: str | None
    uid: str | None

    @property
    def api_major(self) -> int:
        try:
            return int(self.api_version.split(".")[0])
        except (ValueError, IndexError):
            return 8

    @property
    def version_prefix(self) -> str:
        return f"v{self.api_major}"

    @property
    def api_path_prefix(self) -> str:
        """e.g. '/api/v16' — prepended to every spec path at request time."""
        base = self.api_base_url.strip("/")
        return f"/{base}/{self.version_prefix}"


def fetch_discovery(settings: Settings, client: httpx.Client | None = None) -> Discovery:
    owns = client is None
    client = client or httpx.Client(timeout=settings.https_probe_timeout)
    try:
        data = client.get(settings.discovery_url).json()
    finally:
        if owns:
            client.close()
    return Discovery(
        api_domain=data.get("api_domain"),
        https_port=data.get("https_port"),
        https_available=bool(data.get("https_available")),
        api_base_url=data.get("api_base_url", "/api/"),
        api_version=data.get("api_version", "8.0"),
        box_model_name=data.get("box_model_name"),
        uid=data.get("uid"),
    )


@dataclass(frozen=True)
class Endpoint:
    base_url: str  # scheme://host[:port] — NO path
    secure: bool
    api_path_prefix: str  # "/api/v16"
    discovery: Discovery


def _https_reachable(base: str, prefix: str, settings: Settings) -> bool:
    from .tls import freebox_ssl_context

    try:
        r = httpx.get(
            f"{base}{prefix}/login/",
            verify=freebox_ssl_context(str(settings.cert_bundle)),
            timeout=settings.https_probe_timeout,
        )
        return r.status_code < 500
    except Exception as exc:  # noqa: BLE001
        log.debug("HTTPS probe failed for %s: %r", base, exc)
        return False


def choose_endpoint(settings: Settings, discovery: Discovery | None = None) -> Endpoint:
    """Select the base URL + transport, honoring FREEBOX_API_BASE_URL / FREEBOX_TRANSPORT."""
    discovery = discovery or fetch_discovery(settings)
    prefix = discovery.api_path_prefix

    if settings.base_url_override:
        base = settings.base_url_override.rstrip("/")
        return Endpoint(base, base.startswith("https"), prefix, discovery)

    https_base = (
        f"https://{discovery.api_domain}:{discovery.https_port}"
        if discovery.api_domain and discovery.https_port
        else None
    )
    http_base = "http://mafreebox.freebox.fr"

    if settings.transport == "http":
        return Endpoint(http_base, False, prefix, discovery)
    if settings.transport == "https":
        if not https_base:
            raise RuntimeError("HTTPS transport forced but box advertises no api_domain/https_port")
        return Endpoint(https_base, True, prefix, discovery)

    # auto: prefer verified HTTPS, fall back to LAN HTTP
    if https_base and discovery.https_available and _https_reachable(https_base, prefix, settings):
        return Endpoint(https_base, True, prefix, discovery)
    log.warning(
        "Using LAN HTTP transport (%s): the session token transits the local network in "
        "cleartext. Enable Freebox remote HTTPS access or set FREEBOX_API_BASE_URL for TLS.",
        http_base,
    )
    return Endpoint(http_base, False, prefix, discovery)
