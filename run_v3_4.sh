#!/usr/bin/env bash
# Installs nothing and does not contact Wallex, alter checkpoints, or start a second watch.
set -euo pipefail
cd "$(dirname "$0")"
echo '[Atlas V3.4] Contract tests: no fabricated prices.'
python -m pytest -q
echo '[Atlas V3.4] Inspect durable context memory and progressive skill routing.'
python -m wallex_bot.atlas_cli context-status
python -m wallex_bot.atlas_cli context-review
echo '[Atlas V3.4] Existing archive, live watch session and champion are untouched.'
