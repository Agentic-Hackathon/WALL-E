"""Milestone 3 contracts; no synthetic market observations are constructed."""
from __future__ import annotations
import json
from pathlib import Path
import pytest
from wallex_bot.atlas_archive import Lake
from wallex_bot.atlas_data_sync import DataSyncManager
from wallex_bot.atlas_feature_registry import REGISTRY, RECIPE_VERSION, registry_payload, sync_requirements
from wallex_bot.atlas_feature_audit_v3 import build_reports

def test_registry_is_versioned_and_definitions_are_complete():
    payload=registry_payload()
    assert payload['recipe_version']==RECIPE_VERSION and payload['feature_count']>=50
    assert {'trend','momentum','volatility','volume','price_action','microstructure','cross_asset'} <= {x.family for x in REGISTRY}
    assert all(x.warmup_bars>=1 and x.missing_policy.startswith('NaN') for x in REGISTRY)

def test_registry_demand_is_not_hidden_fixed_warmup():
    advanced=sync_requirements('advanced')
    assert set(advanced)=={'1','5','15','30','60','240','1D'}
    assert advanced['1D']['warmup_hours']>72 and advanced['15']['warmup_bars']==151
    with pytest.raises(ValueError):sync_requirements('unknown')

def test_empty_real_archive_feature_readiness_is_per_asset_fail_closed(tmp_path):
    lake=Lake(tmp_path/'lake')
    try:
        report=DataSyncManager(lake).feature_readiness('BTCTMN','watch_core',now=1_700_000_000)
        assert report['ready'] is False and report['timeframes'][0]['reason']=='MISSING_OR_UNVERIFIED_TIMEFRAME'
    finally:lake.close()

def test_absent_catalog_audit_writes_schema_not_market_data(tmp_path):
    root=tmp_path/'not_there';out=tmp_path/'reports'
    result=build_reports(root,out,top=1)
    assert result['status']=='NO_EXISTING_CATALOG'
    assert not root.exists()
    assert json.loads((out/'feature_registry.json').read_text())['feature_count']>=50
    assert (out/'feature_ablation.csv').is_file()

def test_execution_paths_do_not_import_research_recipe():
    root=Path('wallex_bot')
    for name in ('atlas_deep.py','atlas_risk.py','atlas_agent.py'):
        assert 'atlas_feature_registry' not in (root/name).read_text(encoding='utf8')
    assert 'allowed_symbols=eligible' in (root/'atlas_watch.py').read_text(encoding='utf8')

def test_watch_passes_only_ready_assets_to_existing_shadow_path(tmp_path,monkeypatch):
    """Orchestration metadata only; no candle, quote, or order-book fixture."""
    from wallex_bot import atlas_watch
    import wallex_bot.atlas_liquidation as liquidation
    lake=Lake(tmp_path/'lake');seen=[]
    class Sync:
        def __init__(self,_lake):pass
        def _priority_symbols(self,*_):return ['BTCTMN','ETHTMN']
        def feature_sync_plan(self,**_):return {'feature_requirements':{}}
        def run(self,**_):return {'status':'COMPLETED','complete':0,'failed':0,'plan':{'symbols':['BTCTMN','ETHTMN']},'derived_requested':[]}
        def feature_readiness(self,symbol,_profile):return {'symbol':symbol,'ready':symbol=='ETHTMN','reason':'TEST_METADATA'}
    class Context:
        def __init__(self,*_,**__):pass
        def record(self,*_,**__):return 'ok'
        def close(self):pass
    ticks=iter((0.,0.,3601.,3601.))
    monkeypatch.setattr(lake,'symbols',lambda _:['BTCTMN'])
    monkeypatch.setattr(atlas_watch,'DataSyncManager',Sync);monkeypatch.setattr(atlas_watch,'ContextStore',Context)
    monkeypatch.setattr(atlas_watch,'harvest_news',lambda *_a,**_k:{'fetched_articles_count_attempted':0})
    monkeypatch.setattr(atlas_watch,'make_packet',lambda *_a,**_k:{'task_skills':[],'pinned_start':{'tool_menu':[]}})
    monkeypatch.setattr(atlas_watch.time,'time',lambda:next(ticks));monkeypatch.setattr(atlas_watch.time,'monotonic',lambda:0.);monkeypatch.setattr(atlas_watch.time,'sleep',lambda _:None)
    monkeypatch.setattr(atlas_watch,'shadow_cycle',lambda *_a,**kw:seen.append(kw['allowed_symbols']) or {'events':[]})
    monkeypatch.setattr(liquidation,'liquidate_paper_positions',lambda *_a,**_k:{'remaining_paper_positions':0,'paper_cash_tmn':0,'status':'NO_PAPER_POSITIONS'})
    try:
        atlas_watch.run(lake,hours=1,interval_seconds=60,top=2)
        assert seen==[['ETHTMN']]
    finally:lake.close()
