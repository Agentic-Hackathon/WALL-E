"""Stage 11: read-only, real-archive-only PIT model feature health inspection.

This is a diagnostic view of EXISTING genuine Wallex candle chunks; it does not
fill undefined indicators, alter model features, place orders or fetch markets.
Only hashes verified against the persisted source catalog are read.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

from .atlas_deep import COLS
from .atlas_signals import features
from .atlas_operational import _read_connection, _table
from . import market


def _hexsha(path):
    h=hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda:stream.read(1<<20),b''):
            h.update(chunk)
    return h.hexdigest()


def _read_catalog_symbols(db, top, only_symbol=None):
    if not _table(db,'assets'):return []
    available=[]
    for (raw,) in db.execute('SELECT metadata FROM assets'):
        try:
            m=json.loads(raw)
            if m.get('is_spot') is not True or m.get('quote_asset')!='TMN':continue
            name=m.get('symbol')
            if not isinstance(name,str) or not name.isalnum() or not name.isupper():continue
            if only_symbol is not None and name!=only_symbol:continue
            volume=float(m.get('quote_volume_24h') or 0)
            if not math.isfinite(volume) or volume<0:volume=0
            available.append((volume,name))
        except (TypeError,ValueError,KeyError,OverflowError):continue
    # Identical ranking to current Shadow symbol selection: no return-based screening.
    return [name for _,name in sorted(available,reverse=True)[:top]]


def _verified_segments(root,db,symbol,resolution):
    period=market.ALLOWED_RESOLUTIONS.get(resolution)
    # M8: 5m/30m are valid LOCAL derived grids, not native API resolutions.
    # Reuse the same hash/conflict checks without changing the API adapter.
    if period is None and resolution in ('5','30'):
        from .atlas_archive import period_seconds
        period=period_seconds(resolution)
    if period is None:raise ValueError('Unsupported verified archive resolution')
    if not _table(db,'chunks'):return [],0
    files=db.execute('''SELECT filename,sha256 FROM chunks
           WHERE symbol=? AND resolution=? AND status='COMPLETE' ORDER BY begin''',
           (symbol,resolution)).fetchall()
    frames=[]
    for relative,digest in files:
        # Path traversal from untrusted manifest is never permitted.
        candidate=(Path(root)/relative).resolve()
        if not candidate.is_relative_to(Path(root).resolve()) or not candidate.is_file():
            raise ValueError('MISSING_OR_UNTRUSTED_ARCHIVE_CHUNK')
        if _hexsha(candidate)!=digest:raise ValueError('ARCHIVE_SHA256_MISMATCH')
        frame=pd.read_csv(candidate)
        frame=market.normalize(frame)
        if (frame.timestamp.to_numpy(dtype=np.int64)%period).any():
            raise ValueError('OFF_GRID_GENUINE_CANDLES')
        frames.append(frame)
    if not frames:return [],0
    data=pd.concat(frames,ignore_index=True)
    # Repeated archived source chunks can overlap, but conflicting facts cannot.
    repeated=data[data.timestamp.duplicated(keep=False)]
    if not repeated.empty and (repeated.groupby('timestamp')[['open','high','low','close','volume']]
                                .nunique().to_numpy()>1).any():
        raise ValueError('CONFLICTING_OBSERVED_CANDLES')
    data=data.drop_duplicates('timestamp').sort_values('timestamp').reset_index(drop=True)
    stamps=data.timestamp.to_numpy(dtype=np.int64)
    breaks=np.flatnonzero(np.diff(stamps)!=period)+1
    segments=[data.iloc[idx].reset_index(drop=True) for idx in np.split(np.arange(len(data)),breaks) if len(idx)]
    return segments,len(files)


def _last_quote_epoch(root,symbol):
    db=_read_connection(Path(root)/'forward_observations.sqlite')
    if db is None:return None
    try:
        if not _table(db,'quotes'):return None
        r=db.execute('SELECT MAX(observed_epoch) FROM quotes WHERE symbol=?',(symbol,)).fetchone()
        if not r or r[0] is None or not math.isfinite(float(r[0])):return None
        return float(r[0])
    finally:db.close()


def _known_denominator_conditions(frame,invalid_columns):
    """Diagnostic predicates on measured OHLCV; never manufacture a feature value."""
    if frame.empty:return []
    found=[]
    f=set(invalid_columns)
    close=frame.close.astype(float)
    high=frame.high.astype(float)
    low=frame.low.astype(float)
    volume=frame.volume.astype(float)
    if 'rsi14' in f and len(frame)>=15:
        down=(-close.diff()).clip(lower=0).rolling(14,min_periods=14).mean().iloc[-1]
        if pd.notna(down) and down==0:found.append('RSI14_ZERO_AVERAGE_DOWN_MOVE')
    if 'mfi14' in f and len(frame)>=15:
        tp=(high+low+close)/3
        neg=(tp*volume).where(tp<tp.shift(),0).rolling(14).sum().iloc[-1]
        if pd.notna(neg) and neg==0:found.append('MFI14_ZERO_NEGATIVE_MONEY_FLOW')
    if 'stoch_k' in f and len(frame)>=14:
        if high.tail(14).max()==low.tail(14).min():found.append('STOCH14_ZERO_OBSERVED_RANGE')
    if 'bb_z' in f and len(frame)>=20:
        if close.tail(20).std()==0:found.append('BOLLINGER20_ZERO_OBSERVED_STD')
    if 'volume_ratio' in f and len(frame)>=20:
        if volume.tail(20).sum()==0:found.append('VOLUME20_ZERO_RECORDED_VOLUME')
    if 'obv_slope' in f and len(frame)>=12:
        if volume.tail(12).sum()==0:found.append('OBV12_ZERO_RECORDED_VOLUME')
    if 'adx14' in f and len(frame)>=15:
        if high.tail(15).max()==low.tail(15).min():found.append('ADX14_NO_OBSERVED_RANGE')
    return sorted(set(found))


def diagnose_frame(frame,period,context=96,latest_quote_epoch=None):
    """A pure calculation on caller-supplied *actual* verified candles.

    Exposed for tests of missingness only, not used to invent candles.
    """
    if not isinstance(context,int) or context<1:raise ValueError('Invalid context')
    if frame.empty:return {'status':'NO_OBSERVED_CANDLES'}
    selected=frame
    if latest_quote_epoch is not None:
        # The timestamp identifies the *start*, never the close, of a candle.
        selected=frame.loc[frame.timestamp+period<=latest_quote_epoch]
        if selected.empty:
            return {'status':'NO_CLOSED_CANDLE_AT_LAST_RECORDED_QUOTE'}
    f=features(selected)
    values=f[COLS].tail(context)
    latest_bad=[col for col in COLS if not np.isfinite(float(values[col].iloc[-1]))]
    window_bad={col:int((~np.isfinite(values[col].to_numpy(dtype=float))).sum())
                for col in COLS if (~np.isfinite(values[col].to_numpy(dtype=float))).any()}
    start=int(selected.timestamp.iloc[-1]); close_epoch=start+int(period)
    end_age=((latest_quote_epoch-close_epoch)/60 if latest_quote_epoch is not None else None)
    enough=len(selected)>=context+55
    return {'status':('MODEL_INPUT_WINDOW_FINITE' if enough and len(values)==context and not window_bad
                      else 'INSUFFICIENT_CONTIGUOUS_CONTEXT' if not enough or len(values)<context
                      else 'MODEL_INPUT_WINDOW_NONFINITE'),
            'observed_contiguous_bars':len(selected),
            'required_bars_for_existing_predict_latest':context+55,
            'latest_candle_open_epoch':start,'latest_candle_close_epoch':close_epoch,
            'last_recorded_quote_epoch':latest_quote_epoch,
            'minutes_quote_after_last_closed_candle':round(end_age,6) if end_age is not None else None,
            'context_window':context,
            'invalid_columns_latest':latest_bad,
            'invalid_counts_in_context_window':window_bad,
            'recorded_denominator_conditions':_known_denominator_conditions(selected,latest_bad),
            'can_use_unchanged_champion':bool(enough and len(values)==context and not window_bad),
            'do_not_impute_unobserved_market_prices':True}


def feature_health_report(root,resolution='15',top=8,symbol=None):
    """Read-only against the existing Wallex Atlas catalog and saved quotes."""
    if resolution!='15':raise ValueError('Stage 11 only audits the champion 15-minute input protocol')
    if not isinstance(top,int) or not 1<=top<=24:raise ValueError('Top must be 1..24')
    if symbol is not None and (not isinstance(symbol,str) or not symbol.isalnum() or not symbol.isupper()):
        raise ValueError('Invalid symbol')
    root=Path(root).resolve()
    db=_read_connection(root/'catalog.sqlite')
    if db is None:return {'mode':'EXISTING_ARCHIVE_READ_ONLY_FEATURE_HEALTH','status':'NO_EXISTING_CATALOG',
                          'mutations':False,'network_requests':False,'orders':False}
    try:
        names=_read_catalog_symbols(db,top,symbol)
        output=[]
        for name in names:
            quote_epoch=_last_quote_epoch(root,name)
            try:
                segments,source_files=_verified_segments(root,db,name,resolution)
                if not segments:
                    result={'status':'NO_VERIFIED_15MIN_CANDLES'}
                else:
                    # Reconstruct exactly the last observed contiguous segment at
                    # the point-in-time of the latest genuinely recorded quote.
                    if quote_epoch is not None:
                        eligible=[s[s.timestamp+900<=quote_epoch] for s in segments]
                        eligible=[s for s in eligible if len(s)]
                        segment=eligible[-1] if eligible else None
                    else:segment=segments[-1]
                    result=(diagnose_frame(segment,900,latest_quote_epoch=quote_epoch)
                            if segment is not None else {'status':'NO_CLOSED_CANDLE_AT_LAST_RECORDED_QUOTE'})
                output.append({'symbol':name,'source_chunks_verified':source_files,
                               'source_sha256_verified':True,**result})
            except (ValueError,KeyError,TypeError,UnicodeError,RuntimeError,OSError,OverflowError) as exc:
                # Do not leak arbitrary filenames, price rows, payloads or raw errors.
                output.append({'symbol':name,'status':'FAIL_CLOSED_SOURCE_OR_FEATURE_ERROR',
                               'error_class':type(exc).__name__,'source_sha256_verified':False})
        return {'mode':'EXISTING_ARCHIVE_READ_ONLY_FEATURE_HEALTH',
                'status':'READ_ONLY','resolution':resolution,'symbols':output,
                'mutations':False,'network_requests':False,'orders':False,
                'warning':'This is a current historical snapshot, not a reconstruction of each old REJECTED event; missing indicator outputs remain blocked.',
                'candle_timestamp_semantics':'OPEN; full verified candle closes at timestamp+900 seconds',
                'model_feature_recipe_unchanged':True,'model_promotion':False}
    finally:db.close()
