#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
python -m wallex_bot.atlas_cli archive-all
