"""Causal levels and shifts checked on genuine existing Wallex candles."""
import math
from pathlib import Path
import pytest
from wallex_bot.atlas_archive import Lake
from wallex_bot.atlas_feature_health import _verified_segments
from wallex_bot.atlas_technical_evidence import compute,confirmed_swings,technical_evidence

@pytest.fixture(scope='module')
def actual():
    lake=Lake(Path(__file__).resolve().parents[1]/'atlas_store')
    try:
        parts,_=_verified_segments(lake.root,lake.db,'BTCTMN','15')
        if not parts:pytest.skip('DATA_NOT_AVAILABLE: authentic BTC 15m chunks required')
        yield lake,max(parts,key=len)
    finally:lake.close()

def test_ichimoku_display_shift_is_not_backdated(actual):
    frame=actual[1].iloc[:100];result=compute(frame);i=result['ichimoku']
    assert i['displayed_forward_at']==result['candle_close_at']+26*900
    old=frame.iloc[:-26];ten=(old.high.tail(9).max()+old.low.tail(9).min())/2;kij=(old.high.tail(26).max()+old.low.tail(26).min())/2
    assert i['cloud_at_current_a']==pytest.approx((ten+kij)/2)
    assert i['chikou_policy']=='NOT_BACKDATED_AS_HISTORICAL_FEATURE'

def test_swing_confirmation_never_uses_unclosed_right_neighbours(actual):
    f=actual[1].iloc[:100];swings=confirmed_swings(f)
    assert swings and all(p['confirmed_at']<=int(f.timestamp.iloc[-1])+900 for p in swings)
    assert all(p['confirmed_at']-p['pivot_open']==2700 for p in swings)

def test_fibonacci_uses_only_opposite_confirmed_pivots(actual):
    result=compute(actual[1]);fib=result['fibonacci']
    assert fib['version']=='CONFIRMED_SWING_FIBONACCI_V1'
    if fib['retracements'] is not None:
        low=min(p['price'] for p in fib['anchors']);high=max(p['price'] for p in fib['anchors'])
        assert fib['anchors'][0]['kind']!=fib['anchors'][1]['kind']
        assert all(low<=p<=high for p in fib['retracements'].values())
        assert all(a['confirmed_at']<=result['candle_close_at'] for a in fib['anchors'])

def test_prefix_technical_evidence_matches_direct_prefix(actual):
    lake,f=actual;end=len(f)-20;cutoff=int(f.timestamp.iloc[end])+900
    result=technical_evidence(lake,'BTCTMN',cutoff=cutoff,retrospective=True)
    prefix=compute(f.iloc[:end+1])
    assert result['fibonacci']==prefix['fibonacci'] and result['ichimoku']==prefix['ichimoku']
    assert result['supertrend_trailing_band_v1']==prefix['supertrend_trailing_band_v1']

def test_volume_profile_and_vwap_do_not_invent_trade_data(actual):
    r=compute(actual[1])
    assert r['volume_profile']['values'] is None and 'APPROXIMATION' in r['vwap']['status']
    assert r['champion_features_changed'] is False
    assert all(v is None or math.isfinite(v) for v in r['indicator_values'].values())

def test_ichimoku_missing_warmup_is_explicit(actual):
    result=compute(actual[1].iloc[:30])
    assert result['ichimoku']['senkou_b_computed_now'] is None
    assert result['ichimoku']['cloud_at_current_a'] is None
