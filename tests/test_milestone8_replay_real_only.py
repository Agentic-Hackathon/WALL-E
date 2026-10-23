"""Actual M8 development receipts; replay never mutates financial/memory state."""
import time
from pathlib import Path
import pytest
from wallex_bot.atlas_m8_evaluation import evaluate,epoch
from wallex_bot.atlas_m5_inference import logical_hash
from wallex_bot.atlas_study import fast_validate,source_manifest

ROOT=Path(__file__).resolve().parents[1]
DEV=ROOT/'atlas_store/research_challengers/milestone8/development_smoke_v1'

def test_actual_chronological_replay_is_read_only_and_cash_conserving():
    if not (DEV/'agentic_decisions.sqlite').exists():pytest.skip('Actual M8 development observations not installed')
    paths=[DEV/'shadow.sqlite',DEV/'context_memory.sqlite',DEV/'agentic_decisions.sqlite']
    before={str(p):logical_hash(p) for p in paths};result=evaluate(DEV)
    assert result['decision_count']>=2 and result['recorded_paper_transitions']==0
    assert all(r['review_identical'] and r['cash_conserved'] and r['exchange_fill_is_none'] for r in result['replay_checks'])
    assert result['realized_exchange_pnl'] is None and result['net_paper_cash_change_tmn']==0
    assert result['economic_edge']=='NO_VERIFIED_ECONOMIC_EDGE'
    assert before=={str(p):logical_hash(p) for p in paths}

def test_missing_history_is_not_success_or_fabricated_nav(tmp_path):
    result=evaluate(tmp_path)
    assert result['decision_count']==0 and result['net_paper_cash_change_tmn'] is None
    assert not result['nav_path'] and result['status']=='INSUFFICIENT_PROSPECTIVE_EVIDENCE'

def test_replay_period_requires_aware_valid_timestamps():
    with pytest.raises(ValueError,match='TIMEZONE'):epoch('2026-10-22')
    with pytest.raises(ValueError,match='FUTURE'):evaluate(DEV,end='2099-01-01T00:00:00Z')

def test_environment_change_stops_pinned_study(monkeypatch):
    import wallex_bot.atlas_study as module
    monkeypatch.setattr(module,'runtime_packages',lambda:{'control':'changed'})
    c={'source_manifest_LF_sha256':source_manifest(),'model_file_hashes':{},'runtime_packages':{'control':'original'}}
    with pytest.raises(RuntimeError,match='PINNED_ENVIRONMENT'):fast_validate(c)
