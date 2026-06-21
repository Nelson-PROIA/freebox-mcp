#!/usr/bin/env bash
# Regenerate the Freebox OpenAPI spec from the live docs and, if it changed,
# test + bump + tag + push — which triggers the GitHub release pipeline
# (PyPI + GHCR + GitHub Release).
#
# Run this on a France-reachable, always-on machine (e.g. a systemd timer on your
# Raspberry Pi): dev.freebox.fr blocks GitHub-hosted runner IPs, so the *scrape*
# can't run on GitHub. The release pipeline it triggers DOES run on GitHub.
#
# Optional alerting (set in the systemd unit / env, not committed):
#   FREEBOX_REGEN_ALERT_URL      POST'd a message if a run FAILS (e.g. an ntfy.sh topic)
#   FREEBOX_REGEN_HEARTBEAT_URL  GET on every successful run (e.g. a healthchecks.io ping)
set -euo pipefail
# cron/systemd run with a minimal PATH; uv installs to ~/.local/bin by default.
export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
cd "$(dirname "$0")/.."

_alert() { [ -n "${FREEBOX_REGEN_ALERT_URL:-}" ] && curl -fsS -m 15 -d "$1" "$FREEBOX_REGEN_ALERT_URL" >/dev/null 2>&1 || true; }
_beat() { [ -n "${FREEBOX_REGEN_HEARTBEAT_URL:-}" ] && curl -fsS -m 15 "$FREEBOX_REGEN_HEARTBEAT_URL" >/dev/null 2>&1 || true; }
# Alert on any unexpected failure (scrape break, test failure, push error, …).
trap 'rc=$?; [ $rc -ne 0 ] && _alert "freebox-mcp regen FAILED (exit $rc) on $(hostname) — check journalctl -u freebox-regen"' EXIT

git pull --ff-only
uv sync --group dev
uv run python -m tools.build # online scrape + deterministic rebuild

if git diff --quiet -- spec/freebox-openapi.json; then
  echo "$(date -u +%FT%TZ) no API change."
  git checkout -- tools/cache spec 2>/dev/null || true
  _beat
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
_alert "freebox-mcp: released v${NEW} (Freebox API changed)"
_beat
