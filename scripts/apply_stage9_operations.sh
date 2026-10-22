#!/usr/bin/env bash
# Stage 9: only-read existing Wallex Atlas evidence; no market requests or trades.
set -euo pipefail
cd "$(dirname "$0")/.."
PATCH=patches/atlas_stage9_operations.patch
BRANCH=integration/atlas-operational-audit
if ! command -v git >/dev/null || [[ ! -d .git ]]; then
  echo '[BLOCKED] Existing Git checkout required.'; exit 1
fi
HEAD=$(git rev-parse HEAD)
BASE_BRANCH=$(git branch --show-current)
if [[ "$HEAD" != e6673e3* || "$BASE_BRANCH" != 'integration/atlas-decision-replay' ]]; then
  echo "[BLOCKED] Expected e6673e3 on integration/atlas-decision-replay; actual $BASE_BRANCH ${HEAD:0:12}"; exit 1
fi
if ! git diff --quiet || ! git diff --cached --quiet; then
  echo '[BLOCKED] Tracked working tree is not clean.'; exit 1
fi
if git show-ref --verify --quiet "refs/heads/$BRANCH"; then
  echo '[BLOCKED] Target branch already exists.'; exit 1
fi
[[ -f "$PATCH" ]] || { echo '[BLOCKED] Stage 9 patch missing'; exit 1; }
git apply --check "$PATCH"
git switch -c "$BRANCH"
git apply "$PATCH"
echo '[Stage9] Source of truth: stored receipts only; no order, network or model call.'
if ! python -m pytest -q; then
  echo '[BLOCKED] Tests failed. No commit created.'; exit 1
fi
python -m wallex_bot.atlas_cli operations-report

git add -- wallex_bot/atlas_cli.py wallex_bot/atlas_operational.py \
    tests/test_stage9_operational_diagnostics_real_only.py \
    CHANGELOG_STAGE9_OPERATIONAL_AUDIT_FA.md QUICKSTART_STAGE9_OPERATIONS_FA.md \
    scripts/apply_stage9_operations.sh patches/atlas_stage9_operations.patch
git commit -m 'Stage 9: read-only empirical operations and forecast-cost audit'
git log -1 --format='%h %s'
echo '[Stage9] Model, RiskGate, Broker, archive and live-order permissions unchanged.'
