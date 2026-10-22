#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
python -m wallex_bot.atlas_dashboard_eval --hours 24 --top 12
