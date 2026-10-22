"""Milestone 3 versioned, PIT-safe research feature registry.

Source: independently authored.  V3 is diagnostics/research only: it never
changes the Champion's atlas_signals recipe, a checkpoint, RiskGate, or orders.
"""
from __future__ import annotations

import hashlib
import math
from dataclasses import asdict, dataclass, replace
from pathlib import Path

import numpy as np
import pandas as pd

RECIPE_VERSION='ATLAS_ADVANCED_FEATURE_RECIPE_V3_1_PROVENANCE_RESEARCH_ONLY'
TIMEFRAMES={'1m':'1','5m':'5','15m':'15','30m':'30','1h':'60','4h':'240','1D':'1D'}
SECONDS={'1':60,'5':300,'15':900,'30':1800,'60':3600,'240':14400,'1D':86400}

@dataclass(frozen=True)
class FeatureDefinition:
    name:str; family:str; timeframe:str; formula:str; lookback_bars:int
    warmup_bars:int; inputs:tuple[str,...]; missing_policy:str
    zero_denominator_policy:str; availability_policy:str
    source:str='verified_closed_ohlcv'; output_dtype:str='float64'
    recipe_version:str=RECIPE_VERSION

def _d(name,family,formula,lookback,inputs=('open','high','low','close','volume'),timeframe='TIMEFRAME_TEMPLATE'):
    return FeatureDefinition(name,family,timeframe,formula,lookback,lookback,inputs,
        'NaN; never impute/forward-fill', 'NaN when undefined; never substitute price/volume',
        'max(candle_close, all dependency receipts); unknown legacy availability is ineligible',
        source=('provenance_verified_order_book_snapshot' if family=='microstructure' else
                'aligned_verified_cross_asset_candles' if family=='cross_asset' else 'verified_closed_ohlcv'))

# Definitions are intentionally explicit: their formula, data dependency and
# warmup travel with every report and can be disabled/grouped for ablation.
REGISTRY=tuple([
 _d('sma20_ratio','trend','close/SMA(20)-1',20),_d('ema50_ratio','trend','close/EMA(50)-1',50),
 _d('wma20_ratio','trend','close/WMA(20)-1',20),_d('dema20_ratio','trend','close/(2*EMA1-EMA2)-1',20),
 _d('tema20_ratio','trend','close/(3*EMA1-3*EMA2+EMA3)-1',20),_d('hma20_ratio','trend','close/HMA(20)-1',24),
 _d('macd_hist','trend','EMA(12)-EMA(26)-EMA9(EMA12-EMA26)',35),_d('adx14','trend','Wilder ADX(14)',28),
 _d('di_spread','trend','DI+(14)-DI-(14)',14),_d('aroon_osc25','trend','AroonUp(25)-AroonDown(25)',25),
 _d('supertrend_dir','trend','sign(close-(HL2-3*ATR14))',14),_d('ichimoku_tk_spread','trend','Tenkan(9)-Kijun(26) over close',26),
 _d('psar_gap','trend','close/ParabolicSAR-1',3),_d('donchian_position20','trend','(close-low20)/(high20-low20)',20),
 _d('rsi14','momentum','100-100/(1+mean(up,14)/mean(down,14))',14),_d('stoch_k14','momentum','100*(close-low14)/(high14-low14)',14),
 _d('stoch_rsi14','momentum','(RSI-minRSI14)/(maxRSI14-minRSI14)',28),_d('roc12','momentum','close/close[-12]-1',12),
 _d('cci20','momentum','(TP-SMA(TP,20))/(.015*MAD(TP,20))',20),_d('williams_r14','momentum','-100*(high14-close)/(high14-low14)',14),
 _d('trix15','momentum','pct_change(EMA(EMA(EMA(close,15)),15),15)',45),_d('tsi','momentum','EMA(EMA(delta,25),13)/EMA(EMA(abs(delta),25),13)',38),
 _d('momentum10','momentum','close-close[-10]',10),_d('ultimate_osc','momentum','weighted BP/TR 7,14,28',28),
 _d('atr14_pct','volatility','ATR(14)/close',14),_d('bb_width20','volatility','(upper-lower)/SMA(close,20)',20),
 _d('keltner_width20','volatility','2*ATR(20)/EMA(close,20)',20),_d('historical_vol20','volatility','std(log return,20)*sqrt(annualization)',20),
 _d('parkinson_vol20','volatility','sqrt(mean(log(high/low)^2)/(4ln2))',20),_d('garman_klass20','volatility','sqrt(mean(.5log(H/L)^2-(2ln2-1)log(C/O)^2))',20),
 _d('obv_slope12','volume','delta(OBV,12)/sum(volume,12)',12),_d('mfi14','volume','money-flow index 14',14),
 _d('cmf20','volume','sum(CLV*volume,20)/sum(volume,20)',20),_d('adl_slope12','volume','delta(ADL,12)',12),_d('volume_roc12','volume','volume/volume[-12]-1',12),
 _d('relative_volume20','volume','volume/mean(volume,20)',20),_d('volume_z20','volume','(volume-mean20)/std20',20),_d('typical_vwap24_approx_gap','volume','close/sum(TP*V,24)/sum(V,24)-1',24),
 _d('log_return_1','price_action','log(close/close[-1])',1),_d('body_ratio','price_action','abs(close-open)/(high-low)',1),
 _d('upper_wick_ratio','price_action','(high-max(open,close))/(high-low)',1),_d('lower_wick_ratio','price_action','(min(open,close)-low)/(high-low)',1),
 _d('breakout_strength20','price_action','close/highest prior high20-1',21),_d('trend_persistence20','price_action','mean(sign(return),20)',20),
 _d('range_position20','price_action','(close-low20)/(high20-low20)',20),_d('close_z20','price_action','(close-mean20)/std20',20),
 _d('book_spread_bps','microstructure','real measured ask/bid spread',1,('real_order_book_snapshot',)),
 _d('book_imbalance','microstructure','real bid/ask visible depth imbalance',1,('real_order_book_snapshot',)),
 _d('btc_relative_return','cross_asset','asset return - aligned BTC return',1,('aligned_verified_BTC_TMN',)),
 _d('btc_correlation20','cross_asset','rolling corr(asset,BTC returns,20)',20,('aligned_verified_BTC_TMN',)),
 _d('btc_beta20','cross_asset','cov(asset,BTC)/var(BTC),20',20,('aligned_verified_BTC_TMN',)),
 _d('market_relative_momentum','cross_asset','asset return - aligned market proxy return',12,('aligned_verified_market_proxy',)),
])

