"""Next-bar-open backtest; conservative simplified execution, not exchange-grade."""
from __future__ import annotations
import csv, json, hashlib
from pathlib import Path
import numpy as np
from .market import normalize
from .strategy import Parameters,decision
from .learning import train,predict
from .audit import AuditStore

def backtest(df,params:Parameters,db_path,initial_cash=5_000_000,symbol='DEMO_TMN', model=None,
             start_index=None, end_index=None):
    df=normalize(df)
    if model is None:
        model,features,start=train(df,params.horizon)
    else:
        from .features import make_features
        features=make_features(df)
        start=start_index if start_index is not None else 36
    start=start if start_index is None else start_index
    end=(len(df)-1) if end_index is None else min(end_index,len(df)-1)
    if end<=start:
        raise ValueError('Insufficient evaluation window')
    store=AuditStore(db_path)
    cash=float(initial_cash);qty=0.;basis=0.;entry_at=-1
    peak=cash;trades=[];curves=[]
    input_hash=hashlib.sha256(df.to_csv(index=False,float_format='%.10g').encode()).hexdigest()
    store.record('RUN_START',{'symbol':symbol,'input_sha256':input_hash,
                 'start':start,'end':end,'initial_cash':initial_cash,'params':params.__dict__},'START')
    for i in range(start,end):
        # Use candle i's completed features to trade only at next candle's OPEN.
        ref=float(df.open.iloc[i+1]); ts=int(df.timestamp.iloc[i+1])
        equity=cash+qty*ref
        peak=max(peak,equity)
        forecast=predict(model,features,i)
        action,reason,notional=decision(forecast,cash,qty,ref,equity,peak,params,
                                        max(0,i-entry_at),basis)
        store.record('DECISION',{'feature_candle':int(df.timestamp.iloc[i]),
                     'execution_candle':ts,'forecast':None if not np.isfinite(forecast) else round(forecast,10),
                     'equity_tmn':round(equity,3),'cash_tmn':round(cash,3),
                     'qty':round(qty,12),'action':action,'reason':reason,
                     'suggested_notional_tmn':round(notional,3)},str(ts))
        if action=='BUY':
            fill=ref*(1+params.slippage_rate)
            qty_add=notional/(fill*(1+params.fee_rate))
            debited=qty_add*fill*(1+params.fee_rate)
            cash-=debited
            qty+=qty_add
            basis=fill
            entry_at=i
            trade={'time':ts,'side':'BUY','price':fill,'qty':qty_add,'fee_tmn':qty_add*fill*params.fee_rate}
            trades.append(trade);store.record('SIMULATED_FILL',trade,str(ts))
        elif action=='SELL' and qty>0:
            fill=ref*(1-params.slippage_rate)
            earned=qty*fill*(1-params.fee_rate)
            trade={'time':ts,'side':'SELL','price':fill,'qty':qty,'fee_tmn':qty*fill*params.fee_rate}
            cash+=earned;qty=0;basis=0;entry_at=-1
            trades.append(trade);store.record('SIMULATED_FILL',trade,str(ts))
        curves.append({'timestamp':ts,'equity_tmn':cash+qty*ref,'cash_tmn':cash,'base_qty':qty})
    # End of test is flat at next-bar OPEN, with costs charged.
    last=float(df.open.iloc[end]);last_ts=int(df.timestamp.iloc[end])
    if qty>0:
        fill=last*(1-params.slippage_rate)
        trade={'time':last_ts,'side':'SELL','price':fill,'qty':qty,'fee_tmn':qty*fill*params.fee_rate,
               'reason':'mandatory_final_flatten'}
        cash+=qty*fill*(1-params.fee_rate);qty=0
        trades.append(trade);store.record('SIMULATED_FILL',trade,str(last_ts))
    curves.append({'timestamp':last_ts,'equity_tmn':cash,'cash_tmn':cash,'base_qty':0})
    peaks=np.maximum.accumulate([x['equity_tmn'] for x in curves])
    max_dd=float(np.max(1-np.array([x['equity_tmn'] for x in curves])/peaks))
    result={'symbol':symbol,'first_ts':int(df.timestamp.iloc[start]),'final_ts':last_ts,
            'starting_tmn':float(initial_cash),'final_tmn':round(cash,3),
            'net_return_pct':round(100*(cash/initial_cash-1),5),
            'max_drawdown_pct':round(100*max_dd,5),'number_of_fills':len(trades),
            'number_of_round_trips':sum(t['side']=='SELL' for t in trades),
            'ending_crypto_qty':0,'input_sha256':input_hash}
    store.record('RUN_END',result,'END')
    store.close()
    return result,trades,curves,model

def export_result(folder,result,trades,curve):
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    (folder/'metrics.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    for name,arr in (('trades.csv',trades),('equity.csv',curve)):
        if arr:
            with (folder/name).open('w',newline='',encoding='utf-8') as f:
                w=csv.DictWriter(f,fieldnames=list(dict.fromkeys(k for a in arr for k in a.keys())))
                w.writeheader();w.writerows(arr)
