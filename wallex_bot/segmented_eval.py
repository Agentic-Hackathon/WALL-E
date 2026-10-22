"""Genuine Wallex segment-to-segment OOS evaluation, never across missing OHLCV.

Train on a fully continuous EARLIER real segment. Apply the fixed model to
LATER real segment only. All feature history for test is within that segment.
Gaps are never imputed, bridged, or counted as holding-period observations.
"""
from __future__ import annotations
import hashlib
import json
import time
import shutil
from pathlib import Path

import joblib
import pandas as pd

from . import market
from .learning import train_cutoff
from .simulator import backtest, export_result
from .strategy import Parameters


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_catalog_segments(catalog_path: str, symbol: str, resolution: str,
                          max_staleness_hours: int = 8):
    cat = json.loads(Path(catalog_path).read_text(encoding='utf-8'))
    if cat.get('source') != 'wallex_public_api' or cat.get('symbol') != symbol or cat.get('resolution') != resolution:
        raise RuntimeError('Segment catalog Wallex source/symbol/resolution mismatch')
    period = market.ALLOWED_RESOLUTIONS[resolution]
    records = []
    base = Path(catalog_path).resolve().parent
    for entry in cat.get('segments', []):
        path = Path(entry['file'])
        if not path.is_absolute(): path = base/path
        if not path.is_file() or digest(path) != entry['sha256']:
            raise RuntimeError(f'Segment missing or checksum altered: {path}')
        proof_path = Path(entry['provenance_file'])
        if not proof_path.is_absolute(): proof_path = base/proof_path
        proof = json.loads(proof_path.read_text(encoding='utf-8'))
        if (proof.get('source') != 'wallex_public_api' or proof.get('symbol') != symbol or
            proof.get('resolution') != resolution or proof.get('sha256') != entry['sha256'] or
            proof.get('segment_status') != 'strictly_continuous_genuine_observations'):
            raise RuntimeError(f'Segment provenance invalid: {path}')
        df = pd.read_csv(path)
        df = market.normalize(df)
        if len(df) != entry['rows'] or df.empty:
            raise RuntimeError(f'Invalid segment row count: {path}')
        if len(df) >= 3:
            market.require_resolution(df,resolution)
        elif len(df) == 2 and int(df.timestamp.iloc[1] - df.timestamp.iloc[0]) != period:
            raise RuntimeError('Two-row segment not truly contiguous')
        if int(df.timestamp.iloc[0]) != entry['start'] or int(df.timestamp.iloc[-1]) + period != entry['end_exclusive']:
            raise RuntimeError(f'Wrong segment time boundaries: {path}')
        if (df.timestamp.to_numpy(dtype='int64') % period != 0).any():
            raise RuntimeError('Segment not aligned to target candle grid')
        resolved_entry = dict(entry)
        resolved_entry['_resolved_file'] = str(path.resolve())
        records.append((resolved_entry, df))
    records.sort(key=lambda z: z[0]['start'])
    for prev, later in zip(records,records[1:]):
        if later[0]['start'] < prev[0]['end_exclusive']:
            raise RuntimeError('Overlapping segments - invalid provenance catalog')
    if not records:
        raise RuntimeError('No genuine segment found')
    now = int(time.time())
    latest = records[-1][0]['end_exclusive']
    if latest > now + period or now - latest > max_staleness_hours*3600:
        raise RuntimeError(f'Latest segment is stale or future-dated (age={(now-latest)/3600:.1f}h). '
                           'Fetch more real observations with a NEW recent window.')
    return cat, records


