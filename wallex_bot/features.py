"""Causal indicators: each row depends on its candle and earlier candles only."""
from __future__ import annotations
import numpy as np
import pandas as pd

COLUMNS = ['ret1','ret3','ret6','mom12','ema_spread','vol_12','vol_36',
           'volume_ratio','range_pct','close_location','rsi14','atr14']

def make_features(df: pd.DataFrame) -> pd.DataFrame:
    p = df.close.astype(float)
    r = np.log(p / p.shift(1))
    ema_f = p.ewm(span=8,adjust=False).mean()
    ema_s = p.ewm(span=21,adjust=False).mean()
    delta = p.diff()
    gain = delta.clip(lower=0).ewm(alpha=1/14,adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1/14,adjust=False).mean()
    rs = gain / loss.replace(0,np.nan)
    rsi = (100 - 100/(1+rs)).fillna(100)
    tr = pd.concat([df.high-df.low, (df.high-p.shift()).abs(),
                    (df.low-p.shift()).abs()], axis=1).max(axis=1)
    f = pd.DataFrame(index=df.index)
    f['ret1'] = r
    f['ret3'] = np.log(p/p.shift(3))
    f['ret6'] = np.log(p/p.shift(6))
    f['mom12'] = np.log(p/p.shift(12))
    f['ema_spread'] = ema_f/ema_s-1
    f['vol_12'] = r.rolling(12).std()
    f['vol_36'] = r.rolling(36).std()
    f['volume_ratio'] = df.volume / df.volume.rolling(24).mean().replace(0,np.nan)
    f['range_pct'] = (df.high-df.low)/p
    f['close_location'] = (p-df.low)/(df.high-df.low).replace(0,np.nan)
    f['rsi14'] = rsi/100
    f['atr14'] = tr.ewm(alpha=1/14,adjust=False).mean()/p
    return f.replace([np.inf,-np.inf], np.nan)

def future_label(df: pd.DataFrame, horizon: int) -> pd.Series:
    """At candle i CLOSE we observe features; enter next OPEN i+1;
    label exit at OPEN i+1+h (never at current close)."""
    start = df.open.shift(-1)
    finish = df.open.shift(-(horizon+1))
    return np.log(finish / start)
