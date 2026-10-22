#!/usr/bin/env bash
# Stage 4 offline research integration on exact Stage 3 commit. No live orders.
set -euo pipefail
cd "$(dirname "$0")/.."
PATCH='patches/atlas_stage4_validation.patch'
BRANCH='integration/atlas-validation'
if ! command -v git >/dev/null || [[ ! -d .git ]]; then
  echo '[BLOCKED] Existing Git checkout required; do not initialize a replacement repo.'; exit 1
fi
HEAD=$(git rev-parse HEAD)
BASE_BRANCH=$(git branch --show-current)
if [[ "$HEAD" != 1f43a04* || "$BASE_BRANCH" != 'integration/atlas-tmn-liquidation' ]]; then
  echo "[BLOCKED] Stage3 commit 1f43a04 and integration/atlas-tmn-liquidation required (found $BASE_BRANCH ${HEAD:0:12})."; exit 1
fi
if ! git diff --quiet || ! git diff --cached --quiet; then
  echo '[BLOCKED] Commit or save existing tracked changes before stage4.'; exit 1
fi
if git show-ref --quiet --verify "refs/heads/$BRANCH"; then
  echo '[BLOCKED] Integration branch already exists, refusing to duplicate.'; exit 1
fi
[[ -f "$PATCH" ]] || { echo '[BLOCKED] Missing patch'; exit 1; }
git apply --check "$PATCH"
git switch -c "$BRANCH"
git apply "$PATCH"
echo '[Stage4] RiskGate, ShadowBroker, and all market/model data preserved.'
if ! python -m pytest -q; then
  echo '[BLOCKED] Test failure: nothing committed. Review environment and stage4 source.'
  exit 1
fi
git add -- wallex_bot/atlas_cli.py wallex_bot/atlas_liquidation.py wallex_bot/atlas_validation.py \
  tests/test_atlas_validation_stage4_real_only.py \
  CHANGELOG_STAGE4_VALIDATION_FA.md QUICKSTART_STAGE4_VALIDATION_FA.md \
  README_STAGE4_PACKAGE_FA.md \
  scripts/apply_stage4_validation.sh patches/atlas_stage4_validation.patch
git commit -m 'Stage 4: audited real-history statistical validation and safe empty-paper no-op'
echo '[Stage4] Committed:'
git log -1 --format='%h %s'
echo '[Stage4] Live exchange order submission remains ABSENT. No candidate promoted.'
