#!/usr/bin/env bash
# Stage 11: source-grounded read-only model input feature health diagnostics.
set -euo pipefail
cd "$(dirname "$0")/.."
BASE=cec0a32
BRANCH=integration/atlas-feature-health
PATCH=patches/atlas_stage11_feature_health.patch
if ! command -v git >/dev/null || [[ ! -d .git ]]; then
  echo '[BLOCKED] Run inside original Wallex Atlas Git checkout.'; exit 1
fi
HEAD=$(git rev-parse HEAD)
CURRENT=$(git branch --show-current)
if [[ "$HEAD" != "$BASE"* || "$CURRENT" != 'integration/atlas-edge-triage' ]]; then
  echo "[BLOCKED] Expected $BASE on integration/atlas-edge-triage. Actual $CURRENT ${HEAD:0:12}"; exit 1
fi
if ! git diff --quiet || ! git diff --cached --quiet; then
  echo '[BLOCKED] Local tracked modifications present. Nothing applied.'; exit 1
fi
if git show-ref --quiet --verify "refs/heads/$BRANCH"; then
  echo '[BLOCKED] Target branch exists. Nothing applied.'; exit 1
fi
[[ -f "$PATCH" ]] || { echo '[BLOCKED] Stage 11 patch missing.'; exit 1; }
git apply --check "$PATCH"
git switch -c "$BRANCH"
git apply "$PATCH"
echo '[Stage11] Strict read-only SHA-verified genuine candle feature health inspection.'
if ! python -m pytest -q; then
  echo '[BLOCKED] Tests failed. No commit created.'; exit 1
fi
python -m wallex_bot.atlas_cli feature-health --resolution 15 --top 8
git add -- wallex_bot/atlas_cli.py wallex_bot/atlas_feature_health.py \
  tests/test_stage11_feature_health_no_market_fixtures.py \
  CHANGELOG_STAGE11_FEATURE_HEALTH_FA.md QUICKSTART_STAGE11_FEATURE_HEALTH_FA.md \
  scripts/apply_stage11_feature_health.sh patches/atlas_stage11_feature_health.patch
git commit -m 'Stage 11: readonly PIT feature health audit on verified Wallex candles'
git log -1 --format='%h %s'
echo '[Stage11] Champion, RiskGate, market facts, LIVE permissions and Watch unchanged.'