def evaluate_segments(catalog_path: str, symbol: str, resolution: str,
                      hours: int, folder: str, fee: float, slippage: float,
                      initial_cash: float = 5_000_000, horizon: int = 3,
                      min_notional: float = 0):
    cat, records = load_catalog_segments(catalog_path, symbol, resolution)
    period = market.ALLOWED_RESOLUTIONS[resolution]
    if hours <= 0 or (hours*3600) % period:
        raise ValueError('Hours must align with timeframe')
    test_bars = hours*3600 // period
    # Select newest sufficiently long genuine segment, NOT a stitched time series.
    test_candidates = [(i,e,df) for i,(e,df) in enumerate(records)
                       if len(df) >= test_bars + 42]
    if not test_candidates:
        actual=max(len(df) for _,df in records)
        raise RuntimeError(f'No single real contiguous segment has {test_bars}+42 candles '
                           f'(largest available={actual}). Reduce --hours or collect newer real data; never fill holes.')
    # Prefer newest contiguous segment ending at catalog end; do not cherry-pick older segments.
    last_idx, test_record, test_df = test_candidates[-1]
    if last_idx != len(records)-1:
        raise RuntimeError('Newest real-data segment too short; avoid cherry-picking earlier test periods. '
                           'Reduce --hours or fetch a newer window.')
    train_candidates = [(i,e,df) for i,(e,df) in enumerate(records[:last_idx])
                        if len(df)>=330 and e['end_exclusive'] <= test_record['start']]
    if not train_candidates:
        raise RuntimeError('No separate earlier real segment with >=330 continuous candles for training')
    _, train_record, train_df = train_candidates[-1]
    model, _, _ = train_cutoff(train_df,len(train_df),horizon)
    start_idx=len(test_df)-test_bars-1
    if start_idx < 40:
        raise RuntimeError('Insufficient genuine in-segment feature warmup before held-out test')
    out=Path(folder)
    if out.exists() and any(out.iterdir()):
        raise FileExistsError('Evaluation output directory must be new/empty')
    out.mkdir(parents=True,exist_ok=True)
    params=Parameters(fee_rate=fee,slippage_rate=slippage,horizon=horizon,min_trade_tmn=min_notional)
    metrics,trades,curve,_=backtest(test_df,params,out/'decisions.sqlite',
                                initial_cash=initial_cash,symbol=symbol,model=model,
                                start_index=start_idx,end_index=len(test_df)-1)
    export_result(out,metrics,trades,curve)
    model_path=out/'ai_model.joblib'
    joblib.dump(model,model_path)
    # Self-contained original market inputs make judge-machine replay portable.
    inputs=out/'inputs'
    inputs.mkdir(exist_ok=True)
    shutil.copyfile(train_record['_resolved_file'], inputs/'train.csv')
    shutil.copyfile(test_record['_resolved_file'], inputs/'test.csv')
    if digest(inputs/'train.csv') != train_record['sha256'] or digest(inputs/'test.csv') != test_record['sha256']:
        raise RuntimeError('Copied real-market audit inputs differ from source')
    manifest={'evaluation_mode':'separated_real_segments','source':'wallex_public_api',
              'symbol':symbol,'resolution':resolution,'evaluation_hours':hours,
              'training_segment_path':'inputs/train.csv',
              'training_segment_sha256':train_record['sha256'],
              'evaluation_dataset_path':'inputs/test.csv',
              'dataset_file_sha256':test_record['sha256'],
              'model_sha256':digest(model_path),
              'train_rows':len(train_df),'test_segment_rows':len(test_df),
              'gap_between_train_and_test_seconds':test_record['start']-train_record['end_exclusive'],
              'test_start_index':start_idx,'test_end_index':len(test_df)-1,
              'fee_rate_assumption':fee,'slippage_rate_assumption':slippage,
              'results':metrics,
              'caveat':('Training and evaluation are on separate genuinely observed continuous segments. '
                        'Gaps are excluded, never crossed. Executions are hypothetical; fees/slippage are assumptions. '
                        'Not an independently validated trading strategy or a 48/72-hour realized result.')}
    (out/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    return {'metrics':metrics,'train_rows':len(train_df),'test_segment_rows':len(test_df),
            'evaluated_hours':hours,'training_segment_end_utc':train_record['end_exclusive_utc'],
            'test_segment_start_utc':test_record['start_utc'],
            'documented_missing_bars':cat['missing_bars'],
            'gap_between_train_and_test_seconds':manifest['gap_between_train_and_test_seconds'],
            'evaluation_mode':manifest['evaluation_mode'],
            'note':manifest['caveat']}
