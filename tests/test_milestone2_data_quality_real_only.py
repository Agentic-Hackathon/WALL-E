"""Milestone 2 contracts without fabricated OHLCV, quotes, fills or news."""
import csv
import json

import pytest

from wallex_bot.atlas_archive import Lake
from wallex_bot.atlas_data_quality import build_reports, probe_public_timeframes


def test_empty_catalog_audit_keeps_required_output_contract(tmp_path):
    lake=Lake(tmp_path/'lake')
    try:
        result=build_reports(lake,tmp_path/'reports')
    finally:
        lake.close()
    assert result['assets']==0 and result['rows']==0
    expected=('data_coverage.csv','data_coverage_summary.json','data_download_incidents.json',
              'timeframe_integrity.json','pit_data_quality.json','download_progress.json')
    for name in expected:
        assert (tmp_path/'reports'/name).is_file()
    with (tmp_path/'reports'/'data_coverage.csv').open(encoding='utf-8') as handle:
        assert 'coverage_percent' in next(csv.reader(handle))
    pit=json.loads((tmp_path/'reports'/'pit_data_quality.json').read_text(encoding='utf-8'))
    assert 'never proof' in pit['candles']['rule']


def test_invalid_public_probe_symbol_fails_before_any_network():
    with pytest.raises(ValueError):
        probe_public_timeframes('BTC-TMN')
