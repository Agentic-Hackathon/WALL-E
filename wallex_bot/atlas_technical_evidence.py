"""M8 causal technical evidence; reuse V3 computations without changing V1/V3.

Original Fibonacci/confirmed-swing/Ichimoku alignment and trailing-band
SuperTrend adapter. Values are descriptive evidence, not validated forecasts.
"""
import argparse,hashlib,json,math,time
from pathlib import Path
import numpy as np
from .atlas_archive import Lake,period_seconds
from .atlas_feature_health import _verified_segments
from .atlas_feature_registry import compute_ohlcv_features,registry_payload
from .atlas_feature_provenance import annotate_receipts
from .atlas_forward import _sha
from .atlas_liquidation import _save_atomic

VERSION='ATLAS_TECHNICAL_EVIDENCE_V4_1'

def number(value):
    return float(value) if isinstance(value,(float,int,np.number)) and math.isfinite(value) else None


def confirmed_swings(frame,left=2,right=2,period=900):
    if left<1 or right<1:raise ValueError('SWING_CONFIRMATION_REQUIRES_CLOSED_NEIGHBOURS')
    result=[];h=frame.high.to_numpy(float);l=frame.low.to_numpy(float)
    for i in range(left,len(frame)-right):
        # Equality ties are not multiple confirmations of one flat plateau.
        if h[i]>max(h[i-left:i]) and h[i]>=max(h[i+1:i+right+1]):kind='HIGH';value=h[i]
        elif l[i]<min(l[i-left:i]) and l[i]<=min(l[i+1:i+right+1]):kind='LOW';value=l[i]
        else:continue
        result.append({'kind':kind,'price':float(value),'pivot_open':int(frame.timestamp.iloc[i]),
            'confirmed_at':int(frame.timestamp.iloc[i+right])+period,'confirmation_right_bars':right})
    return result


def compute(frame,period=900):
    if frame.empty:raise ValueError('NO_REAL_CLOSED_CANDLES')
    h=frame.high.astype(float);l=frame.low.astype(float);c=frame.close.astype(float)
    mid=lambda n:(h.rolling(n,min_periods=n).max()+l.rolling(n,min_periods=n).min())/2
    tenkan=mid(9);kijun=mid(26);span_a=(tenkan+kijun)/2;span_b=mid(52)
    cloud_a=span_a.shift(26);cloud_b=span_b.shift(26)
    reg=compute_ohlcv_features(frame);last=reg.iloc[-1]
    indicators={k:number(v) for k,v in last.items() if k!='timestamp'}
    # Preserve existing V3's simplified supertrend_dir; do not relabel it as
    # the full trailing-band algorithm. New field has a separate version.
    tr=np.maximum(h-l,np.maximum((h-c.shift()).abs(),(l-c.shift()).abs()))
    atr=tr.ewm(alpha=1/14,adjust=False,min_periods=14).mean()
    upper=(h+l)/2+3*atr;lower=(h+l)/2-3*atr;direction=None;u=None;d=None;line=None
    for i in range(len(frame)):
        if not math.isfinite(atr.iloc[i]):continue
        bu=float(upper.iloc[i]);bl=float(lower.iloc[i]);previous=float(c.iloc[i-1]) if i else float(c.iloc[i])
        if u is None:u=bu;d=bl;direction=1 if c.iloc[i]>=(h.iloc[i]+l.iloc[i])/2 else -1
        else:
            old_u=u;old_d=d
            u=bu if bu<old_u or previous>old_u else old_u
            d=bl if bl>old_d or previous<old_d else old_d
            if direction==-1 and c.iloc[i]>u:direction=1
            elif direction==1 and c.iloc[i]<d:direction=-1
        line=d if direction==1 else u
    swings=confirmed_swings(frame,period=period);anchors=[]
    if swings:
        last_swing=swings[-1];previous=next((p for p in reversed(swings[:-1]) if p['kind']!=last_swing['kind']),None)
        if previous:anchors=[previous,last_swing]
    fib={'version':'CONFIRMED_SWING_FIBONACCI_V1','status':'INSUFFICIENT_CONFIRMED_ANCHORS','retracements':None,'extensions':None,'anchors':anchors}
    if len(anchors)==2:
        lo=min(p['price'] for p in anchors);hi=max(p['price'] for p in anchors);distance=hi-lo;up=anchors[-1]['kind']=='HIGH'
        if distance>0:
            fib.update(status='DESCRIPTIVE_CONFIRMED_SWING_LEVELS',direction='UP' if up else 'DOWN',
                retracements={str(r):(hi-r*distance if up else lo+r*distance) for r in (.236,.382,.5,.618,.786)},
                extensions={str(r):(lo+r*distance if up else hi-r*distance) for r in (1.272,1.618,2.)})
    close_epoch=int(frame.timestamp.iloc[-1])+period
    payload={'version':VERSION,'candle_close_at':close_epoch,'indicator_values':indicators,
        'ichimoku':{'tenkan9':number(tenkan.iloc[-1]),'kijun26':number(kijun.iloc[-1]),
            'senkou_a_computed_now':number(span_a.iloc[-1]),'senkou_b_computed_now':number(span_b.iloc[-1]),
            'displayed_forward_at':close_epoch+26*period,'cloud_at_current_a':number(cloud_a.iloc[-1]),'cloud_at_current_b':number(cloud_b.iloc[-1]),
            'availability':'computed now is not available 26 bars ago; forward display is not future price',
            'chikou_policy':'NOT_BACKDATED_AS_HISTORICAL_FEATURE'},
        'supertrend_trailing_band_v1':{'direction':direction,'line':line,'atr14':number(atr.iloc[-1]),'multiplier':3.,
            'legacy_supertrend_dir':'V3 simplified HL2/ATR expression preserved, not silently replaced'},
        'fibonacci':fib,'confirmed_swings':swings[-12:],
        'provisional_extrema':{'status':'UNCONFIRMED_NOT_FIBONACCI_ANCHORS','high':number(h.tail(2).max()),'low':number(l.tail(2).min())},
        'support_resistance':{'confirmed_low_levels':[p['price'] for p in swings[-12:] if p['kind']=='LOW'],
            'confirmed_high_levels':[p['price'] for p in swings[-12:] if p['kind']=='HIGH']},
        'volume_profile':{'status':'INSUFFICIENT_REAL_TRADE_AT_PRICE_DATA','values':None},
        'vwap':{'status':'TYPICAL_PRICE_VOLUME_APPROXIMATION_NOT_TRADE_VWAP','gap':indicators.get('typical_vwap24_approx_gap')},
        'missing_indicators':[k for k,v in indicators.items() if v is None],
        'warmup':{'ichimoku_current_cloud':78,'fibonacci':'two opposite pivots confirmed with 2 closed right bars','supertrend':15},
        'missing_policy':'None/explicit reason, no imputation','champion_features_changed':False,'decision_authority':'RESEARCH_EVIDENCE_ONLY'}
    payload['evidence_sha256']=_sha(payload);return payload


