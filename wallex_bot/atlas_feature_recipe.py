"""Stage 12 — independent research-only feature recipe comparison on genuine candles.

Never modifies atlas_signals.features, a checkpoint, the RiskGate, or an archive.
This is NOT inference, model calibration, evidence of profitability or authorization.
"""
from __future__ import annotations

import hashlib
import math
from pathlib import Path

import numpy as np
import pandas as pd

from .atlas_signals import features
from .atlas_deep import COLS
from .atlas_feature_health import (
    _read_catalog_symbols, _verified_segments, _last_quote_epoch,
)
from .atlas_operational import _read_connection

POLICY = 'EXPERIMENTAL_CHALLENGER_FEATURE_RECIPE_V2_ZERO_DENOMINATOR_CONVENTIONS'
CONTEXT = 96
MIN_BARS = CONTEXT + 55


def _isfinite(values):
    return np.isfinite(values.to_numpy(dtype=float))


def _replace_if_defined(original, candidate, mask, *, name, observations):
    """Replace only undefined V1 indicator rows with a declared arithmetic limit.

    Raw OHLCV measurements are never altered. Warm-up missingness is preserved.
    """
    before = original[name]
    replace = (~_isfinite(before)) & mask.fillna(False).to_numpy(dtype=bool) & _isfinite(candidate)
    if replace.any():
        original.loc[replace,name] = candidate.loc[replace].to_numpy(dtype=float)
    observations[name] = int(replace.sum())


def challenger_features(frame):
    """Return independent V2 research features and per-column repair evidence.

    Definitions are explicitly experimental and must be retrained/evaluated before
    use. Index and rows are not added; missing candles are never reconstructed.
    """
    v1 = features(frame)
    v2 = v1[COLS].copy(deep=True)
    counts = {name:0 for name in ('rsi14','mfi14','obv_slope','stoch_k','bb_z','volume_ratio')}
    if frame.empty:
        return v1[COLS].copy(),v2,counts
    c=frame.close.astype(float);h=frame.high.astype(float)
    l=frame.low.astype(float);v=frame.volume.astype(float)
    d=c.diff();up=d.clip(lower=0);down=(-d).clip(lower=0)
    up14=up.rolling(14,min_periods=14).mean()
    down14=down.rolling(14,min_periods=14).mean()
    rsi_zero_den=down14.eq(0)&up14.notna()
    rsi_candidate=pd.Series(np.where(up14.gt(0),100.0,50.0),index=frame.index)
    _replace_if_defined(v2,rsi_candidate,rsi_zero_den,name='rsi14',observations=counts)

    tp=(h+l+c)/3
    mf=tp*v
    pos=mf.where(tp>tp.shift(),0).rolling(14,min_periods=14).sum()
    neg=mf.where(tp<tp.shift(),0).rolling(14,min_periods=14).sum()
    mf_undefined=neg.eq(0)&pos.notna()
    mfi_candidate=pd.Series(np.where(pos.gt(0),100.0,50.0),index=frame.index)
    _replace_if_defined(v2,mfi_candidate,mf_undefined,name='mfi14',observations=counts)

    hh=h.rolling(14,min_periods=14).max();ll=l.rolling(14,min_periods=14).min()
    flat_range=hh.eq(ll)&c.eq(hh)&c.eq(ll)&hh.notna()
    neutral_stoch=pd.Series(50.0,index=frame.index)
    _replace_if_defined(v2,neutral_stoch,flat_range,name='stoch_k',observations=counts)

    mid=c.rolling(20,min_periods=20).mean()
    std=c.rolling(20,min_periods=20).std()
    flat_bollinger=std.eq(0)&mid.eq(c)&mid.notna()
    zero=pd.Series(0.0,index=frame.index)
    _replace_if_defined(v2,zero,flat_bollinger,name='bb_z',observations=counts)

    rolling_v=v.rolling(20,min_periods=20).mean()
    vol_zero=rolling_v.eq(0)&v.eq(0)&rolling_v.notna()
    _replace_if_defined(v2,zero,vol_zero,name='volume_ratio',observations=counts)

    obv=(np.sign(d).fillna(0)*v).cumsum()
    total_v=v.rolling(12,min_periods=12).sum()
    obv_zero=total_v.eq(0)&obv.diff(12).eq(0)&total_v.notna()
    _replace_if_defined(v2,zero,obv_zero,name='obv_slope',observations=counts)
    return v1[COLS].copy(),v2,counts


def _whole_window_valid(matrix,context=CONTEXT,min_bars=MIN_BARS):
    """Count inference-eligible historical endings without future information.

    A window at index t reads only rows t-context+1 through t.
    """
    if len(matrix)<min_bars:return 0
    ok=np.isfinite(matrix.to_numpy(dtype=np.float64)).all(axis=1).astype(np.int64)
    rolling=np.convolve(ok,np.ones(context,dtype=np.int64),'valid')
    # rolling end index is (context-1)+k; min_bars-1 also required
    return int((rolling[min_bars-context:] == context).sum())


