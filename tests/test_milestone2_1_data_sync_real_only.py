"""Milestone 2.1 contracts; no fabricated candle, quote, fill, or API key."""
from __future__ import annotations

import threading
from pathlib import Path

import pytest

from wallex_bot.atlas_archive import Lake
from wallex_bot.atlas_data_sync import DataSyncManager
from wallex_bot.wallex_api import account_connection_status


def test_empty_catalog_refuses_to_plan_or_decide(tmp_path):
    lake=Lake(tmp_path/'lake')
    try:
        sync=DataSyncManager(lake)
        with pytest.raises(ValueError,match='nonempty uppercase catalog symbols'):
            sync.plan()
        readiness=sync.market_readiness('BTCTMN',now=1_700_000_000)
        assert readiness['ready'] is False
        assert readiness['reason']=='MISSING_OR_STALE_VERIFIED_INPUT'
    finally:
        lake.close()


def test_invalid_sync_scope_cannot_open_a_network_path(tmp_path):
    lake=Lake(tmp_path/'lake')
    try:
        with pytest.raises(ValueError,match='invalid sync scope'):
            DataSyncManager(lake).plan(scope='anything-goes')
    finally:
        lake.close()


def test_scheduler_is_stoppable_without_running_a_market_request(tmp_path):
    lake=Lake(tmp_path/'lake')
    try:
        sync=DataSyncManager(lake)
        event=threading.Event();event.set()
        result=sync.run_continuous(event,interval_seconds=1)
        assert result['status']=='STOPPED' and result['cycles']==0
    finally:
        lake.close()


def test_sync_status_survives_a_separate_manager_start(tmp_path):
    root=tmp_path/'lake'
    first=Lake(root)
    try:
        assert DataSyncManager(first).status()['lease']['held'] is False
    finally:
        first.close()
    second=Lake(root)
    try:
        status=DataSyncManager(second).status()
        assert status['resume_source']=='catalog.sqlite.download_progress'
        assert status['live_execution']=='HARD_DISABLED'
    finally:
        second.close()


def test_network_outage_preserves_empty_archive_and_records_resume_state(tmp_path,monkeypatch):
    """Controlled transport failure; it creates no observations or fabricated bars."""
    from wallex_bot import market
    lake=Lake(tmp_path/'lake')
    monkeypatch.setattr(market,'candles_sparse',lambda *_args,**_kwargs:(_ for _ in ()).throw(ConnectionError('offline')))
    try:
        result=lake.harvest(resolutions=('1',),windows=[('BTCTMN','1',1_700_000_040,1_700_000_100)],
                            delay=.02,retries=0,workers=1)
        progress=lake.db.execute('SELECT status FROM download_progress').fetchone()[0]
        assert result['failed']==1 and result['complete']==0
        assert progress=='FAILED'
        assert lake.db.execute('SELECT count(*) FROM chunks').fetchone()[0]==0
    finally:
        lake.close()


def test_account_status_without_environment_key_is_safe(monkeypatch):
    monkeypatch.delenv('WALLEX_API_KEY',raising=False)
    result=account_connection_status()
    assert result['status']=='WALLEX_API_KEY_UNSET'
    assert result['connection']=='NOT_ATTEMPTED'
    assert result['live_execution']=='HARD_DISABLED'


def test_sync_module_does_not_reference_local_password_file():
    source=Path('wallex_bot/atlas_data_sync.py').read_text(encoding='utf-8')
    api_source=Path('wallex_bot/wallex_api.py').read_text(encoding='utf-8')
    assert 'pass.txt' not in source
    # The API module may document the forbidden filename, but must not open it.
    assert "Path('pass.txt')" not in api_source
    assert 'open(' not in api_source


def test_watch_cannot_issue_a_shadow_decision_when_sync_is_not_ready(tmp_path,monkeypatch):
    """This simulates orchestration state, never prices/candles or exchange I/O."""
    from wallex_bot import atlas_watch
    lake=Lake(tmp_path/'lake')
    class UnreadySync:
        def __init__(self,_lake):pass
        def _priority_symbols(self,_top,_scope):return ['BTCTMN']
        def feature_sync_plan(self,**_kwargs):return {'feature_requirements':{}}
        def run(self,**_kwargs):
            return {'status':'COMPLETED','complete':0,'failed':0,
                    'plan':{'symbols':['BTCTMN']},'derived_requested':[]}
        def feature_readiness(self,_symbol,_profile):
            return {'symbol':'BTCTMN','ready':False,'reason':'MISSING_OR_STALE_VERIFIED_INPUT'}
    class Context:
        def __init__(self,*_args,**_kwargs):pass
        def record(self,*_args,**_kwargs):return 'context-receipt'
        def close(self):pass
    ticks=iter((0.0,0.0,3601.0,3601.0))
    monkeypatch.setattr(lake,'symbols',lambda _scope:['BTCTMN'])
    monkeypatch.setattr(atlas_watch,'DataSyncManager',UnreadySync)
    monkeypatch.setattr(atlas_watch,'harvest_news',lambda *_args,**_kwargs:{'fetched_articles_count_attempted':0})
    monkeypatch.setattr(atlas_watch,'ContextStore',Context)
    monkeypatch.setattr(atlas_watch.time,'time',lambda:next(ticks))
    monkeypatch.setattr(atlas_watch.time,'monotonic',lambda:0.0)
    monkeypatch.setattr(atlas_watch.time,'sleep',lambda _seconds:None)
    monkeypatch.setattr(atlas_watch,'shadow_cycle',lambda *_args,**_kwargs:pytest.fail('shadow decision must be skipped'))
    import wallex_bot.atlas_liquidation as liquidation
    monkeypatch.setattr(liquidation,'liquidate_paper_positions',lambda *_args,**_kwargs:{
        'remaining_paper_positions':0,'paper_cash_tmn':0,'status':'NO_PAPER_POSITIONS'})
    try:
        result=atlas_watch.run(lake,hours=1,interval_seconds=60,top=1)
        assert result['cycles']==1
    finally:
        lake.close()
