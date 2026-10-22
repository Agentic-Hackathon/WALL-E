"""Evidence-only diagnostic report for genuine Wallex replay runs.

No new trades, no fabricated prices, no retraining, no altered backtest logic.
Uses only original, hash-checked, archived real candles + decision audit.
"""
from __future__ import annotations

from collections import Counter
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import math
import sqlite3

import numpy as np
import pandas as pd

from .audit import AuditStore
from .market import normalize, require_resolution
from .features import future_label
from .strategy import Parameters


def _sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _utc(ts: int) -> str:
    return datetime.fromtimestamp(int(ts), tz=timezone.utc).isoformat()


def _finite(v):
    try:
        x = float(v)
    except (ValueError, TypeError):
        return None
    return x if math.isfinite(x) else None


def _safe_num(v, ndigits=8):
    return None if v is None or not math.isfinite(float(v)) else round(float(v), ndigits)


def _quantiles(nums):
    if not nums:
        return None
    vals=np.array(nums,dtype=float)
    return {"min":_safe_num(vals.min()),"p10":_safe_num(np.quantile(vals,.1)),
            "median":_safe_num(np.median(vals)),"p90":_safe_num(np.quantile(vals,.9)),
            "p95":_safe_num(np.quantile(vals,.95)),"max":_safe_num(vals.max()),
            "mean":_safe_num(vals.mean())}


def _correlation(pred, true, method):
    value = pd.Series(pred, dtype='float64').corr(pd.Series(true, dtype='float64'),method=method)
    return _safe_num(value)


