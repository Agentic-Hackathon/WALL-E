"""Causal, auditable technical research on genuine closed Wallex candles."""
from __future__ import annotations
import numpy as np
import pandas as pd


def _ema(v,n):return v.ewm(span=n,adjust=False,min_periods=n).mean()
def _sma(v,n):return v.rolling(n,min_periods=n).mean()

def features(frame:pd.DataFrame):
    x=frame.copy(); c=x.close.astype(float);h=x.high.astype(float);l=x.low.astype(float);v=x.volume.astype(float)
    r=c.pct_change(); d=c.diff(); u=d.clip(lower=0); dn=(-d).clip(lower=0)
    x['ret1']=np.log(c/c.shift(1));x['ret3']=np.log(c/c.shift(3));x['ret6']=np.log(c/c.shift(6))
    x['ret12']=np.log(c/c.shift(12)); x['ret24']=np.log(c/c.shift(24))
    x['sma9']=_sma(c,9); x['sma20']=_sma(c,20); x['sma50']=_sma(c,50)
    x['ema9']=_ema(c,9);x['ema12']=_ema(c,12);x['ema26']=_ema(c,26);x['ema50']=_ema(c,50)
    x['macd']=x.ema12-x.ema26; x['macd_signal']=_ema(x.macd,9); x['macd_hist']=x.macd-x.macd_signal
    roll_u=_sma(u,14);roll_d=_sma(dn,14); x['rsi14']=100-100/(1+roll_u/roll_d.replace(0,np.nan))
    x['bb_mid']=_sma(c,20); std=c.rolling(20,min_periods=20).std()
    x['bb_upper']=x.bb_mid+2*std;x['bb_lower']=x.bb_mid-2*std
    x['bb_z']=(c-x.bb_mid)/std.replace(0,np.nan)
    pc=c.shift(1); tr=pd.concat([h-l,(h-pc).abs(),(l-pc).abs()],axis=1).max(axis=1)
    x['atr14']=_sma(tr,14);x['natr14']=x.atr14/c
    x['volatility12']=r.rolling(12,min_periods=12).std()
    x['volatility48']=r.rolling(48,min_periods=48).std()
    x['vol_z']=(v-_sma(v,20))/v.rolling(20,min_periods=20).std().replace(0,np.nan)
    x['volume_ratio']=v/_sma(v,20).replace(0,np.nan)
    tp=(h+l+c)/3;x['vwap24']=(tp*v).rolling(24,min_periods=24).sum()/v.rolling(24,min_periods=24).sum().replace(0,np.nan)
    x['obv']=(np.sign(d).fillna(0)*v).cumsum();x['obv_slope']=x.obv.diff(12)/v.rolling(12).sum().replace(0,np.nan)
    x['roc12']=c/c.shift(12)-1
    hh=h.rolling(14,min_periods=14).max();ll=l.rolling(14,min_periods=14).min()
    x['stoch_k']=100*(c-ll)/(hh-ll).replace(0,np.nan);x['stoch_d']=_sma(x.stoch_k,3)
    x['williams_r']=-100*(hh-c)/(hh-ll).replace(0,np.nan)
    x['cci20']=(tp-_sma(tp,20))/(.015*tp.rolling(20,min_periods=20).apply(lambda a:np.abs(a-a.mean()).mean()).replace(0,np.nan))
    # Ichimoku displacement: leading spans calculated at past times and shifted forward.
    tenkan=(h.rolling(9).max()+l.rolling(9).min())/2
    kijun=(h.rolling(26).max()+l.rolling(26).min())/2
    x['ich_tenkan']=tenkan;x['ich_kijun']=kijun
    x['ich_span_a']=((tenkan+kijun)/2).shift(26)
    x['ich_span_b']=((h.rolling(52).max()+l.rolling(52).min())/2).shift(26)
    x['donchian_high20']=h.rolling(20).max().shift(1)
    x['donchian_low20']=l.rolling(20).min().shift(1)
    # Historical Fibonacci anchored to *prior* rolling swing only.
    high48=h.rolling(48).max().shift(1);low48=l.rolling(48).min().shift(1)
    x['fib_382']=high48-.382*(high48-low48)
    x['fib_618']=high48-.618*(high48-low48)
    # ADX: Wilder exponential smoothing
    plusdm=(h-h.shift(1)).where((h-h.shift(1))>(l.shift(1)-l),0).clip(lower=0)
    minusdm=(l.shift(1)-l).where((l.shift(1)-l)>(h-h.shift(1)),0).clip(lower=0)
    smooth_tr=tr.ewm(alpha=1/14,adjust=False,min_periods=14).mean()
    x['di_plus']=100*plusdm.ewm(alpha=1/14,adjust=False,min_periods=14).mean()/smooth_tr.replace(0,np.nan)
    x['di_minus']=100*minusdm.ewm(alpha=1/14,adjust=False,min_periods=14).mean()/smooth_tr.replace(0,np.nan)
    dx=100*(x.di_plus-x.di_minus).abs()/(x.di_plus+x.di_minus).replace(0,np.nan)
    x['adx14']=dx.ewm(alpha=1/14,adjust=False,min_periods=14).mean()
    # MFI & Chaikin; no lookahead
    flow=tp*v; pos=flow.where(tp>tp.shift(),0).rolling(14).sum()
    neg=flow.where(tp<tp.shift(),0).rolling(14).sum()
    x['mfi14']=100-100/(1+pos/neg.replace(0,np.nan))
    clv=((c-l)-(h-c))/(h-l).replace(0,np.nan)
    adl=(clv.fillna(0)*v).cumsum(); x['chaikin']=_ema(adl,3)-_ema(adl,10)
    return x.replace([np.inf,-np.inf],np.nan)


