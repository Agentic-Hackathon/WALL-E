#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
BASE=b8af77f
CURRENT=$(git branch --show-current)
HEAD=$(git rev-parse HEAD)
TARGET=integration/atlas-saved-checkpoint-eval
PATCH=patches/atlas_stage14_checkpoint_eval.patch
if [[ "$CURRENT" != 'integration/atlas-paired-challenger-v2' || "$HEAD" != "$BASE"* ]]; then
    echo "[BLOCKED] Expected $BASE on integration/atlas-paired-challenger-v2; got $CURRENT ${HEAD:0:12}"
    exit 1
fi
if ! git diff --quiet || ! git diff --cached --quiet; then
    echo '[BLOCKED] Tracked local changes must be handled before patching.'
    exit 1
fi
if git show-ref --quiet --verify "refs/heads/$TARGET"; then
    echo "[BLOCKED] Branch $TARGET already exists."
    exit 1
fi
[[ -f "$PATCH" ]] || { echo '[BLOCKED] Patch file not extracted.';exit 1; }
git apply --check --exclude=scripts/apply_stage14_eval.sh "$PATCH"
git switch -c "$TARGET"
git apply --exclude=scripts/apply_stage14_eval.sh "$PATCH"
echo '[Stage14] Strict saved model/manifest/split forensic evaluation; no new market data.'
python -m pytest -q
python -m wallex_bot.atlas_cli challenger-evaluate --mode BACKTEST
git add -- wallex_bot/atlas_challenger_eval.py wallex_bot/atlas_cli.py wallex_bot/atlas_mode.py \
    tests/test_stage14_challenger_saved_evaluation.py CHANGELOG_STAGE14_SAVED_CHECKPOINT_EVAL_FA.md \
    QUICKSTART_STAGE14_EVAL_FA.md scripts/apply_stage14_eval.sh patches/atlas_stage14_checkpoint_eval.patch
git commit -m 'Stage 14: provenance-gated evaluation of saved paired challenger checkpoints'
git log -1 --oneline
echo '[Stage14] RiskGate, Champion, ShadowBroker, archive and LIVE permissions unchanged.'
