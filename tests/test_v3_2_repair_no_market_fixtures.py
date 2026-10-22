"""V3.2 regression tests. No mocked OHLCV, prices, trades, or news.
Metadata ratios come from genuine user-reported Wallex training outputs.
"""
import json
import pytest
from wallex_bot.atlas_archive import Lake
from wallex_bot.atlas_diagnostics import audit_v3
from wallex_bot.atlas_deep import model_metadata_eligible, verified_champion


def test_manifest_array_does_not_crash_audit(tmp_path):
    lake=Lake(tmp_path)
    try:
        d=tmp_path/'models'
        d.mkdir()
        # Only an auxiliary format marker: no generated market data.
        (d/'existing_checkpoint.sources.json').write_text('[]',encoding='utf-8')
        outcome=audit_v3(lake)
        assert outcome['archive']['candles']==0
        assert (tmp_path/'reports'/'v3_2_audit.json').is_file()
        assert outcome['model_checkpoints']==[]
    finally:
        lake.close()


def test_prior_real_run_imbalanced_training_cannot_be_promoted():
    # Counts are from 2026-10-22 user's genuine execution: 321 train / 1430 val.
    cfg={'validation_protocol':'GLOBAL_UTC_PURGED_V1',
         'training_samples':321,'validation_samples':1430,
         'validation_pinball':0.0024635179297203993,
         'train_last_label_ts':1792400000,
         'validation_start_ts':1792450000}
    eligible, reasons=model_metadata_eligible(cfg)
    assert not eligible
    assert 'INADEQUATE_TRAIN_TO_VALIDATION_COVERAGE' in reasons


def test_unpromoted_shadow_model_fails_closed(tmp_path):
    with pytest.raises(RuntimeError,match='No approved explicit champion'):
        verified_champion(tmp_path)


def test_auxiliary_lists_and_unrelated_json_are_not_models(tmp_path):
    lake=Lake(tmp_path)
    try:
        m=tmp_path/'models';m.mkdir()
        (m/'old.sources.json').write_text(json.dumps([]),encoding='utf8')
        (m/'unrelated.json').write_text(json.dumps({'some_documentation':'true'}),encoding='utf8')
        report=audit_v3(lake)
        assert report['model_checkpoints']==[]
        assert report['warnings']
    finally:
        lake.close()
