#!/usr/bin/env bash
# Stage 6: PIT evidence retrieval, no market data or exchange order writes.
set -euo pipefail
cd "$(dirname "$0")/.."
PATCH=patches/atlas_stage6_finmem_pit_memory.patch
BRANCH=integration/atlas-finmem-memory
if ! command -v git >/dev/null || [[ ! -d .git ]]; then
  echo '[BLOCKED] Existing Git checkout required. No replacement git init.';exit 1
fi
HEAD=$(git rev-parse HEAD)
BASE_BRANCH=$(git branch --show-current)
if [[ "$HEAD" != 250f342* || "$BASE_BRANCH" != 'integration/atlas-mode-isolation' ]]; then
  echo "[BLOCKED] Expected commit 250f342 and integration/atlas-mode-isolation, found $BASE_BRANCH ${HEAD:0:12}"; exit 1
fi
if ! git diff --quiet || ! git diff --cached --quiet; then
  echo '[BLOCKED] Uncommitted tracked changes. Commit or stash first.';exit 1
fi
if git show-ref --quiet --verify "refs/heads/$BRANCH"; then
  echo '[BLOCKED] Stage6 branch exists. Refusing duplicate apply.';exit 1
fi
[[ -f "$PATCH" ]] || { echo '[BLOCKED] Stage6 patch absent';exit 1; }
git apply --check "$PATCH"
git switch -c "$BRANCH"
git apply "$PATCH"
echo '[Stage6] PIT ranked operational evidence, BACKTEST isolated; no trading permission changed.'
if ! python -m pytest -q; then
  echo '[BLOCKED] Test failure, no commit created.';exit 1
fi
python -m wallex_bot.atlas_cli memory-rank --top 8
# The patch/installer were extracted into the project root before this step.
git add -- wallex_bot/atlas_context.py wallex_bot/atlas_memory.py wallex_bot/atlas_agent.py \
   wallex_bot/atlas_cli.py tests/test_stage6_pit_memory_real_only.py \
   CHANGELOG_STAGE6_FINMEM_FA.md QUICKSTART_STAGE6_FINMEM_FA.md \
   scripts/apply_stage6_memory.sh patches/atlas_stage6_finmem_pit_memory.patch
git commit -m 'Stage 6: PIT FinMem-inspired operational memory ranking without execution authority'
echo '[Stage6] Commit:'
git log -1 --format='%h %s'
echo '[Stage6] LIVE execution remains HARD_DISABLED; no new market facts or orders.'
