"""Stage 8: all tests use empty/unavailable books, not fabricated market data.

No price, candle, market quote, trade fill, outcome or news is fabricated.
The only generated decisions are RiskGate refusals on MISSING observations.
"""
from __future__ import annotations

import inspect
import sqlite3

import pytest

from wallex_bot.atlas_archive import Lake
from wallex_bot.atlas_broker import OrderIntent,ShadowBroker,OrderState
from wallex_bot.atlas_shadow import PaperAccount
from wallex_bot.atlas_replay import replay_decision
from wallex_bot import atlas_replay,atlas_agent


def test_no_ledger_is_not_created_by_replay(tmp_path):
    assert replay_decision(tmp_path)['status']=='NO_EXISTING_SHADOW_LEDGER'
    assert not (tmp_path/'shadow.sqlite').exists()


def test_missing_observations_are_replayed_as_refusal_not_fake_fill(tmp_path):
    lake=Lake(tmp_path)
    p=PaperAccount(lake)
    try:
        original=ShadowBroker(p).submit(OrderIntent('stage8-missing-0001','BTCTMN'),
                                        forecast={},book={},fee=.001)
        assert original.state==OrderState.PAPER_NOT_EXECUTED
        assert original.reason=='REJECTED'
        assert p.verify()
    finally:p.close();lake.close()
    result=replay_decision(tmp_path)
    assert result['status']=='MATCH'
    assert result['recorded_action']==result['recomputed_action']=='REJECTED'
    assert result['risk_reason']=='MISSING_OR_INVALID_OBSERVED_BOOK'
    assert result['full_model_or_execution_replay'] is False
    assert result['exchange_orders']==0


def test_replay_does_not_write_or_duplicate_an_existing_event(tmp_path):
    lake=Lake(tmp_path)
    p=PaperAccount(lake)
    try:
        p.trade('BTCTMN',{}, {},.001,client_order_id='stage8-repeat-00001')
        before=p.db.execute('SELECT id,hash,payload FROM events').fetchall()
        before_cash=p.get('cash_tmn')
        assert replay_decision(tmp_path)['status']=='MATCH'
        assert replay_decision(tmp_path,event_id=1)['status']=='MATCH'
        after=p.db.execute('SELECT id,hash,payload FROM events').fetchall()
        assert before==after
        assert before_cash==p.get('cash_tmn')
        assert p.db.execute('SELECT COUNT(*) FROM positions').fetchone()[0]==0
    finally:p.close();lake.close()


def test_legacy_event_has_explicit_no_snapshot(tmp_path):
    lake=Lake(tmp_path)
    p=PaperAccount(lake)
    try:
        with p.db:p.log('SYSTEM','LEGACY_AUDIT_EVENT',{'no_market_data':True})
    finally:p.close();lake.close()
    result=replay_decision(tmp_path,event_id=1)
    assert result['status']=='LEGACY_NO_RISK_SNAPSHOT'
    assert result['exchange_orders']==0


def test_tampering_with_paper_event_refuses_all_replay(tmp_path):
    lake=Lake(tmp_path)
    p=PaperAccount(lake)
    try:
        p.trade('BTCTMN',{}, {},.001)
        p.db.execute("UPDATE events SET action='CHANGED' WHERE id=1")
        p.db.commit()
    finally:p.close();lake.close()
    assert replay_decision(tmp_path)['status']=='AUDIT_HASH_CHAIN_INVALID'


def test_changed_risk_code_fails_closed_without_fabricated_observations(tmp_path,monkeypatch):
    lake=Lake(tmp_path)
    p=PaperAccount(lake)
    try:p.trade('BTCTMN',{}, {},.001)
    finally:p.close();lake.close()
    monkeypatch.setattr(atlas_replay,'_risk_source_hash',lambda:'CHANGED_CODE')
    assert replay_decision(tmp_path)['status']=='RISK_CODE_VERSION_MISMATCH'


def test_unknown_invalid_ids_do_not_change_storage(tmp_path):
    with pytest.raises(ValueError):replay_decision(tmp_path,event_id=0)
    with pytest.raises(ValueError):replay_decision(tmp_path,event_id=True)
    assert not (tmp_path/'shadow.sqlite').exists()


def test_stage8_source_does_not_import_external_data_or_order_api():
    source=inspect.getsource(atlas_replay)
    assert 'import requests' not in source
    assert 'WallexReadClient' not in source
    assert 'depth(' not in source
    assert 'market.depth' not in source
    assert 'PaperAccount(' not in source
    assert 'sqlite3.connect' in source and '?mode=ro' in source
    original_agent=inspect.getsource(atlas_agent.cycle)
    # LLM remains after risk but outside order submission arguments.
    assert "'risk_agent','llm_rationale_agent','shadow_execution_agent'" in original_agent
    assert 'broker_client_order_id' in original_agent
