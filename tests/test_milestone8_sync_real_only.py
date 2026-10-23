"""Non-financial scheduling/lease controls; no generated market/news data."""
import time
from pathlib import Path
from types import SimpleNamespace
from wallex_bot.atlas_archive import Lake
from wallex_bot.atlas_news_pipeline import NewsStore
from wallex_bot.atlas_news_ingestion import harvest
from wallex_bot.atlas_intelligence_sync import IntelligenceSyncManager
from wallex_bot.atlas_intelligence import profile
import pytest

def test_news_shared_lease_blocks_second_fetch(tmp_path,monkeypatch):
    import wallex_bot.atlas_news_ingestion as module
    with NewsStore(tmp_path) as store:
        store.db.execute('CREATE TABLE news_sync_lease_v8(name TEXT PRIMARY KEY,owner TEXT,expires REAL)')
        store.db.execute("INSERT INTO news_sync_lease_v8 VALUES('public-news','non-financial-control',?)",(time.time()+300,));store.db.commit()
    def forbidden(*a,**k):raise AssertionError('No network call permitted in lease test')
    monkeypatch.setattr(module,'fetch_public',forbidden)
    result=harvest(SimpleNamespace(root=tmp_path),score_sentiment=False)
    assert result['status']=='NEWS_LEASE_HELD_NO_DUPLICATE_REQUEST' and result['source_runs']==[]

def test_news_cursor_persists_without_fabricated_articles(tmp_path,monkeypatch):
    import wallex_bot.atlas_news_ingestion as module
    calls=[]
    def metadata_only(*a,**kwargs):
        calls.append(kwargs);return {'status':'CONTROL_ONLY_NO_NEWS_OR_NETWORK','source_runs':[]}
    monkeypatch.setattr(module,'_harvest',metadata_only)
    lake=SimpleNamespace(root=tmp_path)
    assert harvest(lake,score_sentiment=False,min_interval_seconds=300)['status']=='CONTROL_ONLY_NO_NEWS_OR_NETWORK'
    assert harvest(lake,score_sentiment=False,min_interval_seconds=300)['status']=='NEWS_POLL_INTERVAL_CACHE_HIT'
    assert len(calls)==1 and calls[0]['score_sentiment'] is False
    with NewsStore(tmp_path) as store:
        assert store.db.execute('SELECT count(*) FROM news_documents').fetchone()[0]==0
        assert not store.db.execute('SELECT count(*) FROM news_sync_lease_v8').fetchone()[0]

def test_empty_sync_status_is_unknown_not_invented_observations(tmp_path):
    lake=Lake(tmp_path/'empty')
    try:
        report=IntelligenceSyncManager(lake).intelligence_status(tmp_path/'session',index_dir=tmp_path/'missing_index')
        assert report['sources']['ohlcv']['last_valid_observation'] is None
        assert report['sources']['order_books']['pending_work']=='FIRST_REAL_SNAPSHOT_REQUIRED'
        assert report['sources']['sentiment']['source_unavailable']=='FINBERT_CONTEST_LICENSE_NOT_AUTHORIZED'
        assert report['synthetic_gap_fill'] is False
    finally:lake.close()

def test_m8_profile_pins_separate_research_without_promotion():
    c=profile()
    assert c['research_profile']=='ATLAS_M8_AGENTIC_V1' and c['LIVE']=='HARD_DISABLED'
    assert c['automatic_promotion'] is False and c['shadow'] is False # disables legacy second execution
    assert c['intelligence']['pattern_decision_use'] is False and c['intelligence']['finbert_competition_decision_use'] is False
    assert c['intelligence']['terminal_exit_window_seconds']==3600


def test_real_native_and_derived_core_are_both_verified():
    root=Path(__file__).resolve().parents[1]/'atlas_store'
    if not (root/'catalog.sqlite').exists():pytest.skip('Authentic Wallex archive required')
    lake=Lake(root)
    try:
        if not lake.db.execute("SELECT 1 FROM chunks WHERE symbol='BTCTMN' AND resolution='1' AND status='COMPLETE' LIMIT 1").fetchone():
            pytest.skip('DATA_NOT_AVAILABLE: authentic native BTC chunks required')
        result=IntelligenceSyncManager(lake).core_preflight('BTCTMN')
        assert result.get('native_verified') is True and result.get('derived_verified') is True
        assert result['hash_verified_last_closed_at']<=time.time()
    finally:lake.close()


def test_actual_conflicting_parent_cannot_be_authorized_by_derived_data():
    root=Path(__file__).resolve().parents[1]/'atlas_store'
    if not (root/'catalog.sqlite').exists():pytest.skip('Authentic Wallex archive required')
    lake=Lake(root)
    try:
        result=IntelligenceSyncManager(lake).core_preflight('PEPETMN')
        if 'CONFLICTING_OBSERVED_CANDLES' not in result.get('reason',''):
            pytest.skip('Previously observed real parent conflict is not present in supplied archive')
        assert result['ready'] is False and result['native_verified'] is False
        assert result['reason'].startswith('NATIVE_PARENT_INVALID:')
    finally:lake.close()
