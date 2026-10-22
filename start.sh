#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
echo '[Wallex Atlas] Installing required dependencies; no API key printed.'
python -m pip install -r requirements.txt -r requirements-agent.txt
echo '[Wallex Atlas] Contract tests (NO synthetic market prices).'
python -m pytest -q
echo '[Wallex Atlas] Start autonomous market research, no live orders.'
python -m wallex_bot.atlas_cli run --days 3 --limit-markets 20
