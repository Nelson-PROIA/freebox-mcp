"""Locate and load the bundled OpenAPI document."""

from __future__ import annotations

import json
import os
from importlib import resources
from pathlib import Path


def spec_path() -> Path:
    override = os.environ.get("FREEBOX_OPENAPI_PATH")
    if override:
        return Path(override)
    # Installed: packaged at freebox_mcp/spec/freebox-openapi.json (hatch force-include).
    try:
        packaged = resources.files("freebox_mcp") / "spec" / "freebox-openapi.json"
        if packaged.is_file():
            return Path(str(packaged))
    except (ModuleNotFoundError, FileNotFoundError):
        pass
    # Dev checkout: repo-root spec/.
    repo = Path(__file__).resolve().parent.parent.parent / "spec" / "freebox-openapi.json"
    return repo


def load_spec() -> dict:
    return json.loads(spec_path().read_text())