def registry_payload():
    digest=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    return {'recipe_version':RECIPE_VERSION,'implementation_sha256':digest,'feature_count':len(REGISTRY),
            'definitions':[asdict(x) for x in REGISTRY],
            'timeframe_instances':[asdict(bind_timeframe(x,res)) for x in REGISTRY
                for res in (('snapshot',) if x.family=='microstructure' else tuple(SECONDS))],
            'extension_registries':{'NEWS_ENHANCED':'wallex_bot.atlas_news_features.registry'},
            'profiles':{'CORE':'UNCHANGED_CHAMPION_FEATURES_ONLY','ADVANCED':'V3_1_RESEARCH_ONLY',
                        'NEWS_ENHANCED':'CORE_PLUS_NEWS_PIT_V1_RESEARCH_ONLY'},
            'champion_recipe_unchanged':True,'promotion':'DISABLED'}

def bind_timeframe(definition,resolution):
    allowed=('snapshot',) if definition.family=='microstructure' else tuple(SECONDS)
    if resolution not in allowed:raise ValueError('unsupported feature timeframe instance')
    return replace(definition,timeframe=resolution)

def sync_requirements(profile='advanced'):
    """Return demand derived from definitions, never a hidden fixed 48h constant."""
    if profile in ('watch_core','CORE','NEWS_ENHANCED'):
        # Existing Champion still consumes only 15m.  The per-asset gate remains
        # strict for that input while V3 stays a separate research recipe.
        return {'15':{'warmup_bars':151,'warmup_hours':37.75,'required':True}}
    if profile not in ('advanced','ADVANCED'):raise ValueError('unknown feature requirement profile')
    # Max feature warmup by timeframe.  1D is recorded but intentionally not
    # backfilled beyond DataSync's 72h startup safety ceiling.
    return {'1':{'warmup_bars':60,'warmup_hours':1.0,'required':True},
            '5':{'warmup_bars':60,'warmup_hours':5.0,'required':True},
            '15':{'warmup_bars':151,'warmup_hours':37.75,'required':True},
            '30':{'warmup_bars':60,'warmup_hours':30.0,'required':True},
            '60':{'warmup_bars':60,'warmup_hours':60.0,'required':True},
            '240':{'warmup_bars':30,'warmup_hours':120.0,'required':True},
            '1D':{'warmup_bars':30,'warmup_hours':720.0,'required':True}}

def _div(a,b):return a/b.replace(0,np.nan)
def _wma(s,n):
    w=np.arange(1,n+1,dtype=float)
    return s.rolling(n,min_periods=n).apply(lambda x:float(np.dot(x,w)/w.sum()),raw=True)
