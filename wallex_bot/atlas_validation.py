"""Real-observation-only stage-4 statistical diagnostics and costed baselines.

Source: Hindsight by Ajay03299 @ 5111eeaf969c26c74443f5fd1d5dfbd30b32a9af
(MIT per recorded third_party/SOURCES.md, copyright template caveat) and
Bailey & Lopez de Prado, Deflated Sharpe Ratio (2014), Probability of
Backtest Overfitting (2015). CONCEPTS ONLY; no third-party code copied.
DLinear inspiration: Zeng et al., Are Transformers Effective for Time Series
Forecasting? (2022); implementation below is an independent ridge-fitted
trailing decomposition baseline, NOT a reproduction of paper checkpoints.

No market fixtures, interpolated bars, fabricated trades or PnL.
Fees/slippage are research assumptions until organizer/exchange verified.
All fills are counterfactual observed OPEN prices, NOT executable bid/ask.
"""
from __future__ import annotations

import hashlib
import itertools
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from statistics import NormalDist

import numpy as np
import pandas as pd

from .atlas_signals import features, strategies, trade_path


def _now():
    return datetime.now(timezone.utc).isoformat()


def _finite_cost(fee, slippage):
    if any(isinstance(x, bool) or not isinstance(x, (float, int)) or
           not math.isfinite(x) or not 0 <= x < 0.05 for x in (fee, slippage)):
        raise ValueError('Research fee and slippage must be finite non-negative fractions below 5%')


def _series_metrics(log_returns):
    z = np.asarray(log_returns, dtype=float)
    if not len(z) or not np.isfinite(z).all():
        return {'status': 'INSUFFICIENT_EVIDENCE'}
    cumulative = np.cumsum(z)
    peak = np.maximum.accumulate(np.r_[0., cumulative])
    drawdown = 1 - np.exp(cumulative - peak[1:])
    return {'status': 'COUNTERFACTUAL_ONLY', 'intervals': int(len(z)),
            'net_return_pct': float(np.expm1(cumulative[-1]) * 100),
            'max_drawdown_pct': float(max(0., drawdown.max(initial=0.)) * 100)}


def _event_path(df, signal, start, end, fee, slippage, hold=3):
    """Convert genuine observed-OPEN hypothetical round-trips to exit-index log returns.

    Zero cash return between counterfactual exits is an accounting convention,
    NOT a manufactured market price or observed fill. Events only from trade_path.
    """
    if end - start < hold + 3:
        raise ValueError('Insufficient genuine intervals for round trips')
    result = trade_path(df, signal, start, end, hold=hold, fee=fee, slippage=slippage)
    ts_to_index = {int(t): i for i, t in enumerate(df.timestamp.to_numpy())}
    out = np.zeros(end - start, dtype=float)
    for event in result['events']:
        idx = ts_to_index[int(event['exit_ts'])] - start
        if not 0 <= idx < len(out):
            raise RuntimeError('Observed exit timestamp not in original contiguous input')
        r = float(event['net_return'])
        if not math.isfinite(r) or r <= -1:
            raise RuntimeError('Invalid hypothetical result from genuine observed opens')
        out[idx] += math.log1p(r)
    return out, result


def _sharpe(returns):
    z = np.asarray(returns, dtype=float)
    if len(z) < 4 or not np.isfinite(z).all():
        return None
    sd = float(np.std(z, ddof=1))
    return float(np.mean(z) / sd) if sd > 1e-12 else None


def _blocks(logpath, block_size=8):
    """Use contiguous, disjoint, real-observation-aligned diagnostic blocks."""
    z = np.asarray(logpath, dtype=float)
    usable = len(z) // block_size * block_size
    return np.expm1(z[:usable].reshape(-1, block_size).sum(axis=1)) if usable else np.array([])


