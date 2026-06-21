"""Shared fixtures. Tests run against the committed pipeline cache + spec, so
they are hermetic (no network) except the opt-in live suite."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="session")
def repo() -> Path:
    return REPO


@pytest.fixture(scope="session")
def spec() -> dict:
    return json.loads((REPO / "spec" / "freebox-openapi.json").read_text())


@pytest.fixture(scope="session")
def ir() -> dict:
    return json.loads((REPO / "tools" / "cache" / "ir.json").read_text())
