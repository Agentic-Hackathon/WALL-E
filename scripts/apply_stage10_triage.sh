#!/usr/bin/env bash
# Stage 10: *ONLY* read saved evidence. The RiskGate is never modified.
set -euo pipefail
cd "$(dirname "$0")/.."
BASE=0bc8af2
BRANCH=integration/atlas-edge-triage
PATCH=patches/atlas_stage10_edge_triage.patch
if ! command -v git >/dev/null || [[ ! -d .git ]]; then
  echo '[BLOCKED] Run inside original Wallex Atlas Git checkout.'; exit 1
fi
HEAD=$(git rev-parse HEAD)
CURRENT=$(git branch --show-current)
if [[ "$HEAD" != "$BASE"* || "$CURRENT" != 'integration/atlas-operational-audit' ]]; then
  echo "[BLOCKED] Expected $BASE on integration/atlas-operational-audit. Actual $CURRENT ${HEAD:0:12}"; exit 1
fi
if ! git diff --quiet || ! git diff --cached --quiet; then
  echo '[BLOCKED] Local tracked modifications present. Nothing applied.'; exit 1
fi
if git show-ref --quiet --verify "refs/heads/$BRANCH"; then
  echo '[BLOCKED] Target branch already exists. Nothing applied.'; exit 1
fi
[[ -f "$PATCH" ]] || { echo '[BLOCKED] Stage 10 patch missing.'; exit 1; }
git apply --check "$PATCH"
git switch -c "$BRANCH"
git apply "$PATCH"
echo '[Stage10] Read-only forensic analysis; q10 and RiskGate policy unchanged.'
if ! python -m pytest -q; then
  echo '[BLOCKED] Tests failed. No commit created.'; exit 1
fi
python -m wallex_bot.atlas_cli edge-triage
# Added installer/patch are bundled by the user; no arbitrary untracked files staged.
git add -- wallex_bot/atlas_cli.py wallex_bot/atlas_forward.py wallex_bot/atlas_edge_triage.py \
  tests/test_stage10_edge_triage_no_market_fixtures.py \
  CHANGELOG_STAGE10_EDGE_TRIAGE_FA.md QUICKSTART_STAGE10_EDGE_TRIAGE_FA.md \
  scripts/apply_stage10_triage.sh patches/atlas_stage10_edge_triage.patch
git commit -m 'Stage 10: real-receipt forecast edge and runtime-failure triage'
git log -1 --format='%h %s'
echo '[Stage10] No live execution transport or model/risk permission change.'
