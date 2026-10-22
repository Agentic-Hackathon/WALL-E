"""Real Atlas archived candles; never manufacture OHLCV/prices/outcomes."""
import json,sqlite3,time
from pathlib import Path
import numpy as np
import pytest
from wallex_bot.atlas_archive import Lake
from wallex_bot.atlas_feature_health import _verified_segments
from wallex_bot.atlas_patterns import PatternIndex,representation,constrained_dtw,outcomes,make_query

ROOT=Path(__file__).resolve().parents[1]

@pytest.fixture(scope='module')
def genuine():
    if not (ROOT/'atlas_store/catalog.sqlite').exists():pytest.skip('Real Atlas archive not installed')
    lake=Lake(ROOT/'atlas_store')
    try:
        parts,_=_verified_segments(lake.root,lake.db,'BTCTMN','15')
        frame=max(parts,key=len)
        if len(frame)<64:pytest.skip('Insufficient real contiguous BTC history')
        yield lake,frame
    finally:lake.close()

@pytest.fixture(scope='module')
def index(genuine,tmp_path_factory):
    path=tmp_path_factory.mktemp('actual-pattern-index');idx=PatternIndex(path)
    try:
        idx.build(genuine[0],resolutions=('15',),max_windows_per_asset=100)
        yield idx
    finally:idx.close()

def historical_query(frame,end,length=10):
    from wallex_bot.atlas_forward import _sha
    window=frame.iloc[end-length+1:end+1];stamp=float(window.timestamp.iloc[-1])+900
    q={'symbol':'BTCTMN','resolution':'15','length':length,'start':int(window.timestamp.iloc[0]),
        'end':stamp,'decision_time':stamp,'available_at':time.time(),'representation':'relative_ohlcv',
        'representations':{k:representation(window,k).tolist() for k in ('relative_ohlcv','candle_structure')}}
    q['query_id']=_sha(q);return q

def test_normalization_is_relative_and_uses_window_only(genuine):
    f=genuine[1].iloc[:10];a=representation(f)
    assert a.shape==(10,5) and np.isfinite(a).all()
    assert a[0,3]==0
    expected=np.log(f.close.to_numpy()/f.close.iloc[0])/np.std(np.diff(np.log(f.close.to_numpy())),ddof=1)
    np.testing.assert_allclose(a[:,3],expected)

def test_constrained_dtw_identity_on_real_candles(genuine):
    a=representation(genuine[1].iloc[:10]);b=representation(genuine[1].iloc[1:11])
    assert constrained_dtw(a,a)==0
    assert constrained_dtw(a,b)==pytest.approx(constrained_dtw(b,a))

def test_no_outcome_from_incomplete_future(genuine):
    with pytest.raises(ValueError,match='OUTCOME'):outcomes(genuine[1].iloc[:10],8)

def test_index_hash_and_version_valid(index):
    assert index.verify_sources()
    m=index.manifest();assert m['version']=='ATLAS_ANALOGUES_V1' and m['rows_sha256'] and m['sources']

def test_current_query_has_actual_verification_availability(genuine):
    q=make_query(genuine[0],'BTCTMN')
    assert q['available_at']<=q['decision_time']<=time.time()
    assert q['end']<=q['decision_time']

def test_retrospective_does_not_claim_historical_receipts(genuine,index):
    q=historical_query(genuine[1],len(genuine[1])-1)
    with pytest.raises(ValueError,match='AVAILABLE'):index.search(q)
    result=index.search(q,retrospective=True)
    assert result['track']=='RETROSPECTIVE_CANDLE_RESEARCH_NOT_PROVEN_PIT'
    assert not result['decision_path_eligible'] and result['promotion'] is False

def test_cross_asset_search_and_deoverlap(genuine,index):
    q=historical_query(genuine[1],len(genuine[1])-1)
    a=index.search(q,retrospective=True,k=20,min_matches=2)
    assert a['eligible_candidates']>0 and a['matches']
    assert any(p['symbol']!='BTCTMN' for p in a['matches'])
    for p in a['matches']:assert p['outcome_end']<=q['start']-900
    for i,p in enumerate(a['matches']):
        for other in a['matches'][i+1:]:
            assert p['outcome_end']+900<=other['start'] or other['outcome_end']+900<=p['start']

@pytest.mark.parametrize('method',['euclidean','return_structure','dtw','historical_random'])
def test_pattern_results_reproduce(genuine,index,method):
    q=historical_query(genuine[1],len(genuine[1])-1)
    first=index.search(q,method=method,retrospective=True,min_matches=2)
    assert first==index.search(q,method=method,retrospective=True,min_matches=2)

def test_same_asset_and_history_filters(genuine,index):
    q=historical_query(genuine[1],len(genuine[1])-1)
    result=index.search(q,scope='same',history_end=q['start']-900,retrospective=True)
    assert all(p['symbol']=='BTCTMN' and p['outcome_end']<=q['start']-900 for p in result['matches'])

def test_unknown_liquidity_never_inferred_from_volume(genuine,index):
    q=historical_query(genuine[1],len(genuine[1])-1)
    result=index.search(q,liquidity_range=(1,2),retrospective=True)
    assert result['status']=='INSUFFICIENT_REAL_HISTORICAL_BOOK_LIQUIDITY' and result['empirical_quantiles'] is None

def test_five_minute_grid_uses_same_real_archive_verifier(genuine):
    lake=genuine[0];segments,_=_verified_segments(lake.root,lake.db,'PEPETMN','5')
    for p in segments:
        assert not (p.timestamp.astype('int64')%300).any()
        assert len(p)<2 or (np.diff(p.timestamp)==300).all()

def test_payload_tampering_detected_without_inventing_market(tmp_path,index):
    destination=sqlite3.connect(tmp_path/'patterns.sqlite');index.db.backup(destination);destination.close()
    copied=PatternIndex(tmp_path)
    try:
        with copied.db:copied.db.execute("UPDATE patterns SET sha256=? WHERE id=(SELECT id FROM patterns LIMIT 1)",('0'*64,))
        with pytest.raises(ValueError,match='ROWS_CHANGED'):copied.verify_sources()
    finally:copied.close()

def test_future_clock_not_allowed(genuine):
    with pytest.raises(ValueError,match='FUTURE'):make_query(genuine[0],'BTCTMN',decision_time=time.time()+3600)

def test_actual_prefix_does_not_change_retrieval(genuine,index):
    frame=genuine[1];end=len(frame)-20
    from_full=historical_query(frame,end);from_prefix=historical_query(frame.iloc[:end+1],end)
    assert from_full['representations']==from_prefix['representations']
    a=index.search(from_full,retrospective=True);b=index.search(from_prefix,retrospective=True)
    assert a['matches']==b['matches'] and a['empirical_quantiles']==b['empirical_quantiles']

def test_multiscale_never_uses_incomplete_long_bucket(genuine,index):
    from wallex_bot.atlas_pattern_research import multiscale_evidence
    stamp=time.time();result=multiscale_evidence(genuine[0],index,'BTCTMN',cutoff=stamp)
    assert result['decision_path_eligible'] is False
    for res,p in result['timeframes'].items():
        if 'closed_bucket_end' in p:
            assert p['closed_bucket_end']<=stamp
            assert p['horizon_seconds']['3']==3*{'1':60,'5':300,'15':900,'60':3600,'240':14400}[res]
