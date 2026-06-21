"""Download the Freebox OS documentation into tools/cache/.

Zero third-party dependencies (stdlib urllib) so the very first pipeline stage
always runs. The list of section pages is re-derived from the live index
toctree, so a new Freebox doc release that adds/removes sections is picked up
automatically — nothing here is hard-coded to today's API surface.
"""

from __future__ import annotations

import hashlib
import os
import re
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from .common import (
    DOC_BASE_URL,
    HTML_DIR,
    INVENTORY_PATH,
    MANIFEST_PATH,
    write_json,
)

USER_AGENT = (
    "Mozilla/5.0 (compatible; freebox-mcp-spec-generator/0.1; "
    "+https://github.com/Nelson-PROIA/freebox-mcp)"
)
TIMEOUT = float(os.environ.get("FREEBOX_SCRAPE_TIMEOUT", "60"))
ATTEMPTS = int(os.environ.get("FREEBOX_SCRAPE_ATTEMPTS", "4"))

# Index hrefs we never treat as API sections.
_SKIP_LINK = re.compile(r"^(https?:|#|mailto:|_static|_sources|genindex|search|py-modindex)")


def _fetch(url: str) -> bytes:
    """Fetch with retries + exponential backoff (the docs host can be slow/flaky
    from CI runners, which would otherwise break the weekly regeneration)."""
    headers = {"User-Agent": USER_AGENT, "Accept-Language": "fr,en;q=0.8"}
    last_exc: Exception | None = None
    for attempt in range(ATTEMPTS):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:  # noqa: S310 (trusted host)
                return resp.read()
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            if attempt < ATTEMPTS - 1:
                wait = 2 ** (attempt + 1)
                print(f"[scrape]   retry {attempt + 1}/{ATTEMPTS} for {url} in {wait}s ({exc})")
                time.sleep(wait)
    raise last_exc  # type: ignore[misc]


def discover_sections(index_html: str) -> list[str]:
    """Return the ordered, de-duplicated list of section slugs from the index toctree.

    The Freebox index links to each section as a relative dir, e.g. ``href="wifi/"``.
    """
    slugs: list[str] = []
    seen: set[str] = set()
    for href in re.findall(r'href="([^"]+)"', index_html):
        href = href.strip()
        if _SKIP_LINK.match(href):
            continue
        # Section links look like "wifi/" or "download_config/".
        slug = href.rstrip("/")
        if not slug or "/" in slug or "." in slug:
            continue
        if slug not in seen:
            seen.add(slug)
            slugs.append(slug)
    return slugs


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _doc_version(inventory: bytes) -> str:
    """Extract the doc version hash from the objects.inv header (line 3)."""
    for line in inventory.split(b"\n", 4)[:4]:
        if line.startswith(b"# Version:"):
            return line.split(b":", 1)[1].strip().decode("utf-8", "replace")
    return "unknown"


def main() -> int:
    HTML_DIR.mkdir(parents=True, exist_ok=True)
    base = DOC_BASE_URL if DOC_BASE_URL.endswith("/") else DOC_BASE_URL + "/"

    print(f"[scrape] index: {base}")
    index_bytes = _fetch(base)
    index_html = index_bytes.decode("utf-8", "replace")
    (HTML_DIR / "index.html").write_text(index_html)

    inventory = _fetch(urllib.parse.urljoin(base, "objects.inv"))
    INVENTORY_PATH.write_bytes(inventory)
    version = _doc_version(inventory)
    print(f"[scrape] doc version: {version}")

    sections = discover_sections(index_html)
    print(f"[scrape] {len(sections)} sections discovered: {', '.join(sections)}")

    files: dict[str, dict[str, object]] = {
        "index.html": {"url": base, "sha256": _sha256(index_bytes), "bytes": len(index_bytes)},
        "objects.inv": {
            "url": urllib.parse.urljoin(base, "objects.inv"),
            "sha256": _sha256(inventory),
            "bytes": len(inventory),
        },
    }

    for slug in sections:
        url = urllib.parse.urljoin(base, f"{slug}/")
        # Fail hard: a missing section would silently produce a degraded spec,
        # which the regeneration cron could then commit + release.
        data = _fetch(url)
        (HTML_DIR / f"{slug}.html").write_bytes(data)
        files[f"{slug}.html"] = {"url": url, "sha256": _sha256(data), "bytes": len(data)}
        print(f"[scrape]   + {slug}.html ({len(data)} bytes)")

    write_json(
        MANIFEST_PATH,
        {
            "doc_base_url": base,
            "doc_version": version,
            "scraped_at": datetime.now(timezone.utc).isoformat(),
            "section_slugs": sections,
            "files": files,
        },
    )
    print(f"[scrape] manifest -> {MANIFEST_PATH.relative_to(MANIFEST_PATH.parents[2])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
