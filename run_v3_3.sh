#!/usr/bin/env bash
set -euo pipefail
python -m pytest -q
python -m wallex_bot.atlas_cli contest-readiness
python -m wallex_bot.atlas_cli forward-report
printf '\n[Atlas V3.3] Read-only audit complete. No exchange orders.\n'
printf '[Atlas V3.3] For prospective genuine 48h data capture from your machine:\n'
printf 'python -m wallex_bot.atlas_cli watch --hours 48\n'
