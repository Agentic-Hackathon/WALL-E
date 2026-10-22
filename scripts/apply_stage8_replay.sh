#!/usr/bin/env bash
# Stage 8: replay existing shadow decisions, no new market data or exchange orders.
set -euo pipefail
cd "$(dirname "$0")/.."
PATCH=patches/atlas_stage8_replay.patch
BRANCH=integration/atlas-decision-replay
if ! command -v git >/dev/null || [[ ! -d .git ]]; then
  echo '[BLOCKED] Existing Git checkout required.'; exit 1
fi
HEAD=$(git rev-parse HEAD)
BASE_BRANCH=$(git branch --show-current)
if [[ "$HEAD" != 0b917d9* || "$BASE_BRANCH" != 'integration/atlas-llm-rationale' ]]; then
  echo "[BLOCKED] Expected 0b917d9 on integration/atlas-llm-rationale; actual $BASE_BRANCH ${HEAD:0:12}"; exit 1
fi
if ! git diff --quiet || ! git diff --cached --quiet; then
  echo '[BLOCKED] Tracked working tree is not clean; commit/stash tracked edits first.'; exit 1
fi
if git show-ref --verify --quiet "refs/heads/$BRANCH"; then
  echo '[BLOCKED] Target branch already exists; refusing repeated install.'; exit 1
fi
[[ -f "$PATCH" ]] || { echo '[BLOCKED] Stage 8 patch missing'; exit 1; }
git apply --check "$PATCH"
git switch -c "$BRANCH"
git apply "$PATCH"
echo '[Stage8] SHA-linked deterministic RiskGate replay; old events are never fabricated.'
if ! python -m pytest -q; then
  echo '[BLOCKED] Tests failed; no Stage 8 commit created.'; exit 1
fi
python -m wallex_bot.atlas_cli replay-decision
git add -- wallex_bot/atlas_agent.py wallex_bot/atlas_shadow.py wallex_bot/atlas_cli.py \
    wallex_bot/atlas_replay.py tests/test_stage8_replay_without_synthetic_market.py \
    CHANGELOG_STAGE8_DECISION_REPLAY_FA.md QUICKSTART_STAGE8_REPLAY_FA.md \
    scripts/apply_stage8_replay.sh patches/atlas_stage8_replay.patch
git commit -m 'Stage 8: read-only deterministic replay of risk decisions with provenance'
echo '[Stage8] Commit:'
git log -1 --format='%h %s'
echo '[Stage8] No live Wallex order transport exists. No model or strategy promoted.'
