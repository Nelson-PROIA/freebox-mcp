"""Bump the package patch version in pyproject.toml and __init__.py.

Used by the weekly regeneration workflow when the generated spec changes.
    python -m tools.bump            # bump patch, print new version
    python -m tools.bump --print    # just print current version
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = ROOT / "pyproject.toml"
INIT = ROOT / "src" / "freebox_mcp" / "__init__.py"


def current() -> str:
    m = re.search(r'(?m)^version\s*=\s*"([^"]+)"', PYPROJECT.read_text())
    if not m:
        raise SystemExit("version not found in pyproject.toml")
    return m.group(1)


def bump_patch(v: str) -> str:
    parts = v.split(".")
    if len(parts) != 3 or not all(p.isdigit() for p in parts):
        raise SystemExit(f"unexpected version {v!r} (need MAJOR.MINOR.PATCH)")
    parts[2] = str(int(parts[2]) + 1)
    return ".".join(parts)


def write(new: str) -> None:
    PYPROJECT.write_text(
        re.sub(
            r'(?m)^(version\s*=\s*")[^"]+(")', rf"\g<1>{new}\g<2>", PYPROJECT.read_text(), count=1
        )
    )
    INIT.write_text(
        re.sub(
            r'(?m)^(__version__\s*=\s*")[^"]+(")', rf"\g<1>{new}\g<2>", INIT.read_text(), count=1
        )
    )


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if "--print" in argv:
        print(current())
        return 0
    new = bump_patch(current())
    write(new)
    print(new)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
