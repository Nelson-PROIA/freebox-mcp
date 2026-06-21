"""Run the full deterministic regeneration pipeline.

    python -m tools.build            # scrape docs, parse, render, emit OpenAPI
    python -m tools.build --offline  # skip scraping, use the existing cache

This is the single command CI runs on a schedule. It is pure Python: no AI,
no manual steps. The only non-deterministic input (permissions / a few response
bindings) lives in the committed spec/overrides.json, which is merged in.
"""

from __future__ import annotations

import sys

from . import build_openapi, inventory, parse, render, scrape


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    offline = "--offline" in argv

    if not offline:
        print("== scrape ==")
        scrape.main()
    else:
        print("== scrape skipped (--offline) ==")

    print("\n== inventory ==")
    inventory.main()
    print("\n== parse ==")
    parse.main()
    print("\n== render ==")
    render.main()
    print("\n== build_openapi ==")
    build_openapi.main()
    print("\nDone.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