def diagnose_segment(segment, quote_epoch=None, period=900):
    """Pure research comparison; supplied segment must be genuine contiguous OHLCV."""
    if segment is None or segment.empty:
        return {'status':'NO_GENUINE_CANDLES'}
    stamps=segment.timestamp.to_numpy(dtype=np.int64)
    if np.any(np.diff(stamps)!=period) or np.any(stamps%period):
        raise ValueError('NONCONTIGUOUS_OR_OFFGRID_REAL_CANDLES')
    if quote_epoch is not None:
        if not math.isfinite(float(quote_epoch)):
            raise ValueError('INVALID_OBSERVED_QUOTE_TIME')
        segment=segment.loc[segment.timestamp+period<=float(quote_epoch)].copy().reset_index(drop=True)
        if segment.empty:return {'status':'NO_CLOSED_GENUINE_CANDLES'}
    v1,v2,replacements=challenger_features(segment)
    before={name:int((~_isfinite(v1[name].tail(CONTEXT))).sum()) for name in COLS}
    after={name:int((~_isfinite(v2[name].tail(CONTEXT))).sum()) for name in COLS}
    v1_count=_whole_window_valid(v1)
    v2_count=_whole_window_valid(v2)
    if v2_count<v1_count:raise RuntimeError('EXPERIMENTAL_RECIPE_UNEXPECTEDLY_DESTROYED_VALID_WINDOWS')
    eligible_now=len(segment)>=MIN_BARS
    return {
        'status':'RESEARCH_COUNTERFACTUAL_ONLY',
        'genuine_closed_bars':int(len(segment)),
        'latest_candle_close_epoch':int(segment.timestamp.iloc[-1])+period,
        'last_recorded_quote_epoch':float(quote_epoch) if quote_epoch is not None else None,
        'v1_existing_champion_latest_window_eligible':bool(eligible_now and all(not n for n in before.values())),
        'v2_research_only_latest_window_eligible':bool(eligible_now and all(not n for n in after.values())),
        'v1_latest_window_invalid_counts':{key:n for key,n in before.items() if n},
        'v2_latest_window_invalid_counts':{key:n for key,n in after.items() if n},
        'v2_explicitly_resolved_rows_entire_contiguous_segment':{key:n for key,n in replacements.items() if n},
        'v1_eligible_historical_window_endings':v1_count,
        'v2_research_eligible_historical_window_endings':v2_count,
        'additional_research_only_window_endings':v2_count-v1_count,
        'raw_ohlcv_unchanged':True,
        'existing_champion_policy_unchanged':True,
    }


def feature_recipe_report(root,resolution='15',top=8,symbol=None):
    if resolution!='15':raise ValueError('Only native 15m champion resolution can be audited')
    if not isinstance(top,int) or not 1<=top<=24:raise ValueError('top must be 1..24')
    if symbol is not None and (not isinstance(symbol,str) or not symbol.isalnum() or not symbol.isupper()):
        raise ValueError('invalid symbol')
    root=Path(root).resolve()
    db=_read_connection(root/'catalog.sqlite')
    base={'mode':'READ_ONLY_EXPERIMENTAL_FEATURE_RECIPE_COMPARISON',
          'recipe_id':POLICY,
          'recipe_source_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
          'no_network_no_orders_no_db_writes':True,
          'champion_riskgate_watch_unchanged':True,
          'recipe_requires_separate_training_and_future_validation':True,
          'neutral_zero_denominator_conventions_are_research_choices_not_unique_truth':True,
          'note':'Only arithmetic zero-denominator ambiguities are addressed; gap/warmup/nonfinite prices stay invalid.'}
    if db is None:return {**base,'status':'NO_EXISTING_ARCHIVE','symbols':[]}
    try:
        names=_read_catalog_symbols(db,top,symbol)
        items=[]
        for name in names:
            try:
                segments,chunks=_verified_segments(root,db,name,resolution)
                if not segments:
                    detail={'status':'NO_VERIFIED_GENUINE_CANDLES'}
                else:
                    quote_epoch=_last_quote_epoch(root,name)
                    if quote_epoch is not None:
                        candidates=[s for s in segments if (s.timestamp+900<=quote_epoch).any()]
                        segment=candidates[-1] if candidates else None
                    else:segment=segments[-1]
                    detail=diagnose_segment(segment,quote_epoch)
                items.append({'symbol':name,'sha256_verified_source_chunks':chunks,
                              'verified_source':True,**detail})
            except (ValueError,KeyError,TypeError,RuntimeError,OSError,OverflowError) as exc:
                items.append({'symbol':name,'status':'FAIL_CLOSED_INPUT','error_type':type(exc).__name__,
                              'verified_source':False})
        return {**base,'status':'READ_ONLY','symbols':items}
    finally:db.close()
