# Contributing

Thanks for your interest!

## Layout

- `tools/` — the **deterministic** regeneration pipeline (scrape → inventory → parse → render →
  build_openapi). Pure Python, no AI. This is what CI runs.
- `spec/` — the generated `freebox-openapi.json`, its `*.meta.json`, and the committed
  `overrides.json` (one-time AI audit, treated as static data).
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

- Parser/structure fixes go in `tools/parse.py` / `tools/build_openapi.py`.
- Non-derivable facts (a permission, a response binding the docs don't make machine-readable) go in
  `spec/overrides.json` — keep it small and explain each entry.

## Releases

Releases are automatic (weekly regenerate → bump → tag → publish). To cut one manually, push a
`vX.Y.Z` tag; the `release` workflow publishes to PyPI (OIDC), GHCR (signed), and GitHub Releases.
