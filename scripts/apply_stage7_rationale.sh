#!/usr/bin/env bash
# Stage 7: advisory-only, local, cached LLM explanations; NO trading permission.
set -euo pipefail
cd "$(dirname "$0")/.."
PATCH=patches/atlas_stage7_llm_advisory.patch
BRANCH=integration/atlas-llm-rationale
if ! command -v git >/dev/null || [[ ! -d .git ]]; then
  echo '[BLOCKED] Existing Git checkout required; no Git repository initialized.'; exit 1
fi
HEAD=$(git rev-parse HEAD)
BASE_BRANCH=$(git branch --show-current)
if [[ "$HEAD" != ddc22e0* || "$BASE_BRANCH" != 'integration/atlas-finmem-memory' ]]; then
  echo "[BLOCKED] Expected ddc22e0 on integration/atlas-finmem-memory; found $BASE_BRANCH ${HEAD:0:12}"; exit 1
fi
if ! git diff --quiet || ! git diff --cached --quiet; then
  echo '[BLOCKED] Tracked working tree not clean. Commit/stash first.'; exit 1
fi
if git show-ref --verify --quiet "refs/heads/$BRANCH"; then
  echo '[BLOCKED] Stage 7 branch already exists; refusing repeated application.'; exit 1
fi
[[ -f "$PATCH" ]] || { echo '[BLOCKED] Patch missing'; exit 1; }
git apply --check "$PATCH"
git switch -c "$BRANCH"
git apply "$PATCH"
echo '[Stage7] Independent advisory rationale, cannot influence RiskGate or Broker.'
if ! python -m pytest -q; then
  echo '[BLOCKED] Test suite failed; NO COMMIT CREATED.'; exit 1
fi
python -m wallex_bot.atlas_cli rationale-status
git add -- wallex_bot/atlas_agent.py wallex_bot/atlas_cli.py \
  wallex_bot/atlas_rationale.py tests/test_stage7_advisory_real_only.py \
  CHANGELOG_STAGE7_LLM_RATIONALE_FA.md QUICKSTART_STAGE7_LLM_RATIONALE_FA.md \
  scripts/apply_stage7_rationale.sh patches/atlas_stage7_llm_advisory.patch
git commit -m 'Stage 7: immutable local LLM advisory rationale with risk isolation'
echo '[Stage7] Commit:'
git log -1 --format='%h %s'
echo '[Stage7] REAL ORDER SUBMISSION HARD-DISABLED; no economic candidate promoted.'