def strategies(f:pd.DataFrame)->dict[str,pd.Series]:
    c=f.close; out={}
    def add(name,s):out[name]=s.fillna(False).astype(bool)
    for fast,slow in [(9,20),(9,50),(20,50)]:
        col={9:'sma9',20:'sma20',50:'sma50'}
        add(f'sma_{fast}_{slow}',f[col[fast]]>f[col[slow]])
    for fast,slow in [(9,26),(12,26),(9,50)]:
        e1=f[f'ema{fast}'] if f'ema{fast}' in f else _ema(c,fast)
        e2=f[f'ema{slow}'];add(f'ema_{fast}_{slow}',e1>e2)
    for lo in [25,30,35,40]:add(f'rsi_reversion_{lo}',f.rsi14<lo)
    for hi in [55,60,65,70]:add(f'rsi_momentum_{hi}',f.rsi14>hi)
    for z in [1.0,1.5,2.0]:add(f'bollinger_reversal_{z}',f.bb_z<-z)
    for z in [0.5,1.0,1.5]:add(f'bollinger_momentum_{z}',f.bb_z>z)
    add('macd_trend', f.macd>f.macd_signal)
    add('macd_zero',f.macd>0)
    add('ichimoku_cloud', (c>f[['ich_span_a','ich_span_b']].max(axis=1))&(f.ich_tenkan>f.ich_kijun))
    add('ichimoku_tenkan_kijun',f.ich_tenkan>f.ich_kijun)
    add('donchian_breakout',c>f.donchian_high20)
    add('donchian_reversion',c<f.donchian_low20)
    add('stochastic_cross',(f.stoch_k>f.stoch_d)&(f.stoch_k<35))
    add('williams_rebound',f.williams_r< -80)
    add('cci_rebound',f.cci20< -100)
    add('cci_trend',f.cci20>100)
    add('fibonacci_382',c>f.fib_382)
    add('fibonacci_618',c>f.fib_618)
    add('vwap_mean_revert',c<f.vwap24)
    add('vwap_momentum',c>f.vwap24)
    add('mfi_oversold',f.mfi14<25)
    add('mfi_volume_trend',f.mfi14>65)
    add('adx_strong_uptrend',(f.adx14>25)&(f.di_plus>f.di_minus))
    add('obv_trend',f.obv_slope>0)
    add('volume_breakout',(f.volume_ratio>2)&(f.ret1>0))
    for n in [3,6,12,24]:add(f'momentum_{n}',f[f'ret{n}']>0)
    add('low_vol_uptrend',(f.volatility12<f.volatility48)&(f.ema9>f.ema26))
    return out


def trade_path(frame, signal, start, end, hold=3, fee=.001, slippage=.0005):
    """Hypothetical next observed OPEN execution; no invented prices/fills."""
    if not 0<=fee<.05 or not 0<=slippage<.05:raise ValueError('invalid fee/slippage')
    signal=signal.to_numpy(dtype=bool); opens=frame.open.to_numpy(dtype=float)
    events=[];equity=1.0;i=start
    while i+hold+1<end:
        if not signal[i]:i+=1;continue
        enter=i+1;exit_i=enter+hold
        buy=opens[enter]*(1+slippage);sell=opens[exit_i]*(1-slippage)
        net=(sell*(1-fee))/(buy*(1+fee))-1
        equity*=1+net
        events.append({'decision_ts':int(frame.timestamp.iloc[i]),'entry_ts':int(frame.timestamp.iloc[enter]),
                       'exit_ts':int(frame.timestamp.iloc[exit_i]),'net_return':float(net)})
        i=exit_i+1
    returns=np.array([e['net_return'] for e in events]);
    peak=1.;val=1.;dd=0.
    for r in returns:
        val*=1+r;peak=max(peak,val);dd=max(dd,(peak-val)/peak)
    return {'number_of_round_trips':len(events),'net_return_pct':float((equity-1)*100),
            'max_trade_sequence_drawdown_pct':float(dd*100),'win_rate':float((returns>0).mean()) if len(returns) else None,
            'events':events}


def run_benchmark(lake,res='15', fee=.001,slippage=.0005,hold=3,min_bars=180):
    """Train-period strategy selection, non-overlapping holdout validation.
    Not a proper portfolio across symbols. Candidate results are hypothetical and multiple-tested.
    """
    results=[]
    for sym in lake.symbols('all-spot'):
        try: segments=lake.load(sym,res)
        except ValueError:continue
        for seg_index,df in enumerate(segments):
            if len(df)<min_bars:continue
            f=features(df); signals=strategies(f); n=len(df)
            split=int(n*.70)
            if split < 80 or n-split < hold+8:continue
            for name,s in signals.items():
                train=trade_path(df,s,65,split,hold,fee,slippage)
                val=trade_path(df,s,split,n,hold,fee,slippage)
                results.append({'symbol':sym,'segment':seg_index,'strategy':name,
                  'train_return_pct':train['net_return_pct'],'train_trades':train['number_of_round_trips'],
                  'holdout_return_pct':val['net_return_pct'],'holdout_trades':val['number_of_round_trips'],
                  'holdout_max_trade_dd_pct':val['max_trade_sequence_drawdown_pct'],
                  'holdout_win_rate':val['win_rate'],'bars':len(df),
                  'train_end_ts':int(df.timestamp.iloc[split-1]),'holdout_start_ts':int(df.timestamp.iloc[split])})
    out=pd.DataFrame(results)
    if out.empty:raise RuntimeError('No eligible real historical segments; harvest first')
    # Selection on train only, per symbol+segment, prohibit choosing using validation returns.
    eligible=out[out.train_trades>=2].sort_values('train_return_pct',ascending=False)
    winners=eligible.drop_duplicates(['symbol','segment']).reset_index(drop=True)
    return out,winners
