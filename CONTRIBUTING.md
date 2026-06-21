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

Everything is deterministic — there is no AI and no per-endpoint hand data.

- Parser/structure fixes go in `tools/parse.py`.
- Facts the docs don't encode machine-readably (the section→permission map; response-binding
  heuristics) live as small deterministic config/logic in `tools/build_openapi.py` / `tools/parse.py`.
  Endpoints the docs genuinely don't specify keep an untyped result — that's honest, not a TODO.

## Releases

Releases are automatic (weekly regenerate → bump → tag → publish). To cut one manually, push a
`vX.Y.Z` tag; the `release` workflow publishes to PyPI (OIDC), GHCR (signed), and GitHub Releases.