def deflated_sharpe(selected_block_returns, attempted_train_sharpes, nominal_trials):
    """Approximate Bailey & Lopez de Prado DSR selection diagnostic.

    Requires >=8 blocks, >=4 nondegenerate comparable training candidates,
    and an observed search-ledger trial count. Not an OOS profit certificate.
    """
    z = np.asarray(selected_block_returns, dtype=float)
    tried = np.asarray([s for s in attempted_train_sharpes if s is not None and math.isfinite(s)], dtype=float)
    if (len(z) < 8 or not np.isfinite(z).all() or len(tried) < 4 or
            nominal_trials is None or int(nominal_trials) < len(tried)):
        return {'status': 'INSUFFICIENT_EVIDENCE', 'reason': 'Need >=8 genuine time blocks, >=4 varying candidates and complete trials ledger'}
    sr = _sharpe(z)
    if sr is None or np.std(tried, ddof=1) <= 1e-12:
        return {'status': 'INSUFFICIENT_EVIDENCE', 'reason': 'Undefined or degenerate Sharpe distribution'}
    mu = float(np.mean(tried)); sigma = float(np.std(tried, ddof=1))
    normal = NormalDist(); n = int(nominal_trials)
    euler_gamma = 0.5772156649015329
    sr_benchmark = mu + sigma * ((1-euler_gamma)*normal.inv_cdf(1-1/n) +
                                  euler_gamma*normal.inv_cdf(1-1/(n*math.e)))
    centered = z - z.mean()
    sd = float(np.std(z, ddof=0))
    if sd <= 1e-12:
        return {'status': 'INSUFFICIENT_EVIDENCE', 'reason': 'Zero return variation'}
    skew = float(np.mean((centered/sd)**3)); kurt = float(np.mean((centered/sd)**4))
    denom_squared = 1 - skew*sr + (kurt-1)*sr*sr/4
    if denom_squared <= 1e-12:
        return {'status': 'INSUFFICIENT_EVIDENCE', 'reason': 'Invalid skew/kurtosis denominator'}
    zscore = (sr - sr_benchmark) * math.sqrt(len(z)-1) / math.sqrt(denom_squared)
    return {'status': 'APPROXIMATE_SELECTION_DIAGNOSTIC_NOT_OOS',
            'probability_sr_exceeds_deflated_benchmark': float(normal.cdf(zscore)),
            'observed_block_sharpe': sr, 'estimated_selection_benchmark_sharpe': sr_benchmark,
            'nominal_tests_from_ledger': n, 'candidate_sharpes_observed_here': len(tried),
            'block_count': len(z), 'limitations': 'Correlated candidates and short crypto samples; effective number of independent trials unknown'}


