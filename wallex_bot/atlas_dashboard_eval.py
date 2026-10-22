"""Point-in-time, non-invented Wallex Atlas retrospective research diagnostics.

Reads local archived genuine contiguous OHLCV only. Research results are
hypothetical at actually observed candle opens, NOT fill evidence or actual PnL.
Champion is NEVER evaluated on a period ending before its model promotion.
"""
from __future__ import annotations
import argparse, json, math, time
from datetime import datetime, timezone
from pathlib import Path
import numpy as np
from .atlas_archive import Lake
from .atlas_signals import features, strategies, trade_path


def _stamp(text):
    return datetime.fromisoformat(text.replace('Z','+00:00')).timestamp()


def _realtime_candidates(lake, top=12):
    order = []
    for (s, raw) in lake.db.execute('SELECT symbol,metadata FROM assets'):
        info = json.loads(raw)
        if info.get('is_spot') is not True or info.get('quote_asset') != 'TMN':
            continue
        try:vol = float(info.get('quote_volume_24h') or 0)
        except (ValueError,TypeError):vol=0
        order.append((vol,s))
    return [s for _,s in sorted(order,reverse=True)[:top]]


def indicator_diagnostic(lake, symbols, res='15', hours=24, fee=.001, slippage=.0005):
    period = 900 if res == '15' else 3600
    length = int(hours*3600/period)
    findings=[]
    for sym in symbols:
        try:chunks=lake.load(sym,res)
        except (ValueError,RuntimeError):continue
        seg=chunks[-1]
        if len(seg)<max(185,length+100):continue
        x=features(seg);signals=strategies(x)
        split=len(seg)-length
        pool=[]
        for name,flag in signals.items():
            tr=trade_path(seg,flag,65,split,3,fee,slippage)
            if tr['number_of_round_trips']>=2:
                pool.append((tr['net_return_pct'],name))
        if not pool:continue
        best=max(pool,key=lambda z:z[0])[1]
        test=trade_path(seg,signals[best],split,len(seg),3,fee,slippage)
        findings.append({'symbol':sym,'strategy':best,'selection':'BEST_TRAIN_PERIOD_ONLY',
                         'train_return_pct':max(pool)[0],
                         'evaluation_start_epoch':int(seg.timestamp.iloc[split]),
                         'evaluation_end_epoch':int(seg.timestamp.iloc[-1]+period),
                         'evaluation_hours_observed':round((len(seg)-split)*period/3600,2),
                         'test_net_return_pct':test['net_return_pct'],
                         'test_round_trips':test['number_of_round_trips'],
                         'test_max_drawdown_pct':test['max_trade_sequence_drawdown_pct'],
                         'price_basis':'ACTUAL_FUTURE_OPEN_WITH_ASSUMED_FEES_SLIPPAGE_NOT_REAL_FILLS'})
    return findings


