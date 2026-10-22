#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
echo '[Atlas V3.2] Verify code contracts: no mocked market prices.'
python -m pytest -q
echo '[Atlas V3.2] Inspect the saved genuine Wallex archive and model lineage.'
python -m wallex_bot.atlas_cli audit-v3
echo '[Atlas V3.2] Train model challengers using LOCAL verified real Wallex history only.'
python -m wallex_bot.atlas_cli train-deep
echo '[Atlas V3.2] Verify model promotion and recorded provenance.'
python -m wallex_bot.atlas_cli audit-v3
echo '[Atlas V3.2] No live orders were sent. Detailed report: atlas_store/reports/v3_2_audit.json'
