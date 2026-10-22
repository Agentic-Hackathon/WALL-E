"""Stage 5: contract and operational-metadata-only tests. No fabricated prices/news/fills.

These tests do NOT prove exchange connectivity, trading performance, or readiness.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import sqlite3

import pytest

from wallex_bot.atlas_mode import ExecutionMode, ModeSafetyError, cli_mode, mode_status, require_mode
from wallex_bot.atlas_context import ContextStore, make_packet
from wallex_bot.atlas_broker import ShadowBroker
from wallex_bot.atlas_shadow import PaperAccount, shadow_cycle
from wallex_bot.atlas_watch import run as watch
from wallex_bot.atlas_agent import cycle
from wallex_bot.atlas_liquidation import liquidate_paper_positions
from wallex_bot.atlas_validation import validate_archive, store_report


def test_mode_name_cannot_alias_live_or_be_guessed():
    assert cli_mode('validate') is ExecutionMode.BACKTEST
    assert cli_mode('watch') is ExecutionMode.SHADOW
    assert cli_mode('benchmark','BACKTEST') is ExecutionMode.BACKTEST
    with pytest.raises(ModeSafetyError):
        cli_mode('watch','BACKTEST')
    with pytest.raises(ModeSafetyError):
        cli_mode('validate','SHADOW')
    with pytest.raises(ModeSafetyError,match='HARD_DISABLED'):
        cli_mode('watch','LIVE')
    with pytest.raises(ModeSafetyError):
        cli_mode('validate','live')
    with pytest.raises(ModeSafetyError):
        cli_mode('context-status','BACKTEST')
    assert not mode_status()['real_exchange_order_submission']


def test_backtest_memory_missing_is_read_only_and_creates_nothing(tmp_path):
    root=tmp_path/'intentionally_absent'
    store=ContextStore(root,mode='BACKTEST')
    assert store.status()['hash_chain_valid'] is True
    assert store.recent()==[]
    assert store.review_candidates()==[]
    with pytest.raises(ModeSafetyError):
        store.record('WATCH_CYCLE','watch_log.jsonl',{'cycles_completed':1})
    with pytest.raises(ModeSafetyError):
        store.propose_lesson('0'*64,'No invalid lesson created')
    store.close()
    assert not root.exists()
    packet=make_packet(SimpleNamespace(root=root),phase='audit',mode='BACKTEST')
    assert packet['summary']['memory_read_only'] is True
    assert packet['summary']['execution_mode']=='BACKTEST'
    assert not root.exists()


def test_existing_operational_memory_immutable_in_backtest(tmp_path):
    writable=ContextStore(tmp_path)
    original=writable.record('RESEARCH_INCIDENT','watch_log.jsonl',{'error_type':'Timeout'})
    writable.close()
    readonly=ContextStore(tmp_path,mode=ExecutionMode.BACKTEST)
    assert readonly.verify()=={'hash_chain_valid':True,'events_verified':1}
    # No hindsight leakage from SHADOW operational memory to BACKTEST packets.
    assert readonly.recent()==[]
    assert readonly.review_candidates()==[]
    packet=make_packet(SimpleNamespace(root=tmp_path),phase='audit',mode='BACKTEST')
    assert packet['working_memory']==[]
    with pytest.raises(ModeSafetyError):
        readonly.record('RESEARCH_INCIDENT','log',{'error_type':'Error'})
    with pytest.raises(ModeSafetyError):
        readonly.propose_lesson(original,'Investigate observed incident before redeployment')
    with pytest.raises(ModeSafetyError):
        readonly.validate_lesson_from_evidence(7,'not_used','0'*64)
    with pytest.raises(sqlite3.OperationalError):
        readonly.db.execute("DELETE FROM context_events")
    readonly.close()
    reopened=ContextStore(tmp_path)
    assert reopened.verify()=={'hash_chain_valid':True,'events_verified':1}
    reopened.close()


def test_backtest_cannot_open_shadow_ledger_or_broker(tmp_path):
    pseudo_lake=SimpleNamespace(root=tmp_path)
    with pytest.raises(ModeSafetyError):
        PaperAccount(pseudo_lake,mode='BACKTEST')
    with pytest.raises(ModeSafetyError):
        ShadowBroker(None,mode='BACKTEST')
    with pytest.raises(ModeSafetyError):
        PaperAccount(pseudo_lake,mode='LIVE')
    assert not (tmp_path/'shadow.sqlite').exists()


def test_backtest_cannot_use_runtime_mutating_entrypoints(tmp_path):
    lake=SimpleNamespace(root=tmp_path)
    for fn, kwargs in [
        (watch,{'mode':'BACKTEST'}),
        (shadow_cycle,{'mode':'BACKTEST'}),
        (liquidate_paper_positions,{'mode':'BACKTEST'}),
    ]:
        with pytest.raises(ModeSafetyError):fn(lake,**kwargs)
    with pytest.raises(ModeSafetyError):
        cycle(lake,mode='BACKTEST')
    with pytest.raises(ModeSafetyError,match='HARD_DISABLED'):
        cycle(lake,mode='LIVE')
    assert list(tmp_path.iterdir())==[]


def test_backtest_validation_writes_research_report_only(tmp_path):
    lake=SimpleNamespace(root=tmp_path)
    with pytest.raises(ModeSafetyError):
        validate_archive(lake,mode='SHADOW')
    with pytest.raises(ModeSafetyError):
        store_report(lake,{},mode='SHADOW')
    # Metadata-only report: no market values, trades, fills or benchmark numbers.
    path=store_report(lake,{'status':'INSUFFICIENT_EVIDENCE'},mode='BACKTEST')
    assert path.is_file()
    assert not (tmp_path/'shadow.sqlite').exists()
    assert not (tmp_path/'context_memory.sqlite').exists()
    assert not (tmp_path/'agent_checkpoints.sqlite').exists()