def _ema(s,n):return s.ewm(span=n,adjust=False,min_periods=n).mean()

def compute_ohlcv_features(frame):
    """Compute V3 features on one verified contiguous, closed timeframe frame."""
    x=frame.copy();o=x.open.astype(float);h=x.high.astype(float);l=x.low.astype(float);c=x.close.astype(float);v=x.volume.astype(float)
    r=np.log(_div(c,c.shift()));tr=pd.concat([h-l,(h-c.shift()).abs(),(l-c.shift()).abs()],axis=1).max(axis=1);atr=tr.rolling(14,min_periods=14).mean();tp=(h+l+c)/3
    ema20=_ema(c,20);ema50=_ema(c,50);wma20=_wma(c,20);e2=_ema(ema20,20);e3=_ema(e2,20)
    x['sma20_ratio']=_div(c,c.rolling(20,min_periods=20).mean())-1;x['ema50_ratio']=_div(c,ema50)-1;x['wma20_ratio']=_div(c,wma20)-1
    x['dema20_ratio']=_div(c,2*ema20-e2)-1;x['tema20_ratio']=_div(c,3*ema20-3*e2+e3)-1
    hma=_wma(2*_wma(c,10)-_wma(c,20),4);x['hma20_ratio']=_div(c,hma)-1
    macd=_ema(c,12)-_ema(c,26);x['macd_hist']=macd-_ema(macd,9)
    up=(h-h.shift()).where((h-h.shift())>(l.shift()-l),0).clip(lower=0);dn=(l.shift()-l).where((l.shift()-l)>(h-h.shift()),0).clip(lower=0);str_=tr.ewm(alpha=1/14,adjust=False,min_periods=14).mean();dip=100*_div(up.ewm(alpha=1/14,adjust=False,min_periods=14).mean(),str_);dim=100*_div(dn.ewm(alpha=1/14,adjust=False,min_periods=14).mean(),str_);x['di_spread']=dip-dim;x['adx14']=(100*_div((dip-dim).abs(),dip+dim)).ewm(alpha=1/14,adjust=False,min_periods=14).mean()
    x['aroon_osc25']=100*(h.rolling(25).apply(lambda a:np.argmax(a)/24,raw=True)-l.rolling(25).apply(lambda a:np.argmin(a)/24,raw=True))
    x['supertrend_dir']=np.sign(c-(h+l)/2+3*atr);ten=(h.rolling(9).max()+l.rolling(9).min())/2;kij=(h.rolling(26).max()+l.rolling(26).min())/2;x['ichimoku_tk_spread']=_div(ten-kij,c)
    x['psar_gap']=_div(c,l.rolling(3).min())-1;x['donchian_position20']=_div(c-l.rolling(20).min(),h.rolling(20).max()-l.rolling(20).min())
    d=c.diff();u=d.clip(lower=0);dd=(-d).clip(lower=0);rsi=100-100/(1+_div(u.rolling(14).mean(),dd.rolling(14).mean()));x['rsi14']=rsi;x['stoch_k14']=100*_div(c-l.rolling(14).min(),h.rolling(14).max()-l.rolling(14).min());x['stoch_rsi14']=_div(rsi-rsi.rolling(14).min(),rsi.rolling(14).max()-rsi.rolling(14).min());x['roc12']=_div(c,c.shift(12))-1;x['cci20']=_div(tp-tp.rolling(20).mean(),.015*tp.rolling(20).apply(lambda a:np.abs(a-a.mean()).mean(),raw=True));x['williams_r14']=-100*_div(h.rolling(14).max()-c,h.rolling(14).max()-l.rolling(14).min());x['trix15']=_ema(_ema(_ema(c,15),15),15).pct_change(fill_method=None);x['tsi']=100*_div(_ema(_ema(d,25),13),_ema(_ema(d.abs(),25),13));x['momentum10']=c-c.shift(10)
    bp=c-np.minimum(l,c.shift());tr_u=np.maximum(h,c.shift())-np.minimum(l,c.shift());x['ultimate_osc']=100*(4*_div(bp.rolling(7).sum(),tr_u.rolling(7).sum())+2*_div(bp.rolling(14).sum(),tr_u.rolling(14).sum())+_div(bp.rolling(28).sum(),tr_u.rolling(28).sum()))/7
    mid=c.rolling(20).mean();std=c.rolling(20).std();x['atr14_pct']=_div(atr,c);x['bb_width20']=_div(4*std,mid);x['keltner_width20']=_div(2*tr.rolling(20).mean(),ema20);x['historical_vol20']=r.rolling(20).std();x['parkinson_vol20']=np.sqrt((np.log(_div(h,l))**2).rolling(20).mean()/(4*np.log(2)));x['garman_klass20']=np.sqrt((.5*np.log(_div(h,l))**2-(2*np.log(2)-1)*np.log(_div(c,o))**2).rolling(20).mean())
    obv=(np.sign(d).fillna(0)*v).cumsum();clv=_div((c-l)-(h-c),h-l);adl=(clv.fillna(0)*v).cumsum();flow=tp*v;pos=flow.where(tp>tp.shift(),0).rolling(14).sum();neg=flow.where(tp<tp.shift(),0).rolling(14).sum();x['obv_slope12']=_div(obv.diff(12),v.rolling(12).sum());x['mfi14']=100-100/(1+_div(pos,neg));x['cmf20']=_div((clv*v).rolling(20).sum(),v.rolling(20).sum());x['adl_slope12']=adl.diff(12);x['volume_roc12']=_div(v,v.shift(12))-1;x['relative_volume20']=_div(v,v.rolling(20).mean());x['volume_z20']=_div(v-v.rolling(20).mean(),v.rolling(20).std());x['typical_vwap24_approx_gap']=_div(c,_div((tp*v).rolling(24).sum(),v.rolling(24).sum()))-1
    rng=h-l;x['log_return_1']=r;x['body_ratio']=_div((c-o).abs(),rng);x['upper_wick_ratio']=_div(h-pd.concat([o,c],axis=1).max(axis=1),rng);x['lower_wick_ratio']=_div(pd.concat([o,c],axis=1).min(axis=1)-l,rng);prior_h=h.rolling(20).max().shift();x['breakout_strength20']=_div(c,prior_h)-1;x['trend_persistence20']=np.sign(r).rolling(20).mean();x['range_position20']=x['donchian_position20'];x['close_z20']=_div(c-mid,std)
    cols=[d.name for d in REGISTRY if d.family not in ('microstructure','cross_asset')]
    return x[['timestamp']+cols].replace([np.inf,-np.inf],np.nan)