def analyze(run_dir: str | Path) -> dict:
    folder=Path(run_dir)
    manifest_path=folder/'manifest.json'
    if not manifest_path.is_file():
        raise FileNotFoundError(f'Run manifest not found: {manifest_path}')
    m=json.loads(manifest_path.read_text(encoding='utf-8'))
    if m.get('evaluation_mode')!='separated_real_segments' or m.get('source')!='wallex_public_api':
        raise RuntimeError('This diagnostic currently accepts only verified Wallex segment-eval runs.')
    symbol=m.get('symbol')
    resolution=m.get('resolution')
    rel=m.get('evaluation_dataset_path','')
    if not rel or Path(rel).is_absolute() or '..' in Path(rel).parts:
        raise RuntimeError('Manifest evaluation path must be relative and inside the archived run.')
    path=(folder/rel).resolve()
    if not path.is_relative_to(folder.resolve()) or not path.is_file():
        raise RuntimeError('Genuine archived test segment missing.')
    if _sha256(path)!=m.get('dataset_file_sha256'):
        raise RuntimeError('Genuine test segment SHA-256 mismatch')
    trainrel=m.get('training_segment_path','')
    if not trainrel or Path(trainrel).is_absolute() or '..' in Path(trainrel).parts:
        raise RuntimeError('Unsafe/missing training path')
    trainpath=(folder/trainrel).resolve()
    if not trainpath.is_relative_to(folder.resolve()) or not trainpath.is_file() or _sha256(trainpath)!=m.get('training_segment_sha256'):
        raise RuntimeError('Training segment SHA-256 mismatch')
    model_path=folder/'ai_model.joblib'
    if not model_path.is_file() or _sha256(model_path)!=m.get('model_sha256'):
        raise RuntimeError('Archived model checksum mismatch (model will NOT be loaded)')
    df=normalize(pd.read_csv(path))
    require_resolution(df,resolution)
    if len(df)!=m.get('test_segment_rows'):
        raise RuntimeError('Archived test row count differs from manifest')
    audit_path=folder/'decisions.sqlite'
    if not audit_path.exists():
        raise FileNotFoundError(f'Missing audit database: {audit_path}')
    audit=AuditStore(audit_path)
    try:
        valid,n=audit.verify()
    finally:
        audit.close()
    if not valid:
        raise RuntimeError(f'Audit SHA-256 hash chain FAILED at event {n}')
    with closing(sqlite3.connect(f'{audit_path.resolve().as_uri()}?mode=ro',uri=True)) as conn:
        rows=conn.execute('SELECT kind,payload FROM events ORDER BY id').fetchall()
    heads=[json.loads(p) for k,p in rows if k=='RUN_START']
    decisions=[json.loads(p) for k,p in rows if k=='DECISION']
    ends=[json.loads(p) for k,p in rows if k=='RUN_END']
    fills=[json.loads(p) for k,p in rows if k=='SIMULATED_FILL']
    if len(heads)!=1 or len(ends)!=1:
        raise RuntimeError('Exactly one RUN_START and RUN_END are required')
    header=heads[0]
    if header.get('symbol')!=symbol or ends[0]!=m.get('results'):
        raise RuntimeError('Stored run metadata/results disagree with manifest')
    p=Parameters(**header['params'])
    threshold=p.entry_threshold
    horizon=p.horizon
    expected_n=header['end']-header['start']
    if len(decisions)!=expected_n:
        raise RuntimeError('Decision rows differ from recorded run index interval')
    if header['start']<0 or header['end']>len(df)-1:
        raise RuntimeError('Run index range outside verified real test segment')
    idx={int(ts):i for i,ts in enumerate(df.timestamp.to_numpy())}
    target=future_label(df,horizon)
    scored=[]
    forecast_values=[]
    reason_counts=Counter()
    action_counts=Counter()
    threshold_crossings=0
    forecast_missing=0
    for offset,row in enumerate(decisions):
        i=header['start']+offset
        ts=int(df.timestamp.iloc[i])
        ex=int(df.timestamp.iloc[i+1])
        if row.get('feature_candle')!=ts or row.get('execution_candle')!=ex or idx.get(ts)!=i:
            raise RuntimeError('Decision candle times do not align with archived real market data')
        action_counts[row.get('action','UNKNOWN')]+=1
        reason_counts[row.get('reason','UNKNOWN')]+=1
        pred=_finite(row.get('forecast'))
        if pred is None:
            forecast_missing+=1
            continue
        forecast_values.append(pred)
        if pred>threshold:
            threshold_crossings+=1
        realized=_finite(target.iloc[i])
        if realized is not None:
            scored.append({'feature_time_utc':_utc(ts),'prediction_log_return':pred,
                           'realized_future_log_return':realized,
                           'action':row.get('action'),'reason':row.get('reason')})
    pred=np.array([r['prediction_log_return'] for r in scored],dtype=float)
    actual=np.array([r['realized_future_log_return'] for r in scored],dtype=float)
    if len(scored):
        error=pred-actual
        forecast_skill={
            'scored_predictions':len(scored),
            'unscored_due_to_unobserved_future':len(forecast_values)-len(scored),
            'mae_log_return':_safe_num(np.mean(np.abs(error))),
            'rmse_log_return':_safe_num(np.sqrt(np.mean(error**2))),
            'predicted_mean_log_return':_safe_num(np.mean(pred)),
            'actual_mean_log_return':_safe_num(np.mean(actual)),
            'prediction_realized_pearson':_correlation(pred,actual,'pearson'),
            'prediction_realized_spearman':_correlation(pred,actual,'spearman'),
            'directional_accuracy':_safe_num(np.mean((pred>0)==(actual>0))),
            'always_predict_up_baseline_accuracy':_safe_num(np.mean(actual>0)),
            'actual_log_return_quantiles':_quantiles(list(actual)),
        }
    else:
        forecast_skill={'scored_predictions':0,'explanation':'No test horizon has both prediction and observed future open prices'}
    if not forecast_values:
        status='NO_FINITE_PREDICTIONS'
    elif max(forecast_values)<=threshold:
        status='NO_FORECAST_PASSED_ENTRY_THRESHOLD'
    elif action_counts.get('BUY',0)==0:
        status='FORECAST_PASSED_THRESHOLD_BUT_OTHER_GATES_BLOCKED'
    else:
        status='AT_LEAST_ONE_BUY_DECISION'
    top=sorted(scored,key=lambda r:r['prediction_log_return'],reverse=True)[:5]
    return {
      'run':str(folder),'mode':'EVIDENCE_ONLY_OFFLINE_ANALYSIS','source_claim':'wallex_public_api',
      'data_sha256_verified':True,'train_sha256_verified':True,'model_sha256_verified':True,
      'audit_hash_chain_valid':True,'audit_events':n,
      'symbol':symbol,'resolution':resolution,'training_rows':m['train_rows'],
      'test_segment_rows':len(df),'decision_count':len(decisions),
      'simulated_fill_count':len(fills),
      'recorded_financial_result':m['results'],
      'assumptions':{
        'forecast_horizon_bars':horizon,'fee_per_side':p.fee_rate,
        'slippage_per_side':p.slippage_rate,'edge_buffer':p.edge_buffer,
        'two_sided_fee_slippage_cost_log_return_approx':_safe_num(2*(p.fee_rate+p.slippage_rate)),
        'entry_threshold_log_return':_safe_num(threshold),
        'entry_threshold_approx_percent':_safe_num(threshold*100,5),
        'note':'Approximate arithmetic cost threshold, not verified execution cost or guaranteed profit.'},
      'action_counts':dict(sorted(action_counts.items())),
      'reason_counts':dict(sorted(reason_counts.items())),
      'finite_forecast_count':len(forecast_values),
      'nonfinite_forecast_count':forecast_missing,
      'entry_threshold_crossings':threshold_crossings,
      'forecast_log_return_quantiles':_quantiles(forecast_values),
      'forecast_skill_on_observed_real_future':forecast_skill,
      'top_five_forecasts_from_recorded_out_of_sample_decisions':top,
      'diagnosis':status,
      'cautions':['No synthetic data or artificial market observations used.',
        'Forecast skill is estimated ONLY from observed future Wallex candles; no future candles were used by the original decision maker.',
        'Backtest fills remain hypothetical, not live orders.',
        'Do not tune rules to maximize this one test period; use a later, disjoint genuinely observed holdout.',
        'A reproducible 0-trade result is not evidence of profitability or sufficient contest activity.']
    }


def write_report(run_dir: str | Path, out: str | Path | None = None):
    result=analyze(run_dir)
    dest=Path(out) if out else Path(run_dir)/'diagnostics.json'
    dest.parent.mkdir(parents=True,exist_ok=True)
    dest.write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    return result,dest