def pbo_cscv(train_block_matrix, max_splits=252):
    """CSCV over the TRAIN region only; never treat recombined folds as prospective OOS."""
    x = np.asarray(train_block_matrix, dtype=float)
    if x.ndim != 2 or x.shape[0] < 8 or x.shape[1] < 4 or x.shape[0] % 2 or not np.isfinite(x).all():
        return {'status': 'INSUFFICIENT_EVIDENCE', 'reason': 'Need >=8 even, disjoint time blocks and >=4 valid strategies'}
    n, cols = x.shape
    if (np.std(x, axis=0) < 1e-12).all():
        return {'status': 'INSUFFICIENT_EVIDENCE', 'reason': 'All candidates have degenerate performance'}
    combinations = math.comb(n, n//2)
    if combinations > max_splits:
        return {'status': 'INSUFFICIENT_EVIDENCE', 'reason': 'Too many CSCV combinations for exhaustiveness; reduce diagnostic blocks without synthetic sampling'}
    logits = []
    for indices in itertools.combinations(range(n), n//2):
        mask = np.zeros(n, dtype=bool); mask[list(indices)] = True
        ins = [_sharpe(x[mask, k]) for k in range(cols)]
        outs = [_sharpe(x[~mask, k]) for k in range(cols)]
        if any(v is None for v in ins) or any(v is None for v in outs):
            continue
        chosen = int(np.argmax(ins))
        out_scores = np.asarray(outs)
        # Assign exact tied ranks mid-rank; ties do not count as strong evidence.
        percentile = (np.sum(out_scores < out_scores[chosen]) +
                      0.5 * np.sum(out_scores == out_scores[chosen])) / cols
        if 0 < percentile < 1:
            logits.append(float(math.log(percentile/(1-percentile))))
    if len(logits) < 12:
        return {'status': 'INSUFFICIENT_EVIDENCE', 'reason': 'Too many degenerate/tied folds; no reliable PBO'}
    return {'status': 'IN_SAMPLE_SELECTION_OVERFIT_DIAGNOSTIC',
            'pbo_estimate': float(np.mean(np.asarray(logits) < 0)),
            'valid_splits': len(logits), 'possible_splits': combinations,
            'test_domain': 'CSCV splits entirely inside original chronological TRAIN period',
            'warning': 'Not evidence of genuine future trading results; folds not chronological prospective OOS'}


def _decomposed_features(close, index, window):
    # Original observed closed-candle history only, never forward mean.
    local = np.asarray(close[index-window+1:index+1], dtype=float)
    if len(local) != window or np.any(~np.isfinite(local)) or np.any(local <= 0):
        raise ValueError('Invalid real observed close window')
    normalized = np.log(local / local[-1])
    # Trailing moving average; first values use only observations actually in window.
    trend = pd.Series(normalized).rolling(9, min_periods=1).mean().to_numpy()
    return np.r_[trend, normalized-trend]


def dlinear_baseline(df, split, fee, slippage, *, window=32, horizon=3):
    """Independent DLinear-inspired trend+remainder linear heads, trained on real candles.

    Ridge solution instead of copied implementations. Purged global per-symbol split:
    every training label closes before split; validation decisions strictly later.
    """
    c = df.close.to_numpy(dtype=float)
    if len(c) < 180 or split < window+80 or len(c)-split < 30:
        return {'status': 'INSUFFICIENT_EVIDENCE', 'reason': 'Not enough contiguous real bars for linear decomposition baseline'}, None
    X = []; y = []
    for idx in range(window-1, split-horizon):
        X.append(_decomposed_features(c, idx, window))
        y.append(float(math.log(c[idx+horizon]/c[idx])))
    if len(X) < 80:
        return {'status': 'INSUFFICIENT_EVIDENCE', 'reason': 'Insufficient purged training labels'}, None
    x = np.asarray(X); y=np.asarray(y)
    mean=x.mean(axis=0); sd=x.std(axis=0); sd[sd < 1e-10]=1.
    scaled=(x-mean)/sd
    # Two linear subcomponents, global Ridge solve; no synthetic training data.
    system=scaled.T@scaled + np.eye(scaled.shape[1]) * max(0.1, len(scaled)*0.01)
    coef=np.linalg.solve(system, scaled.T@(y-y.mean()))
    intercept=float(y.mean())
    signals=np.zeros(len(c), dtype=bool)
    predictions=[]
    for idx in range(split, len(c)-horizon-1):
        xx=(_decomposed_features(c,idx,window)-mean)/sd
        pred=float(intercept+xx@coef)
        if not math.isfinite(pred):
            return {'status': 'INSUFFICIENT_EVIDENCE', 'reason': 'Non-finite linear forecast'}, None
        # Triple open-next-open turnover cost plus slight research margin.
        signals[idx]=pred > 2*(fee+slippage)+.001
        predictions.append(pred)
    if len(predictions)<24:
        return {'status':'INSUFFICIENT_EVIDENCE', 'reason':'Insufficient valid post-split predictions'},None
    return {'status':'TRAIN_ONLY_RIDGE_DLINEAR_INSPIRED', 'fit_samples':len(X),
            'validation_predictions':len(predictions), 'feature_window':window,
            'horizon_closed_candles':horizon, 'fee_assumption':fee,
            'warning':'Linear decomposition baseline is not the official DLinear training recipe'}, pd.Series(signals)


def _read_trials(lake):
    f = Path(lake.root)/'research'/'all_strategy_results.csv'
    if not f.is_file():
        return None, {'status':'NO_CANDIDATE_SEARCH_LEDGER'}
    frame=pd.read_csv(f)
    required={'symbol','segment','strategy','train_return_pct','holdout_return_pct'}
    if not required.issubset(frame.columns) or len(frame)<4:
        return None, {'status':'INVALID_CANDIDATE_SEARCH_LEDGER'}
    return len(frame), {'status':'ARCHIVED_SEARCH_LEDGER','rows':len(frame),
                        'sha256':hashlib.sha256(f.read_bytes()).hexdigest(),
                        'note':'Rows count nominal tried symbol/segment/strategy configurations, not effective independent hypotheses'}


def validate_archive(lake, *, fee=.001, slippage=.0005, resolution='15', max_symbols=8,
                     min_bars=180):
    """Read archived genuine candles; never modify model, trade/account or memory ledgers."""
    _finite_cost(fee, slippage)
    if resolution not in ('5','15','30','60'):
        raise ValueError('Stage4 validation requires supported intraday resolution')
    if not isinstance(max_symbols,int) or not 1 <= max_symbols <= 40:
        raise ValueError('max_symbols outside safe research bound')
    if min_bars < 180:
        raise ValueError('min_bars must be >=180 to avoid short non-informative segments')
    n_trials, ledger=_read_trials(lake)
    symbols = lake.symbols('tmn-spot')
    # Selection by most recent genuine 15-minute archive timestamp, NOT backtest profits.
    eligible=[]
    for s in symbols:
        try:
            segs=lake.load(s,resolution)
        except ValueError:
            continue
        for segment in segs:
            if len(segment)>=min_bars:
                eligible.append((int(segment.timestamp.iloc[-1]),s,segment))
    eligible.sort(key=lambda v:(-v[0],v[1]))
    used=set(); chosen=[]
    for end,s,frame in eligible:
        if s in used:continue
        used.add(s);chosen.append((s,frame))
        if len(chosen)>=max_symbols:break
    output={'generated_at_utc':_now(), 'mode':'HISTORICAL_COUNTERFACTUAL_GENUINE_OPENS_ONLY',
            'real_order_submission':False,'research_fee_assumption_per_side':fee,
            'slippage_assumption_per_side':slippage, 'fee_verified_with_exchange':False,
            'trial_ledger':ledger, 'screening_rule':'Most recent eligible contiguous segment, no return-based symbol ranking',
            'nominal_selected_trial_count':n_trials,'resolution':resolution,
            'symbols':[], 'champion_backtest':'NOT_SUPPORTED_WITHOUT_POST_PROMOTION_GENUINE_OUTCOMES',
            'risk_notice':'Top-of-book fills, realized contest PnL and verified fees NOT established',
            'decision_policy_integration':'OFF; diagnostics never promote models or relax RiskGate'}
    if not chosen:
        output['status']='INSUFFICIENT_EVIDENCE_NO_CONTIGUOUS_GENUINE_HISTORY'
        return output
    for sym, df in chosen:
        n=len(df);split=int(n*.70);warmup=65
        f=features(df); all_signals=strategies(f)
        candidates=[]; log_by_candidate={}
        for name, signal in all_signals.items():
            train_log,train_eval=_event_path(df,signal,warmup,split,fee,slippage)
            hold_log,hold_eval=_event_path(df,signal,split,n,fee,slippage)
            log_by_candidate[name]=train_log
            candidates.append({'name':name,'train':train_eval,'holdout':hold_eval})
        eligible_candidates=[v for v in candidates if v['train']['number_of_round_trips']>=2]
        if not eligible_candidates:
            output['symbols'].append({'symbol':sym,'status':'INSUFFICIENT_TRAIN_TRADES','bars':n});continue
        # Selection uses TRAIN only. HOLDOUT performance never participates.
        winner=max(eligible_candidates,key=lambda x:(x['train']['net_return_pct'],-x['train']['max_trade_sequence_drawdown_pct']))
        win_name=winner['name'];val_len=n-split
        holdout_log,_=_event_path(df,all_signals[win_name],split,n,fee,slippage)
        # Buy and hold entry/exit use actual OPEN at observed indices and same two-sided hypothetical cost.
        real_opens=df.open.to_numpy(dtype=float)
        hold_ret=((real_opens[n-1]*(1-slippage)*(1-fee))/
                  (real_opens[split]*(1+slippage)*(1+fee))-1)
        buy_hold={'status':'COUNTERFACTUAL_ONLY','net_return_pct':float(100*hold_ret),
                  'entry_open_utc':int(df.timestamp.iloc[split]),
                  'exit_open_utc':int(df.timestamp.iloc[n-1]),
                  'fee_assumption':fee,'slippage_assumption':slippage}
        # The random action baseline does not invent market returns, only a fixed decision rule.
        rng=np.random.default_rng(20261022)
        random_actions=pd.Series(np.zeros(n,dtype=bool))
        random_actions.iloc[split:n]=rng.random(n-split)<.10
        random_log,random_eval=_event_path(df,random_actions,split,n,fee,slippage)
        dlinear_info,linear_actions=dlinear_baseline(df,split,fee,slippage)
        if linear_actions is not None:
            dlinear_log,dlinear_eval=_event_path(df,linear_actions,split,n,fee,slippage)
            dlinear_info['holdout']= {k:v for k,v in dlinear_eval.items() if k!='events'}
        # TRAIN-only CSCV. Candidate returns assigned at actual observed exit indices.
        diagnostic_candidates=[v for v in eligible_candidates if v['train']['number_of_round_trips']>=4]
        blocks={}
        for v in diagnostic_candidates:
            blocks[v['name']]=_blocks(log_by_candidate[v['name']],8)
        sharpe_candidates=[name for name,z in blocks.items() if len(z)>=8 and _sharpe(z) is not None]
        sharpe_dist=[_sharpe(blocks[name]) for name in sharpe_candidates]
        selected_blocks=blocks.get(win_name, np.array([]))
        dsr=deflated_sharpe(selected_blocks,sharpe_dist,n_trials)
        if len(sharpe_candidates)>=4:
            matrix=np.column_stack([blocks[name] for name in sharpe_candidates]);
            if len(matrix)%2:matrix=matrix[:-1]
            if len(matrix)>10:matrix=matrix[-10:]  # 10 choose 5 = 252 exhaustive CSCV partitions
            pbo=pbo_cscv(matrix)
        else:
            pbo={'status':'INSUFFICIENT_EVIDENCE','reason':'<4 nondegenerate eligible train strategies with enough blocks'}
        output['symbols'].append({
            'symbol':sym,'status':'COUNTERFACTUAL_VALIDATION_ONLY',
            'bars':n, 'data_start_utc':int(df.timestamp.iloc[0]),'data_end_utc':int(df.timestamp.iloc[-1]),
            'train_end_utc':int(df.timestamp.iloc[split-1]),'holdout_start_utc':int(df.timestamp.iloc[split]),
            'training_candidates_evaluated':len(candidates),
            'training_selection_strategy':win_name,
            'indicator_holdout':{k:v for k,v in winner['holdout'].items() if k!='events'},
            'buy_and_hold_holdout':buy_hold,
            'random_policy_holdout':{k:v for k,v in random_eval.items() if k!='events'},
            'dlinear_holdout':dlinear_info,
            'training_selection_dsr':dsr,'training_cscv_pbo':pbo,
            'holdout_selected_minus_buy_hold_pct_points':float(winner['holdout']['net_return_pct']-buy_hold['net_return_pct']),
            'holdout_selected_minus_random_pct_points':float(winner['holdout']['net_return_pct']-random_eval['net_return_pct']),
            'decision_inclusion':'BLOCKED_UNTIL_VERIFIED_FEES_AND_PROSPECTIVE_PNL'})
    output['status']='HISTORICAL_COUNTERFACTUAL_RESEARCH_ONLY'
    return output


def store_report(lake, report):
    """Persist only a research report, never an order/memory/model mutation."""
    path=Path(lake.root)/'reports'/'stage4_validation.json'
    path.parent.mkdir(parents=True,exist_ok=True)
    from os import replace
    tmp=path.with_name(path.name+'.partial')
    tmp.write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf8')
    replace(tmp,path)
    return path
