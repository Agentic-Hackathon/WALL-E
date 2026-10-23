#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
BASE=f154761
CURRENT=$(git branch --show-current)
HEAD=$(git rev-parse HEAD)
TARGET=integration/atlas-paired-challenger-v2
PATCH=patches/atlas_stage13_challenger.patch
if [[ "$CURRENT" != 'integration/atlas-feature-recipe' || "$HEAD" != "$BASE"* ]]; then
    echo "[BLOCKED] Expected $BASE on integration/atlas-feature-recipe; got $CURRENT ${HEAD:0:12}"; exit 1
fi
if ! git diff --quiet || ! git diff --cached --quiet; then
    echo '[BLOCKED] Tracked local changes must be handled before patching.'; exit 1
fi
if git show-ref --quiet --verify "refs/heads/$TARGET"; then
    echo "[BLOCKED] Branch $TARGET already exists."; exit 1
fi
[[ -f "$PATCH" ]] || { echo '[BLOCKED] Patch file not extracted.'; exit 1; }
git apply --check "$PATCH"
git switch -c "$TARGET"
git apply "$PATCH"
echo '[Stage13] Paired chronological V1/V2 research; no champion, paper or live orders modified.'
python -m pytest -q
python -m wallex_bot.atlas_cli challenger-preflight --mode BACKTEST --top 8 --hours 24
git add -- wallex_bot/atlas_challenger_v2.py wallex_bot/atlas_cli.py wallex_bot/atlas_mode.py \
    tests/test_stage13_challenger_no_market_fixtures.py CHANGELOG_STAGE13_PAIRED_CHALLENGER_FA.md \
    QUICKSTART_STAGE13_PAIRED_CHALLENGER_FA.md scripts/apply_stage13_challenger.sh patches/atlas_stage13_challenger.patch
git commit -m 'Stage 13: paired genuine-candle research challenger without promotion'
git log -1 --oneline
echo '[Stage13] No automatic training, model promotion, or live trading. Separate opt-in command for training.'
