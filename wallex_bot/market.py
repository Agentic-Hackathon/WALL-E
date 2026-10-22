"""Wallex public data with strict timeframe validation and explicit resampling."""
from __future__ import annotations
import time
import requests
import numpy as np
import pandas as pd

HOST = 'https://api.wallex.ir'
ALLOWED_RESOLUTIONS = {'1':60,'15':900,'60':3600,'240':14400,'480':28800,'720':43200,'1D':86400,'2D':172800,'3D':259200}

class MarketDataError(RuntimeError):
    pass

def _get(path: str, params: dict | None = None) -> dict:
    response = requests.get(HOST + path, params=params, timeout=(5, 20))
    response.raise_for_status()
    obj = response.json()
    if not isinstance(obj, dict):
        raise MarketDataError(f'unexpected response type: {type(obj).__name__}')
    if obj.get('success') is False or obj.get('s') in ('error', 'no_data'):
        raise MarketDataError(f'API error/no data: {str(obj)[:200]}')
    return obj

def markets():
    return _get('/hector/web/v1/markets')['result']['markets']

def depth(symbol: str) -> dict:
    return _get('/v1/depth', {'symbol':symbol})['result']

def interval_report(df:pd.DataFrame, resolution:str|None=None)->dict:
    if len(df)<3:raise MarketDataError('Need at least 3 candles for frequency audit')
    t=np.sort(pd.to_numeric(df['timestamp'],errors='raise').to_numpy(dtype='int64'))
    d=np.diff(t)
    pos=d[d>0]
    if not len(pos):raise MarketDataError('No increasing timestamps')
    mode=int(pd.Series(pos).mode().iloc[0])
    expected=ALLOWED_RESOLUTIONS.get(resolution) if resolution else None
    return {'rows':len(df),'first_ts':int(t[0]),'last_ts':int(t[-1]),
            'modal_spacing_seconds':mode,'min_spacing_seconds':int(pos.min()),
            'median_spacing_seconds':float(np.median(pos)),
            'max_spacing_seconds':int(pos.max()),
            'gaps_vs_expected':int(np.sum(np.maximum(0,(pos//expected)-1))) if expected else None,
            'expected_spacing_seconds':expected,
            'has_finer_than_requested':bool(expected and np.any(pos<expected)),
            'has_wrong_interval':bool(expected and np.any(pos!=expected))}

def require_resolution(df:pd.DataFrame,resolution:str)->dict:
    audit=interval_report(df,resolution)
    if audit['has_wrong_interval']:
        raise MarketDataError(f'Requested resolution {resolution} ({audit["expected_spacing_seconds"]}s) '
              f'but data has spacing {audit["modal_spacing_seconds"]}s / max {audit["max_spacing_seconds"]}s. '
              'DO NOT backtest mislabelled or discontinuous candles. Check source interval and gaps; '
              'resample explicitly only after confirming the actual source period.')
    return audit

def resample_candles(df:pd.DataFrame,source_resolution:str,target_resolution:str)->pd.DataFrame:
    """Epoch-aligned OHLCV resample, dropping incomplete buckets rather than inventing candles."""
    if source_resolution not in ALLOWED_RESOLUTIONS or target_resolution not in ALLOWED_RESOLUTIONS:
        raise ValueError('Unknown resolution')
    src=ALLOWED_RESOLUTIONS[source_resolution];dst=ALLOWED_RESOLUTIONS[target_resolution]
    if dst <= src or dst%src: raise ValueError('Target must be integer multiple of source resolution')
    frame=normalize(df)
    # A targeted repair response can legitimately hold just 1 or 2 REAL observations.
    # Never demand >=3 rows to check a SOURCE grid; missing source bars are allowed,
    # but incomplete target buckets below are dropped, never filled.
    stamps=frame.timestamp.to_numpy(dtype='int64')
    if np.any(stamps % src):
        raise MarketDataError('Actual source timestamps are off the source grid')
    diffs=np.diff(stamps)
    if np.any(diffs < src) or np.any(diffs % src):
        raise MarketDataError('Source timestamps do not match the requested source grid')
    frame=frame.copy()
    frame['bucket']=(frame.timestamp//dst)*dst
    required_count=dst//src
    aggregated=[]
    for stamp,g in frame.groupby('bucket',sort=True):
        expected=np.arange(int(stamp),int(stamp+dst),src,dtype='int64')
        if len(g)!=required_count or not np.array_equal(g.timestamp.to_numpy(),expected):
            continue  # an incomplete bucket cannot be honestly used for model training
        aggregated.append({'timestamp':int(stamp),'open':float(g.open.iloc[0]),
               'high':float(g.high.max()),'low':float(g.low.min()),
               'close':float(g.close.iloc[-1]),'volume':float(g.volume.sum())})
    if not aggregated: raise MarketDataError('No complete resample buckets; inspect timestamps')
    return normalize(pd.DataFrame(aggregated))

def candles(symbol: str,resolution:str,begin:int,end:int,resample_from:str|None=None)->pd.DataFrame:
    if resolution not in ALLOWED_RESOLUTIONS:raise ValueError('Invalid Wallex candle resolution')
    if not symbol.isalnum() or symbol.upper()!=symbol:raise ValueError('Invalid symbol')
    if end<=begin:raise ValueError('End must be later than start')
    # Wallex can silently answer resolution=15 with 1-minute bars. When
    # callers request an explicit finer source, ask for THAT source rather
    # than relying on server-side fallback behaviour.
    source_period=ALLOWED_RESOLUTIONS[resample_from] if resample_from else None
    query_resolution=(resample_from if source_period and source_period<ALLOWED_RESOLUTIONS[resolution]
                      else resolution)
    obj=_get('/v1/udf/history',{'symbol':symbol,'resolution':query_resolution,
                                'from':int(begin),'to':int(end)})
    required=('t','o','h','l','c','v')
    if any(k not in obj for k in required):raise MarketDataError('Missing UDF arrays: '+str(list(obj)))
    if len(set(len(obj[k]) for k in required))!=1:raise MarketDataError('Mismatched candle array lengths')
    frame=pd.DataFrame({'timestamp':obj['t'],'open':obj['o'],'high':obj['h'],
                        'low':obj['l'],'close':obj['c'],'volume':obj['v']})
    if frame.empty:raise MarketDataError('Empty candle history')
    frame=normalize(frame)
    frame=frame[(frame.timestamp>=begin)&(frame.timestamp<=end)].reset_index(drop=True)
    if frame.empty:raise MarketDataError('All timestamps outside requested window')
    if resample_from and ALLOWED_RESOLUTIONS[resample_from]<ALLOWED_RESOLUTIONS[resolution]:
        from_seconds=ALLOWED_RESOLUTIONS[resample_from]
        # We explicitly queried a finer source. Treat returned rows as that
        # source, even for 1/2 observations; otherwise the API's reported
        # '15m' could be a single aligned one-minute candle (unsafe).
        frame=resample_candles(frame,resample_from,resolution)
    else:
        # Targeted one- or two-bar intervals can be valid, and alignment is
        # independently checked by the chunk grid in research_data._valid_slice.
        if len(frame)>=3:
            require_resolution(frame,resolution)
        elif len(frame)==2:
            delta=int(frame.timestamp.iloc[1]-frame.timestamp.iloc[0])
            if delta % ALLOWED_RESOLUTIONS[resolution] or delta < ALLOWED_RESOLUTIONS[resolution]:
                raise MarketDataError('Two-bar interval inconsistent with timeframe')
        if (frame.timestamp.to_numpy(dtype='int64') % ALLOWED_RESOLUTIONS[resolution]).any():
            raise MarketDataError('Off-grid target timestamps')
    return frame

def candles_sparse(symbol: str, resolution: str, begin: int, end: int) -> pd.DataFrame:
    """Read genuine UDF candles while preserving provider gaps.

    This is for RESEARCH ARCHIVING ONLY: the result is not guaranteed continuous.
    The archive must validate/segment it before model training. Does not fill,
    forward-fill, interpolate, or invent any observation.
    """
    if resolution not in ALLOWED_RESOLUTIONS:
        raise ValueError('Unsupported Wallex UDF timeframe')
    if not isinstance(symbol, str) or not symbol.isalnum() or symbol != symbol.upper():
        raise ValueError('Invalid market symbol')
    if end <= begin:
        raise ValueError('Invalid request window')
    obj = _get('/v1/udf/history', {'symbol':symbol,'resolution':resolution,
                                  'from':int(begin),'to':int(end)})
    names=('t','o','h','l','c','v')
    if not all(isinstance(obj.get(k),list) for k in names):
        raise MarketDataError('Incomplete real UDF array set')
    if len({len(obj[k]) for k in names}) != 1 or not obj['t']:
        raise MarketDataError('Empty/mismatched real UDF arrays')
    data=pd.DataFrame({'timestamp':obj['t'],'open':obj['o'],'high':obj['h'],
                       'low':obj['l'],'close':obj['c'],'volume':obj['v']})
    data['timestamp']=pd.to_numeric(data['timestamp'],errors='raise').astype('int64')
    # No ambiguous duplicate timestamps with different prices/volume can be accepted.
    if data.timestamp.duplicated().any():
        dup=data[data.timestamp.duplicated(keep=False)]
        if dup.groupby('timestamp',sort=False)[['open','high','low','close','volume']].nunique().max().max()>1:
            raise MarketDataError('Conflicting exchange records at a shared candle timestamp')
    data=normalize(data)
    seconds=ALLOWED_RESOLUTIONS[resolution]
    # Only full, already-closed candles. No public API future value is assumed.
    upper=min(end,int(time.time()))
    data=data[(data.timestamp>=begin)&(data.timestamp<end)&(data.timestamp+seconds<=upper)].reset_index(drop=True)
    if data.empty:
        raise MarketDataError('No genuinely observed closed candles in requested interval')
    stamps=data.timestamp.to_numpy(dtype='int64')
    if (stamps % seconds).any():
        raise MarketDataError('Response does not match native resolution grid (possible UDF fallback)')
    diff=np.diff(stamps)
    if np.any(diff<=0) or np.any(diff % seconds):
        raise MarketDataError('Source observations are not on the genuine timeframe grid')
    # Crucially: diffs > seconds are OBSERVED MISSING PERIODS, not invented prices.
    return data


def normalize(df:pd.DataFrame)->pd.DataFrame:
    df=df[['timestamp','open','high','low','close','volume']].copy()
    df['timestamp']=pd.to_numeric(df['timestamp'],errors='raise').astype('int64')
    for col in ('open','high','low','close','volume'):
        df[col]=pd.to_numeric(df[col],errors='raise').astype(float)
    df=df.sort_values('timestamp').drop_duplicates('timestamp',keep='last').reset_index(drop=True)
    if df[['open','high','low','close']].le(0).any().any():raise MarketDataError('Non-positive OHLC price')
    if df['volume'].lt(0).any() or df.isna().any().any():raise MarketDataError('Invalid/missing candle')
    if ((df['high']<df[['open','close','low']].max(axis=1))|
        (df['low']>df[['open','close','high']].min(axis=1))).any():
        raise MarketDataError('Invalid OHLC bounds')
    return df

def complete_only(df:pd.DataFrame,resolution:str,now:float|None=None)->pd.DataFrame:
    now=time.time() if now is None else now
    return df[df.timestamp+ALLOWED_RESOLUTIONS[resolution]<=now].copy().reset_index(drop=True)
