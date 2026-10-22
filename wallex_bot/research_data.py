"""Fail-closed Wallex historical collection, targeted repair, and resumable chunks.

All prices are real exchange observations. Missing candles are NEVER imputed.
No account credentials or trading API calls are needed by this module.
"""
from __future__ import annotations
import hashlib
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import requests
from . import market


def date_utc(ts: int) -> str:
    return datetime.fromtimestamp(int(ts), timezone.utc).isoformat()


def _sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _atomic_json(path: Path, data: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.temporary')
    try:
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


class IncompleteMarketHistory(market.MarketDataError):
    """The market API did not supply all required *real* candles."""
    def __init__(self, begin: int, end: int, missing: list[int], detail: str = ''):
        self.begin, self.end, self.missing, self.detail = begin, end, missing, detail
        example = ', '.join(date_utc(x) for x in missing[:4])
        super().__init__(f'Incomplete chunk {date_utc(begin)} to {date_utc(end)}; '
                         f'missing={len(missing)}; first_missing_utc=[{example}]; {detail}')


def _valid_slice(frame: pd.DataFrame, begin: int, end: int, period: int) -> pd.DataFrame:
    """Check candle timestamps without assuming that short API responses are complete."""
    frame = market.normalize(frame)
    frame = frame[(frame.timestamp >= begin) & (frame.timestamp < end)].reset_index(drop=True)
    if not frame.empty and (frame.timestamp.to_numpy(dtype='int64') % period != 0).any():
        raise market.MarketDataError('Candles are not aligned to the target UTC grid')
    return frame


def _missing(begin: int, end: int, period: int, frame: pd.DataFrame) -> list[int]:
    expected = np.arange(begin, end, period, dtype='int64')
    return np.setdiff1d(expected, frame.timestamp.to_numpy(dtype='int64')).astype(int).tolist()


def _merge(frames: list[pd.DataFrame]) -> pd.DataFrame:
    if not frames:
        return pd.DataFrame(columns=['timestamp','open','high','low','close','volume'])
    return market.normalize(pd.concat(frames, ignore_index=True))


def _repair_chunk(symbol: str, resolution: str, begin: int, end: int,
                  resample_from: str | None, retries: int, pause_seconds: float,
                  *, max_repair_calls: int = 64, allow_incomplete: bool = False) -> pd.DataFrame:
    """Retry incomplete chunks, then query only missing candle intervals.

    A missing 15-minute bucket may have arisen from a partial 1-minute response.
    Small requests can recover it without rewriting any observed OHLC data.
    Persistent holes are explicitly reported instead of filled or skipped.
    """
    period = market.ALLOWED_RESOLUTIONS[resolution]
    reads = 0
    observations: list[pd.DataFrame] = []
    errors: list[str] = []

    def request(lo: int, hi: int, attempts: int) -> None:
        nonlocal reads
        for attempt in range(attempts + 1):
            if reads >= max_repair_calls:
                errors.append('repair request budget exceeded')
                return
            reads += 1
            try:
                frame = market.candles(symbol, resolution, lo, hi, resample_from=resample_from)
                observations.append(_valid_slice(frame, lo, hi, period))
                return
            except (market.MarketDataError, requests.RequestException) as exc:
                errors.append(f'{date_utc(lo)}..{date_utc(hi)} {type(exc).__name__}: {str(exc)[:140]}')
                if attempt < attempts and pause_seconds:
                    time.sleep(min(0.3 * (2**attempt), 2.0))

    request(begin, end, retries)
    seen = _merge(observations)
    holes = _missing(begin, end, period, seen)
    if not holes:
        return seen

    # Repair ONLY absent target candles; group adjacent holes, then subdivide
    # failed ranges until a single target bucket is reached.
    def repair(lo: int, hi: int, depth: int = 0):
        if depth > 16 or reads >= max_repair_calls:
            return
        existing = _merge(observations)
        if not _missing(lo, hi, period, existing):
            return
        request(lo, hi, 1 if hi-lo == period else 0)
        existing = _merge(observations)
        missing_here = _missing(lo, hi, period, existing)
        if not missing_here or hi-lo == period:
            return
        mid = lo + (((hi-lo)//period)//2)*period
        if lo < mid < hi:
            repair(lo, mid, depth+1)
            repair(mid, hi, depth+1)

    runs = []
    for stamp in holes:
        if runs and runs[-1][1] == stamp:
            runs[-1] = (runs[-1][0], stamp+period)
        else:
            runs.append((stamp,stamp+period))
    for lo, hi in runs:
        repair(lo,hi)
    result = _merge(observations)
    missing = _missing(begin,end,period,result)
    if missing and not allow_incomplete:
        raise IncompleteMarketHistory(begin,end,missing,
                 f'after {reads} public API reads; last_error={errors[-1] if errors else "none"}')
    return result


def _chunk_path(cache: Path, start: int, end: int) -> Path:
    return cache / f'chunk_{start}_{end}.csv'


def _load_cached(cache: Path, start: int, stop: int, period: int) -> pd.DataFrame | None:
    path = _chunk_path(cache,start,stop)
    meta_path = Path(str(path) + '.json')
    if not path.exists() or not meta_path.exists():
        return None
    meta = json.loads(meta_path.read_text(encoding='utf-8'))
    if meta.get('sha256') != _sha256(path) or meta.get('start') != start or meta.get('end') != stop:
        raise RuntimeError(f'Resume cache checksum/range mismatch: {path}')
    frame = _valid_slice(pd.read_csv(path),start,stop,period)
    if _missing(start,stop,period,frame):
        raise RuntimeError(f'Resume cache has missing data: {path}')
    return frame


def _save_cached(cache: Path, start: int, stop: int, frame: pd.DataFrame):
    cache.mkdir(parents=True, exist_ok=True)
    path = _chunk_path(cache,start,stop)
    temp = Path(str(path)+'.temporary')
    try:
        frame.to_csv(temp,index=False)
        digest = _sha256(temp)
        os.replace(temp,path)
        _atomic_json(Path(str(path)+'.json'),
                     {'start':start,'end':stop,'rows':len(frame),'sha256':digest})
    finally:
        temp.unlink(missing_ok=True)


def fetch_research_history(symbol: str, resolution: str, begin: int, end: int,
                           resample_from: str | None = '1', chunk_hours: int = 6,
                           retries: int = 2, pause_seconds: float = 0.10,
                           cache_dir: str | Path | None = None, allow_gaps: bool = False):
    """Collect a continuous real-data [begin,end) UTC history with checkpointed chunks.

    The output CSV/manifest are written only if EVERY required candle is present.
    If an API hole persists, successful chunks remain cached for a future retry.
    """
    if resolution not in market.ALLOWED_RESOLUTIONS:
        raise ValueError('Unknown requested resolution')
    period = market.ALLOWED_RESOLUTIONS[resolution]
    step = chunk_hours * 3600
    if not 1 <= chunk_hours <= 24 or step % period:
        raise ValueError('Chunk hours must be within [1,24] and a multiple of target timeframe')
    if begin % period or end % period or end <= begin:
        raise ValueError('UTC begin/end must align with timeframe and have end > begin')
    if end-begin > 90 * 86400:
        raise ValueError('Limit each download to at most 90 days')
    if resample_from and resample_from not in market.ALLOWED_RESOLUTIONS:
        raise ValueError('Unknown source resolution')
    if resample_from and market.ALLOWED_RESOLUTIONS[resample_from] > period:
        raise ValueError('Source resolution cannot be coarser than target')
    cache = Path(cache_dir) if cache_dir is not None else None
    if cache is not None:
        cache.mkdir(parents=True,exist_ok=True)
        state_file=cache/'state.json'
        expected_state={'symbol':symbol,'resolution':resolution,'begin':begin,'end':end,
                        'resample_from':resample_from,'chunk_hours':chunk_hours,'format_version':1}
        if state_file.exists():
            if json.loads(state_file.read_text(encoding='utf-8')) != expected_state:
                raise RuntimeError(f'Resume state differs from request: {state_file}; use a new output path')
        else:
            _atomic_json(state_file,expected_state)
    chunks = []
    frames = []
    for start in range(begin,end,step):
        stop = min(end,start+step)
        frame = _load_cached(cache,start,stop,period) if cache is not None else None
        if frame is None:
            try:
                frame = _repair_chunk(symbol,resolution,start,stop,resample_from,retries,pause_seconds,
                                      allow_incomplete=allow_gaps)
            except IncompleteMarketHistory as exc:
                if cache is not None:
                    _atomic_json(cache/'last_failure.json',
                        {'start':start,'end':stop,'missing':exc.missing,
                         'first_missing_utc':[date_utc(t) for t in exc.missing[:30]],
                         'reason':str(exc),'note':'No artificial bars created; valid chunks cached.'})
                raise RuntimeError(f'History download paused at {date_utc(start)}: {exc}. '
                         'Finished chunks remain cached; rerun the SAME fetch-history command.') from exc
            missing_here = _missing(start, stop, period, frame)
            if cache is not None and not missing_here:
                _save_cached(cache,start,stop,frame)
            if cache is not None and missing_here:
                # These are genuine returned observations, NOT a completed cache chunk.
                partial_path = cache/f'partial_{start}_{stop}.csv'
                temp = Path(str(partial_path)+'.temporary')
                frame.to_csv(temp,index=False)
                os.replace(temp,partial_path)
                _atomic_json(Path(str(partial_path)+'.json'),
                    {'source':'wallex_public_api','start':start,'end':stop,
                     'sha256':_sha256(partial_path),'missing':missing_here,
                     'note':'Incomplete; never a full-history cache hit'})
            print(f'{"PARTIAL" if missing_here else "Completed"} {date_utc(start)} → {date_utc(stop)} '
                  f'({len(frame)} genuine candles, {len(missing_here)} gaps)',file=sys.stderr)
            if pause_seconds:
                time.sleep(pause_seconds)
        else:
            print(f'Resumed {date_utc(start)} → {date_utc(stop)} ({len(frame)} cached candles)', file=sys.stderr)
        frames.append(frame)
        body = frame.to_csv(index=False,float_format='%.12g').encode('utf-8')
        chunks.append({'start':start,'end':stop,'rows':len(frame),
                       'sha256':hashlib.sha256(body).hexdigest(),
                       'missing':_missing(start,stop,period,frame)})
    combined = _merge(frames)
    grid = np.arange(begin,end,period,dtype='int64')
    if not allow_gaps:
        if not np.array_equal(combined.timestamp.to_numpy(dtype='int64'),grid):
            raise market.MarketDataError('Merged history incomplete; no final CSV was saved')
        market.require_resolution(combined,resolution)
    else:
        # Explicitly preserve missing intervals. NEVER validate this joined table as contiguous.
        if not combined.empty and (combined.timestamp.to_numpy(dtype='int64') % period != 0).any():
            raise market.MarketDataError('Misaligned timestamp in real observations')
    if cache is not None and not any(c['missing'] for c in chunks):
        (cache/'last_failure.json').unlink(missing_ok=True)
    return combined,chunks


def write_research_history(frame:pd.DataFrame, chunks:list[dict], output:str | Path,
                           symbol:str,resolution:str,begin:int,end:int,resample_from:str | None):
    out=Path(output)
    out.parent.mkdir(parents=True,exist_ok=True)
    tmp=out.with_name(out.name+'.temporary')
    try:
        frame.to_csv(tmp,index=False)
        data=tmp.read_bytes()
        digest=hashlib.sha256(data).hexdigest()
        metadata={'source':'wallex_public_api','symbol':symbol,'resolution':resolution,
                  'requested_start':begin,'requested_end':end,'begin_utc':date_utc(begin),
                  'end_exclusive_utc':date_utc(end),'resample_from':resample_from,
                  'sha256':digest,'frequency':market.interval_report(frame,resolution),
                  'chunks':chunks,'downloaded_at_utc':date_utc(int(time.time())),
                  'note':'Real public Wallex market data. No missing candles imputed.'}
        os.replace(tmp,out)
        _atomic_json(Path(str(out)+'.provenance.json'),metadata)
    finally:
        tmp.unlink(missing_ok=True)
    return {'rows':len(frame),'sha256':digest,'file':str(out),
            'provenance_file':str(out)+'.provenance.json',
            'start_utc':date_utc(begin),'end_exclusive_utc':date_utc(end),'chunks':len(chunks)}


def write_segmented_history(frame: pd.DataFrame, chunks: list[dict], output: str | Path,
                            symbol: str, resolution: str, begin: int, end: int,
                            resample_from: str | None):
    """Emit separate, SHA-pinned REAL and strictly continuous segments.

    No combined CSV is emitted: consumers must not treat missing time as contiguous.
    Manifest enumerates every missing bucket and all saved genuine observations.
    """
    out = Path(output)
    output_dir = Path(str(out) + '.segments')
    output_dir.mkdir(parents=True, exist_ok=True)
    period = market.ALLOWED_RESOLUTIONS[resolution]
    frame = market.normalize(frame)
    stamps = frame.timestamp.to_numpy(dtype='int64')
    if stamps.size and np.any(stamps % period):
        raise market.MarketDataError('Unaligned exchange timestamp; refusing segments')
    missing = _missing(begin, end, period, frame)
    split_points = [0]
    split_points.extend((np.flatnonzero(np.diff(stamps) != period) + 1).tolist())
    split_points.append(len(frame))
    segments = []
    for a, b in zip(split_points[:-1], split_points[1:]):
        if b <= a:
            continue
        part = frame.iloc[a:b].reset_index(drop=True)
        start = int(part.timestamp.iloc[0])
        end_excl = int(part.timestamp.iloc[-1]) + period
        name = f'segment_{start}_{end_excl}.csv'
        path = output_dir / name
        tmp = Path(str(path) + '.temporary')
        part.to_csv(tmp, index=False)
        os.replace(tmp, path)
        digest = _sha256(path)
        # If fewer than 3 samples, no statistical interval inference is possible.
        freq = market.interval_report(part, resolution) if len(part) >= 3 else {
            'rows':len(part),'expected_spacing_seconds':period,
            'timestamp_grid_checked':True,'interval_inference':'insufficient_rows'}
        proof = {'source':'wallex_public_api','symbol':symbol,'resolution':resolution,
                 'sha256':digest,'frequency':freq,'resample_from':resample_from,
                 'segment_status':'strictly_continuous_genuine_observations',
                 'segment_start':start,'segment_end_exclusive':end_excl,
                 'requested_start':begin,'requested_end':end,
                 'note':'No fabricated candles. Separate segment across each data gap.'}
        _atomic_json(Path(str(path)+'.provenance.json'),proof)
        segments.append({'file':str(path.relative_to(out.parent)),'provenance_file':str(Path(str(path)+'.provenance.json').relative_to(out.parent)),
                         'sha256':digest,'rows':len(part),'start':start,'end_exclusive':end_excl,
                         'start_utc':date_utc(start),'end_exclusive_utc':date_utc(end_excl)})
    catalog = {'source':'wallex_public_api','status':'INCOMPLETE_REAL_ONLY' if missing else 'COMPLETE_REAL_ONLY',
               'symbol':symbol,'resolution':resolution,'resample_from':resample_from,
               'requested_start':begin,'requested_end':end,
               'requested_start_utc':date_utc(begin),'requested_end_utc':date_utc(end),
               'observed_bars':len(frame),'expected_bars':(end-begin)//period,
               'missing_bars':len(missing),'missing_timestamps':missing,
               'missing_utc':[date_utc(t) for t in missing],
               'segments':segments,'chunk_records':chunks,
               'created_utc':date_utc(int(time.time())),
               'warning':'Not a continuous data set. Never use joined rows to bridge gaps. No invented candles.'}
    index_path = Path(str(out)+'.segments.json')
    _atomic_json(index_path,catalog)
    return {'status':catalog['status'],'index_file':str(index_path.resolve()),
            'observed_bars':catalog['observed_bars'],'missing_bars':len(missing),
            'segments':[{k:v for k,v in z.items() if k in ('file','rows','start_utc','end_exclusive_utc')}
                        for z in segments],
            'note':'Every segment is genuine and continuous; noncontiguous data never fed as one series.'}
