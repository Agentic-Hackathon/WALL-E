#!/usr/bin/env bash
# Applies Stage5 strict execution-mode isolation to one exact Stage4 Git branch.
# Source concepts: local integration playbook (QuantCrypt unavailable). No copied external code.
set -euo pipefail
cd "$(dirname "$0")/.."
PATCH='patches/atlas_stage5_mode_isolation.patch'
BRANCH='integration/atlas-mode-isolation'
if ! command -v git >/dev/null || [[ ! -d .git ]]; then
  echo '[BLOCKED] An existing Git worktree is required; refusing to initialize a new repository.';exit 1
fi
HEAD=$(git rev-parse HEAD)
BASE_BRANCH=$(git branch --show-current)
if [[ "$HEAD" != 1e0654f* || "$BASE_BRANCH" != 'integration/atlas-validation' ]]; then
  echo "[BLOCKED] Expected 1e0654f on integration/atlas-validation; received $BASE_BRANCH ${HEAD:0:12}.";exit 1
fi
if ! git diff --quiet || ! git diff --cached --quiet; then
  echo '[BLOCKED] Existing staged/tracked edits require a clean worktree before integration.';exit 1
fi
if git show-ref --quiet --verify "refs/heads/$BRANCH"; then
  echo '[BLOCKED] Integration branch already exists; refusing to overwrite it.';exit 1
fi
[[ -f "$PATCH" ]] || { echo '[BLOCKED] Missing Stage5 Git patch';exit 1; }
git apply --check "$PATCH"
git switch -c "$BRANCH"
git apply "$PATCH"
echo '[Stage5] BACKTEST context read-only, SHADOW broker gated, LIVE hard-disabled.'
if ! python -m pytest -q;then
  echo '[BLOCKED] Tests failed: changes are uncommitted. Do not enable trade paths.';exit 1
fi
python -m wallex_bot.atlas_cli mode-status
git add -- wallex_bot/atlas_mode.py wallex_bot/atlas_context.py wallex_bot/atlas_shadow.py \
  wallex_bot/atlas_watch.py wallex_bot/atlas_agent.py wallex_bot/atlas_broker.py \
  wallex_bot/atlas_liquidation.py wallex_bot/atlas_validation.py wallex_bot/atlas_cli.py \
  tests/test_stage5_mode_isolation_real_only.py \
  CHANGELOG_STAGE5_MODE_ISOLATION_FA.md QUICKSTART_STAGE5_MODE_ISOLATION_FA.md \
  scripts/apply_stage5_mode.sh patches/atlas_stage5_mode_isolation.patch
git commit -m 'Stage 5: explicit execution modes and zero backtest memory writes'
echo '[Stage5] Committed:'
git log -1 --format='%h %s'
echo '[Stage5] Zero real Wallex orders were enabled. Stage4 research signals remain blocked.'
