"""Expanding-window, purged out-of-sample fold evaluation on real OHLCV.

The feature/label boundary is fully before each test period. Every test starts
with independent paper capital; summary must not be mistaken for live return.
"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import joblib
import pandas as pd
from .learning import train_cutoff
from .market import normalize,require_resolution
from .simulator import backtest,export_result
from .strategy import Parameters


def evaluate(df:pd.DataFrame,folder:str | Path,symbol:str,resolution:str,
             fee:float,slippage:float,initial_train_bars:int=900,
             test_bars:int=288,initial_cash:float=5_000_000,
             horizon:int=3,min_notional:float=0):
    frame=normalize(df)
    require_resolution(frame,resolution)
    if initial_train_bars<330 or test_bars<72 or len(frame)<initial_train_bars+test_bars:
        raise ValueError('Insufficient history: need >= initial_train_bars + test_bars; '
                         'train minimum 330, test minimum 72 closed candles')
    p=Parameters(fee_rate=fee,slippage_rate=slippage,
                 horizon=horizon,min_trade_tmn=min_notional)
    output=Path(folder)
    if output.exists() and list(output.iterdir()):
        raise FileExistsError('Walk-forward output directory must be new/empty')
    output.mkdir(parents=True,exist_ok=True)
    scores=[]
    for fold_i,cutoff in enumerate(range(initial_train_bars,len(frame)-test_bars+1,test_bars),start=1):
        test_end=cutoff+test_bars
        subset=frame.iloc[:test_end].reset_index(drop=True)
        model,_,_=train_cutoff(subset,cutoff,horizon)
        fold=output/f'fold_{fold_i:02d}'
        fold.mkdir(exist_ok=True)
        result,trades,curve,_=backtest(subset,p,fold/'decisions.sqlite',initial_cash=initial_cash,
                   symbol=symbol,model=model,start_index=cutoff,end_index=test_end-1)
        export_result(fold,result,trades,curve)
        model_path=fold/'ai_model.joblib'
        joblib.dump(model,model_path)
        digest=hashlib.sha256(model_path.read_bytes()).hexdigest()
        metadata={'fold':fold_i,'train_cutoff_index':cutoff,
                  'last_training_candle_timestamp':int(frame.timestamp.iloc[cutoff-1]),
                  'test_start_timestamp':int(frame.timestamp.iloc[cutoff]),
                  'test_end_timestamp':int(frame.timestamp.iloc[test_end-1]),
                  'model_sha256':digest,'horizon':horizon,'test_bars':test_bars,
                  'symbol':symbol,'resolution':resolution,'params':p.__dict__,
                  'initial_cash_tmn':initial_cash,'metrics':result}
        (fold/'fold_manifest.json').write_text(json.dumps(metadata,indent=2,ensure_ascii=False),encoding='utf-8')
        scores.append(metadata)
    if not scores:raise RuntimeError('No complete folds')
    returns=[f['metrics']['net_return_pct'] for f in scores]
    drawdowns=[f['metrics']['max_drawdown_pct'] for f in scores]
    summary={'method':'expanding_window_purged_OOS_independent_folds',
             'symbol':symbol,'resolution':resolution,'folds':len(scores),
             'total_fills':sum(f['metrics']['number_of_fills'] for f in scores),
             'mean_test_return_pct':round(sum(returns)/len(returns),5),
             'median_test_return_pct':round(float(pd.Series(returns).median()),5),
             'profitable_folds':sum(v>0 for v in returns),
             'worst_fold_return_pct':min(returns),'worst_fold_drawdown_pct':max(drawdowns),
             'fold_results':scores,
             'caveat':'Each fold resets paper capital to initial_cash; returns are NOT compounded. '
                      'Bar-open fills are hypothetical, not real exchange executions. '
                      'Fold parameters must be locked before final evaluation.'}
    (output/'summary.json').write_text(json.dumps(summary,indent=2,ensure_ascii=False),encoding='utf-8')
    return summary