def champion_diagnostic(lake, symbols, res='15', hours=24, fee=.001, slippage=.0005):
    folder=Path(lake.root)/'models'
    try:
        from .atlas_deep import verified_champion,COLS,features as deep_features,build_model
        import torch
        path=verified_champion(folder)
        champion=json.loads((folder/'active_champion.json').read_text(encoding='utf8'))
        ck=torch.load(path,map_location='cpu',weights_only=True)
    except (ImportError,RuntimeError,ValueError,OSError,KeyError,TypeError) as exc:
        return {'status':'NO_VERIFIED_MODEL','reason':type(exc).__name__,'results':[]}
    config=ck['config']
    if config['resolution']!=res:
        return {'status':'MODEL_TIMEFRAME_MISMATCH','results':[]}
    promoted=_stamp(champion['selected_at_utc'])
    # Every source file listed in the training manifest was available at model promotion;
    # no hindsight may enter an independent retrospective claim.
    sources=json.loads(path.with_suffix('.sources.json').read_text(encoding='utf8'))
    latest_training_end=max((int(x['end']) for x in sources if x.get('resolution')==res),default=0)
    not_before=max(promoted,latest_training_end)
    context=int(config['context']);horizon=int(config['horizon']);bar_seconds=900
    model=build_model(config['architecture'],context,len(COLS),'cpu')
    model.load_state_dict(ck['state_dict']);model.eval()
    results=[];available_opportunities=0
    for sym in symbols:
        try:segments=lake.load(sym,res)
        except (ValueError,RuntimeError):continue
        df=segments[-1]
        if len(df)<context+55+horizon+2:continue
        t=df.timestamp.to_numpy(dtype='int64')
        f=deep_features(df)
        x=f[COLS].to_numpy(dtype=float)
        candidates=[]
        # Full candle t[i] closes at t[i]+bar_seconds. That must follow promotion.
        # Signal at close -> hypothetical entry at NEXT observed open.
        for i in range(context+54,len(df)-horizon-1):
            if t[i]+bar_seconds <= not_before:continue
            if t[i]+bar_seconds < time.time()-hours*3600:continue
            window=x[i-context+1:i+1]
            if not np.isfinite(window).all():continue
            scaled=np.clip((window-window.mean(axis=0,keepdims=True))/np.maximum(
                window.std(axis=0,keepdims=True),1e-6),-20,20)
            with torch.no_grad(): q=model(torch.from_numpy(scaled[None].astype('float32'))).numpy()[0]
            if not (np.isfinite(q).all() and q[0]<=q[1]<=q[2]):continue
            candidates.append((i,[float(y) for y in q]))
        if not candidates:continue
        pnl=0.;n_trades=0;trade_outcomes=[];last_exit=-1;success=0;count=0
        for i,q in candidates:
            actual=math.log(float(df.close.iloc[i+horizon])/float(df.close.iloc[i]))
            count+=1;success+=((actual>0)==(q[1]>0))
            # A tentative gating rule on real observed next-open prices;
            # NEVER interpreted as order-book-spread-adjusted executable PnL.
            cost=2*(fee+slippage)+.001
            if q[0]>cost and i>last_exit:
                entry=i+1;exit_idx=entry+horizon
                buy=float(df.open.iloc[entry])*(1+slippage)
                sell=float(df.open.iloc[exit_idx])*(1-slippage)
                net=(sell*(1-fee))/(buy*(1+fee))-1
                pnl=(1+pnl)*(1+net)-1
                trade_outcomes.append(float(net));n_trades+=1;last_exit=exit_idx
        results.append({'symbol':sym,'observed_prediction_count':count,
                        'directional_accuracy':round(success/count,4) if count else None,
                        'hypothetical_trades':n_trades,
                        'hypothetical_net_return_pct':round(pnl*100,5),
                        'first_eligible_feature_epoch':int(t[candidates[0][0]]),
                        'last_eligible_feature_epoch':int(t[candidates[-1][0]]),
                        'assessment':'POST_PROMOTION_GENUINE_OHLCV_OPEN_PRICE_PROXY'})
        available_opportunities+=count
    return {'status':'POST_PROMOTION_OBSERVATIONS_ONLY' if results else 'WAITING_FOR_POST_PROMOTION_GENUINE_HISTORY',
            'checkpoint':path.name,'promoted_epoch':promoted,
            'strict_evaluation_not_before_epoch':not_before,
            'prediction_count':available_opportunities,'results':results,
            'caveats':['Not a 48h competition result; use forecast receipt evaluation for forward evidence.',
                      'Historical next-open proxies are not real bids/asks, actual fills, or account PnL.',
                      'Model selection used prior validation: pre-promotion prices are explicitly excluded.',
                      'Forecasts have overlapping horizons and are not independent.']}


def evaluate(lake, hours=24, top=12):
    from .atlas_archive import utcnow
    symbols=_realtime_candidates(lake, top)
    summary={'generated_at_utc':utcnow(),'assessment':'RESEARCH_DIAGNOSTICS_NOT_LIVE_PROFIT',
             'hours_requested':hours,'candidate_symbols':symbols,
             'indicator_challengers':indicator_diagnostic(lake,symbols,hours=hours),
             'champion':champion_diagnostic(lake,symbols,hours=hours),
             'data_policy':'REAL_VERIFIED_WALLEX_OHLCV_NO_FABRICATED_PRICES',
             'pricing_caveat':'Backtest uses real historical candle opens plus assumed fees/slippage, NOT actual exchange fills or order-book spreads.',
             'evaluation_warning':'Indicator selection on training only, but 40+ strategies / multiple markets create multiple-comparisons risk.'}
    out=Path(lake.root)/'reports'/'dashboard_research_eval.json'
    out.parent.mkdir(parents=True,exist_ok=True)
    tmp=out.with_suffix('.partial')
    tmp.write_text(json.dumps(summary,indent=2,ensure_ascii=False,allow_nan=False),encoding='utf8')
    tmp.replace(out)
    return {'output':str(out),'indicator_symbols':len(summary['indicator_challengers']),
            'champion_status':summary['champion']['status'],
            'champion_predictions':summary['champion'].get('prediction_count',0)}


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--hours',type=int,default=24)
    parser.add_argument('--top',type=int,default=12)
    args=parser.parse_args()
    if not 1<=args.hours<=72 or not 1<=args.top<=50:raise ValueError('Invalid retrospective window or symbol count')
    lake=Lake()
    try:print(json.dumps(evaluate(lake,hours=args.hours,top=args.top),ensure_ascii=False,indent=2))
    finally:lake.close()

if __name__=='__main__':main()
