#!/usr/bin/env bash
# Stage 12: researcher-only evidence comparison on genuine, verified candles.
set -euo pipefail
cd "$(dirname "$0")/.."
BASE=ecab9d0
BRANCH=integration/atlas-feature-recipe
PATCH=patches/atlas_stage12_feature_recipe.patch
if ! command -v git >/dev/null || [[ ! -d .git ]]; then
  echo '[BLOCKED] Run inside the original Wallex Atlas Git checkout.'; exit 1
fi
HEAD=$(git rev-parse HEAD)
CURRENT=$(git branch --show-current)
if [[ "$HEAD" != "$BASE"* || "$CURRENT" != 'integration/atlas-feature-health' ]]; then
  echo "[BLOCKED] Expected $BASE on integration/atlas-feature-health. Actual $CURRENT ${HEAD:0:12}"; exit 1
fi
if ! git diff --quiet || ! git diff --cached --quiet; then
  echo '[BLOCKED] Tracked local modifications; leave project intact.'; exit 1
fi
if git show-ref --quiet --verify "refs/heads/$BRANCH"; then
  echo '[BLOCKED] Target branch exists; no overwrite.'; exit 1
fi
[[ -f "$PATCH" ]] || { echo '[BLOCKED] Stage 12 patch missing.'; exit 1; }
git apply --check "$PATCH"
git switch -c "$BRANCH"
git apply "$PATCH"
echo '[Stage12] SHA-verified real-candle V1 versus independent research-only V2 comparison.'
if ! python -m pytest -q; then
  echo '[BLOCKED] Tests failed; no commit created.'; exit 1
fi
# No new archive data is created by running the read-only audit.
python -m wallex_bot.atlas_cli feature-recipe-audit --resolution 15 --top 8
git add -- wallex_bot/atlas_cli.py wallex_bot/atlas_feature_recipe.py   tests/test_stage12_feature_recipe_no_market_fixtures.py   CHANGELOG_STAGE12_FEATURE_RECIPE_FA.md QUICKSTART_STAGE12_FEATURE_RECIPE_FA.md   scripts/apply_stage12_feature_recipe.sh patches/atlas_stage12_feature_recipe.patch
git commit -m 'Stage 12: read-only genuine-candle challenger feature recipe comparison'
git log -1 --format='%h %s'
echo '[Stage12] No Champion, Shadow, RiskGate, training, or LIVE permissions changed.'
