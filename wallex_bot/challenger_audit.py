"""Training-history-only chronological model comparison on archived real Wallex observations.

No synthetic data, no invented ticks, no trades, and no model choice based on the
already-examined final 24-hour evaluation. The archived test segment is never read.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.dummy import DummyRegressor
from sklearn.linear_model import Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from .features import COLUMNS, future_label, make_features
from .learning import train_at_training_boundary
from .market import normalize, require_resolution


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def safe_archived_train(run_dir: str | Path) -> tuple[pd.DataFrame, dict, Path]:
    """Read only the true training segment; validate hashes/provenance first.

    This validates a provenance assertion, NOT cryptographic authentication by Wallex.
    """
    root = Path(run_dir).resolve()
    manifest = root / 'manifest.json'
    if not manifest.is_file():
        raise FileNotFoundError(f'Original real run manifest missing: {manifest}')
    m = json.loads(manifest.read_text(encoding='utf-8'))
    if m.get('source') != 'wallex_public_api' or m.get('evaluation_mode') != 'separated_real_segments':
        raise ValueError('Only genuine archived Wallex separated-segment runs are accepted')
    rel = Path(m.get('training_segment_path', ''))
    if not str(rel) or rel.is_absolute() or '..' in rel.parts or str(rel) == '.':
        raise ValueError('Unsafe or absent training path')
    path = (root / rel).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError('Training CSV is outside archive or absent')
    if sha256(path) != m.get('training_segment_sha256'):
        raise ValueError('Genuine training CSV checksum mismatch')
    if m.get('symbol') is None or m.get('resolution') is None:
        raise ValueError('Original symbol/timeframe missing')
    df = normalize(pd.read_csv(path))
    require_resolution(df, m['resolution'])
    if len(df) != m.get('train_rows'):
        raise ValueError('Training row count differs from original manifest')
    if len(df) < 330:
        raise ValueError('Too few genuine training candles')
    return df, m, path


def make_folds(n: int, fold_bars: int = 72, n_folds: int = 2) -> list[tuple[int, int]]:
    """Strictly forward, nonoverlapping validation blocks, with >=330 prior candles."""
    if fold_bars < 24 or n_folds < 2 or n_folds > 5:
        raise ValueError('Require >=24 bars/fold and 2..5 chronological folds')
    first = n - fold_bars*n_folds
    if first < 330:
        raise ValueError(f'Need >= {330+fold_bars*n_folds} *real* bars for these folds; have {n}')
    return [(first + j*fold_bars, first + (j+1)*fold_bars) for j in range(n_folds)]


def _train_rows(features: pd.DataFrame, labels: pd.Series, cutoff: int, horizon: int) -> np.ndarray:
    # Align with original model's purging contract. Outcome labels for these
    # examples finish entirely before the validation boundary.
    return np.array([i for i in range(36, cutoff-horizon-1)
        if bool(features.loc[i, COLUMNS].notna().all()) and np.isfinite(labels.iloc[i])], dtype=int)


def _finite_float(x):
    return None if not np.isfinite(x) else round(float(x), 9)


def _score(y: np.ndarray, pred: np.ndarray, fee: float, slippage: float, buffer: float) -> dict:
    mask = np.isfinite(y) & np.isfinite(pred)
    y = y[mask]
    pred = pred[mask]
    if not len(y):
        raise ValueError('No genuinely observed outcomes to evaluate')
    threshold = 2*(fee+slippage)+buffer
    entries = pred > threshold
    pearson = None
    if len(y) >= 3 and np.std(y) > 0 and np.std(pred) > 0:
        pearson = _finite_float(np.corrcoef(y, pred)[0, 1])
    return {
        'n_scored': int(len(y)),
        'rmse': _finite_float(np.sqrt(np.mean((pred-y)**2))),
        'mae': _finite_float(np.mean(np.abs(pred-y))),
        'directional_accuracy': _finite_float(np.mean((pred>0) == (y>0))),
        'always_predict_up_directional_accuracy': _finite_float(np.mean(y>0)),
        'pearson': pearson,
        'forecast_mean': _finite_float(np.mean(pred)),
        'realized_mean': _finite_float(np.mean(y)),
        'signals_above_full_cost_threshold': int(entries.sum()),
        'mean_realized_net_edge_when_triggered': _finite_float(np.mean(y[entries]-2*(fee+slippage))) if entries.any() else None,
    }


def audit_training_only(run_dir: str | Path, fold_bars: int = 72,
                        n_folds: int = 2, horizon: int = 3) -> dict:
    df, manifest, path = safe_archived_train(run_dir)
    # Use REAL earlier history exclusively. This function never loads the
    # held-out test CSV, original predictions, or subsequent market outcomes.
    all_folds = make_folds(len(df), fold_bars, n_folds)
    f = make_features(df)
    y = future_label(df, horizon)
    fee = float(manifest['fee_rate_assumption'])
    slippage = float(manifest['slippage_rate_assumption'])
    if not (0 <= fee < .05 and 0 <= slippage < .05):
        raise ValueError('Invalid archived transaction cost assumptions')
    buffer = .001
    results = []
    for cutoff, end in all_folds:
        train_rows = _train_rows(f, y, cutoff, horizon)
        if len(train_rows) < 150:
            raise ValueError('Insufficient earlier labeled candles')
        # Prevent scoring overlapping outcomes extending into the next fold
        # or beyond the locally observed archived history.
        idx = np.array([i for i in range(cutoff, end)
            if i+horizon+1 < end and bool(f.loc[i, COLUMNS].notna().all())
            and np.isfinite(y.iloc[i])], dtype=int)
        if len(idx) < 20:
            raise ValueError('Validation window too short after horizon embargo')
        x_train = f.loc[train_rows, COLUMNS].to_numpy(dtype=float)
        y_train = y.iloc[train_rows].to_numpy(dtype=float)
        x_eval = f.loc[idx, COLUMNS].to_numpy(dtype=float)
        y_eval = y.iloc[idx].to_numpy(dtype=float)
        original, _, _ = train_at_training_boundary(df, cutoff, horizon=horizon)
        ridge = make_pipeline(StandardScaler(), Ridge(alpha=20.0))
        ridge.fit(x_train, y_train)
        mean = DummyRegressor(strategy='mean')
        mean.fit(x_train, y_train)
        models = {'existing_hgboost':original, 'regularized_ridge':ridge,
                  'training_mean_baseline':mean}
        fold = {'training_cutoff_index':int(cutoff), 'validation_end_exclusive_index':int(end),
                'training_last_feature_ts':int(df.timestamp.iloc[train_rows[-1]]),
                'validation_start_ts':int(df.timestamp.iloc[cutoff]),
                'validation_last_scored_feature_ts':int(df.timestamp.iloc[idx[-1]]),
                'training_examples':int(len(train_rows)), 'model_metrics':{}}
        for name, model in models.items():
            fold['model_metrics'][name] = _score(y_eval, model.predict(x_eval), fee, slippage, buffer)
        # Ridge coefficients are on standardized inputs and describe association,
        # not causal effects or guaranteed forecasting value.
        fold['ridge_standardized_coefficients'] = {key:_finite_float(coef)
            for key,coef in zip(COLUMNS, ridge.named_steps['ridge'].coef_)}
        results.append(fold)
    # Use descriptive output rather than selecting a strategy based on an
    # already-examined test period or automatically authorizing a trade.
    report = {
        'mode':'TRAIN_HISTORY_ONLY_CHRONOLOGICAL_DIAGNOSTICS',
        'source_claim':'wallex_public_api',
        'source_verification':'archived SHA256 and provenance assertion only; not an exchange-signed attestation',
        'archived_training_sha256':sha256(path),
        'symbol':manifest['symbol'],'resolution':manifest['resolution'],
        'train_segment_bars':len(df), 'horizon_bars':horizon,
        'fold_bars':fold_bars,'n_folds':n_folds,
        'fee_per_side_assumption':fee,'slippage_per_side_assumption':slippage,
        'entry_buffer_assumption':buffer,
        'candidate_names':['existing_hgboost','regularized_ridge','training_mean_baseline'],
        'fold_results':results,
        'next_action':('Compare models on original training segment only. Freeze a research hypothesis '
                       'before collecting a NEW unseen 48-72h shadow sample. Do not authorize real orders.'),
        'limitations':[
            'The newer 24-hour test segment is deliberately NOT opened, used, or scored.',
            'This archive was already used to inspect a 24-hour model failure; do not call a later re-test on it a pristine holdout.',
            'Three-candle forward outcomes overlap; fold scores are descriptive and not independent statistical trials.',
            'Opportunity cost-adjusted edge is NOT a portfolio PnL or fill simulation.',
            'No synthetic market observations, simulated candles or mocked prices are used.',
        ],
    }
    return report


def write_training_audit(run_dir: str | Path, out: str | Path | None = None,
                         fold_bars: int = 72, n_folds: int = 2, horizon: int = 3):
    report = audit_training_only(run_dir, fold_bars, n_folds, horizon)
    p = Path(out) if out else Path(run_dir)/'training_only_challenger_audit.json'
    p.parent.mkdir(parents=True, exist_ok=True)
    if p.exists():
        raise FileExistsError(f'Will not overwrite a prior audit: {p}')
    p.write_text(json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False), encoding='utf-8')
    return report, p
