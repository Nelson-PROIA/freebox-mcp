#!/usr/bin/env bash
# Regenerate the Freebox OpenAPI spec from the live docs and, if it changed,
# test + bump + tag + push — which triggers the GitHub release pipeline
# (PyPI + GHCR + GitHub Release).
#
# Run this on a France-reachable, always-on machine (e.g. cron/launchd on your
# Raspberry Pi): dev.freebox.fr blocks GitHub-hosted runner IPs, so the *scrape*
# can't run on GitHub. The release pipeline it triggers DOES run on GitHub.
#
# Example crontab (Mondays 04:17):
#   17 4 * * 1  /path/to/freebox-mcp/scripts/regenerate.sh >> ~/freebox-mcp-regen.log 2>&1
set -euo pipefail
cd "$(dirname "$0")/.."

git pull --ff-only
uv sync --group dev
uv run python -m tools.build   # online scrape + deterministic rebuild

if git diff --quiet -- spec/freebox-openapi.json; then
  echo "$(date -u +%FT%TZ) no API change."
  git checkout -- tools/cache spec 2>/dev/null || true
  exit 0
fi

echo "$(date -u +%FT%TZ) spec changed — testing and releasing."
uv run pytest -q
NEW="$(uv run python -m tools.bump)"
git add -A
git commit -m "chore: regenerate Freebox API spec → v${NEW}"
git tag "v${NEW}"
git push origin HEAD --follow-tags
echo "$(date -u +%FT%TZ) released v${NEW} (GitHub release pipeline will publish)."
