"""Shared paths and constants for the regeneration pipeline."""

from __future__ import annotations

import json
from pathlib import Path

# Source of truth: the official Freebox OS API documentation (Sphinx site).
DOC_BASE_URL = "https://dev.freebox.fr/sdk/os/"

REPO_ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = REPO_ROOT / "tools" / "cache"
HTML_DIR = CACHE_DIR / "html"
INVENTORY_PATH = CACHE_DIR / "objects.inv"
MANIFEST_PATH = CACHE_DIR / "manifest.json"
IR_PATH = CACHE_DIR / "ir.json"

SPEC_DIR = REPO_ROOT / "spec"
OPENAPI_PATH = SPEC_DIR / "freebox-openapi.json"
SPEC_META_PATH = SPEC_DIR / "freebox-spec.meta.json"


def write_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False, sort_keys=False) + "\n")


def read_json(path: Path) -> object:
    return json.loads(path.read_text())