def technical_evidence(lake,symbol,resolution='15',cutoff=None,*,retrospective=False):
    stamp=time.time() if cutoff is None else float(cutoff);period=period_seconds(resolution)
    if stamp>time.time()+1:raise ValueError('FUTURE_TECHNICAL_CUTOFF')
    parts,_=_verified_segments(lake.root,lake.db,symbol,resolution)
    parts=[p[p.timestamp+period<=stamp] for p in parts];parts=[p for p in parts if len(p)]
    if not parts:return {'status':'NO_VERIFIED_CLOSED_INPUT','symbol':symbol}
    frame=parts[-1];receipts=annotate_receipts(lake,symbol,resolution,frame)
    available=number(receipts.available_at.max());available=time.time() if available is None else available
    if cutoff is None:stamp=time.time()
    if available>stamp and not retrospective:return {'status':'NOT_AVAILABLE_AT_CUTOFF','symbol':symbol,'available_at':available}
    result=compute(frame,period);result.update(symbol=symbol,resolution=resolution,decision_timestamp=stamp,available_at=available,
        status='VERIFIED_CLOSED_TECHNICAL_EVIDENCE' if stamp-result['candle_close_at']<=2*period else 'STALE_TECHNICAL_EVIDENCE',
        source_hashes=dict(lake.db.execute("SELECT filename,sha256 FROM chunks WHERE symbol=? AND resolution=? AND status='COMPLETE'",(symbol,resolution))),
        track='RETROSPECTIVE_NOT_PROVEN_HISTORICAL_AVAILABILITY' if retrospective else 'RECEIPT_AWARE_CURRENT_EVIDENCE')
    result['evidence_sha256']=_sha({k:v for k,v in result.items() if k!='evidence_sha256'});return result


def main():
    p=argparse.ArgumentParser();p.add_argument('--root',default='atlas_store');p.add_argument('--symbol',default='BTCTMN');p.add_argument('--resolution',default='15');p.add_argument('--output');a=p.parse_args();lake=Lake(a.root)
    try:
        result=technical_evidence(lake,a.symbol,a.resolution)
        if a.output:_save_atomic(Path(a.output),result)
        print(json.dumps(result,ensure_ascii=False))
    finally:lake.close()

if __name__=='__main__':main()
