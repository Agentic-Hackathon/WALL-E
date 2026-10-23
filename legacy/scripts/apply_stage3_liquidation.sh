#!/usr/bin/env bash
# Stage 3: TMN shadow finalization patch for exact Stage2 Broker branch.
# Does not use API keys, order endpoints, or synthetic market observations.
set -euo pipefail
cd "$(dirname "$0")/.."
PATCH='patches/atlas_stage3_tmn_liquidation.patch'
BRANCH='integration/atlas-tmn-liquidation'
if ! command -v git >/dev/null; then echo '[BLOCKED] Git is required'; exit 1; fi
if [[ ! -d .git ]]; then echo '[BLOCKED] Run from your existing Git checkout'; exit 1; fi
HEAD=$(git rev-parse HEAD)
BASE_BRANCH=$(git branch --show-current)
if [[ "$HEAD" != 58d3236* || "$BASE_BRANCH" != 'integration/atlas-broker' ]]; then
  echo "[BLOCKED] Requires integration/atlas-broker at 58d3236 (found $BASE_BRANCH at ${HEAD:0:12})."
  exit 1
fi
if ! git diff --quiet || ! git diff --cached --quiet; then
  echo '[BLOCKED] Tracked working tree has changes; preserve them before integrating.'
  exit 1
fi
if git show-ref --verify --quiet "refs/heads/$BRANCH"; then
  echo '[BLOCKED] Stage 3 branch already exists. Never silently reapply patches.'
  exit 1
fi
if [[ ! -f "$PATCH" ]]; then echo '[BLOCKED] Stage3 patch absent'; exit 1; fi
git apply --check "$PATCH"
git switch -c "$BRANCH"
git apply "$PATCH"
echo '[Stage3] Shadow final TMN closeout flows through Broker and deterministic RiskGate.'
if ! python -m pytest -q; then
  echo '[BLOCKED] Tests failed. No commit made; inspect branch and fix environment or code first.'
  exit 1
fi
git add -- \
  wallex_bot/atlas_liquidation.py wallex_bot/atlas_broker.py wallex_bot/atlas_risk.py \
  wallex_bot/atlas_shadow.py wallex_bot/atlas_watch.py wallex_bot/atlas_cli.py \
  tests/test_atlas_liquidation_stage3_real_only.py tests/test_atlas_risk_contract.py \
  CHANGELOG_STAGE3_TMN_LIQUIDATION_FA.md QUICKSTART_STAGE3_TMN_LIQUIDATION_FA.md \
  scripts/apply_stage3_liquidation.sh patches/atlas_stage3_tmn_liquidation.patch
git commit -m 'Stage 3: deterministic broker-gated paper TMN liquidation and reporting'
echo '[Stage3] New branch and commit:'
git log -1 --format='%h %s'
echo '[Stage3] NO real Wallex orders were enabled or submitted.'