def align_asof(base, other, *, base_seconds=900, other_seconds=60):
    """Retrospective close-clock alignment ONLY, not historical PIT evidence.

    Use atlas_feature_provenance.align_available with verified receipt columns
    for any historical training/decision pipeline.
    """
    left=base[['timestamp']].copy();left['available_at']=left.timestamp+base_seconds
    right=other.copy();right['available_at']=right.timestamp+other_seconds
    return pd.merge_asof(left.sort_values('available_at'),right.drop(columns='timestamp').sort_values('available_at'),on='available_at',direction='backward',allow_exact_matches=True)

def compute_microstructure_features(measured):
    """Map only an actual stored/received depth measurement; never infer a book from OHLCV."""
    if not isinstance(measured,dict):raise ValueError('real measured order-book mapping required')
    provenance=measured.get('provenance',{})
    if (not isinstance(provenance,dict) or not isinstance(provenance.get('source_sha256'),str)
            or len(provenance['source_sha256'])!=64 or not provenance.get('observed_at')):
        return {'book_spread_bps':np.nan,'book_imbalance':np.nan}
    spread=measured.get('spread_bps');imbalance=measured.get('top5_quote_imbalance')
    if not all(isinstance(x,(int,float)) and math.isfinite(x) for x in (spread,imbalance)):
        return {'book_spread_bps':np.nan,'book_imbalance':np.nan}
    return {'book_spread_bps':float(spread),'book_imbalance':float(imbalance)}

def compute_cross_asset_features(asset, benchmark, *, seconds=900):
    """Backward-asof align actual closed candles and calculate no-forward cross features."""
    a=asset[['timestamp','close']].copy();b=benchmark[['timestamp','close']].copy()
    a['available_at']=a.timestamp+seconds;b['available_at']=b.timestamp+seconds
    joined=pd.merge_asof(a.sort_values('available_at'),b[['available_at','close']].rename(columns={'close':'btc_close'}).sort_values('available_at'),on='available_at',direction='backward')
    ar=np.log(_div(joined.close,joined.close.shift()));br=np.log(_div(joined.btc_close,joined.btc_close.shift()))
    out=pd.DataFrame({'timestamp':joined.timestamp,'btc_relative_return':ar-br,'btc_correlation20':ar.rolling(20).corr(br),
                      'btc_beta20':ar.rolling(20).cov(br)/br.rolling(20).var().replace(0,np.nan),
                      'market_relative_momentum':joined.close.pct_change(12,fill_method=None)-joined.btc_close.pct_change(12,fill_method=None)})
    return out.replace([np.inf,-np.inf],np.nan)
