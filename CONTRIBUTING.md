# Contributing

Thanks for your interest!

## Layout

- `tools/` — the **deterministic** regeneration pipeline (scrape → inventory → parse → render →
  build_openapi). Pure Python, no AI. This is what CI runs.
- `spec/` — the generated `freebox-openapi.json` and its `*.meta.json` (deterministic output; no AI).
- `src/freebox_mcp/` — the MCP server (discovery, auth, client, FastMCP wiring).
- `tests/` — unit + integration (respx-mocked) + an opt-in `live` suite.

## Dev loop

```bash
uv sync --group dev
uv run python -m tools.build --offline   # rebuild spec from the committed cache
uv run pytest -q
uv run ruff check . && uv run ruff format .
```

The CI **spec-drift** check fails if `tools/build --offline` would change the committed spec, so
always rebuild and commit `spec/` + `tools/cache/` together.

## Changing the spec

The scrape + generate are a pure, generic, deterministic transform — no AI, no per-endpoint or
per-section data, no patching the output.

- If the output is wrong because we extract the docs badly, fix the **scrape** (`tools/parse.py` /
  `tools/scrape.py`) so it faithfully reflects what Free documents.
- If we scraped faithfully and it's still imperfect (a result type Free never documents, a
  malformed field), that's Free's docs — **leave it**. It stays generic/untyped and self-corrects
  if Free fixes the docs. Don't add maps, aliases, or heuristics to paper over it.

## Releases

The scrape runs on a France-reachable host (a Pi cron, `scripts/regenerate.sh`) because
`dev.freebox.fr` blocks GitHub-hosted runners; on a spec change it tags + pushes, and the `release`
workflow (tag-triggered) publishes to PyPI (OIDC), GHCR (signed), and GitHub Releases. To cut one
manually, push a `vX.Y.Z` tag.
