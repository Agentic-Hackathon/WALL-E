"""M8 executable four-arm PIT news dataset/probe, no Champion modification.

Directly reuses NewsStore's 14 stamped features, V1 technical features and
scikit-learn StandardScaler/Ridge (BSD-3-Clause) only if enough shared data.
FinBERT-derived features are local research only, never competition authority.
"""
import hashlib,math,time
from datetime import datetime,timezone
import numpy as np
from .atlas_feature_health import _verified_segments
from .atlas_feature_provenance import annotate_receipts
from .atlas_signals import features
from .atlas_deep import COLS
from .atlas_forward import _sha

ARMS=('PRICE_ONLY','PRICE_TECH','PRICE_NEWS','PRICE_TECH_NEWS')

def dataset(lake,store,symbols):
    rows=[];counts={}
    for symbol in symbols:
        try:parts,_=_verified_segments(lake.root,lake.db,symbol,'15')
        except ValueError:continue
        for f in parts:
            f=f[f.timestamp+900<=time.time()].reset_index(drop=True)
            if len(f)<155:continue
            stamped=annotate_receipts(lake,symbol,'15',f);tech=features(f)[COLS]
            eligible=np.flatnonzero(stamped.available_at.notna().to_numpy()&(stamped.available_at.to_numpy()<=stamped.candle_close_at.to_numpy()))
            counts[symbol]=counts.get(symbol,0)+len(eligible)
            for i in eligible:
                if i<151 or i+3>=len(f):continue
                cutoff=int(f.timestamp.iloc[i])+900;news=store.features_at(symbol,datetime.fromtimestamp(cutoff,timezone.utc).isoformat())
                if not news['ready']:continue
                numeric=news['features']
                # A None is NOT a neutral sentiment and is not converted to 0.
                if any(v is None for v in numeric.values()):continue
                n=np.array(list(numeric.values()),float);t=tech.iloc[i].to_numpy(float)
                p=np.array([math.log(float(f[k].iloc[i])/float(f.close.iloc[i-1])) for k in ('open','high','low','close')]+[math.log1p(float(f.volume.iloc[i]))])
                if not all(np.isfinite(x).all() for x in (p,t,n)):continue
                rows.append({'id':symbol+':'+str(cutoff),'cutoff':cutoff,'label_end':int(f.timestamp.iloc[i+3])+900,
                    'y':float(np.log(f.close.iloc[i+3]/f.close.iloc[i])),
                    'arms':{'PRICE_ONLY':p.tolist(),'PRICE_TECH':np.r_[p,t].tolist(),'PRICE_NEWS':np.r_[p,n].tolist(),'PRICE_TECH_NEWS':np.r_[p,t,n].tolist()}})
    return sorted(rows,key=lambda r:(r['cutoff'],r['id'])),counts

def evaluate(lake,store,symbols=('BTCTMN','ETHTMN')):
    rows,counts=dataset(lake,store,symbols);span=(rows[-1]['cutoff']-rows[0]['cutoff'])/3600 if rows else 0
    common={'common_samples':len(rows),'sample_ids_sha256':_sha([r['id'] for r in rows]),'span_hours':span,
        'historical_receipt_eligible_candidates':counts,'target':'THREE_BAR_CLOSE_RETURN_NOT_EXECUTABLE_PNL',
        'license_guard':'LOCAL_NONCOMMERCIAL_RESEARCH_ONLY; no competition decision use authorized','promotion':False}
    if len(rows)<1280 or span<96:
        return {**common,'status':'INSUFFICIENT_PIT_NEWS_VALIDATION','arms':[{'arm':a,'mae':None,'status':'INSUFFICIENT_PIT_NEWS_VALIDATION'} for a in ARMS],
            'fusion':'INSUFFICIENT_DATA_NO_CROSS_ATTENTION_TRAINED'}
    from sklearn.preprocessing import StandardScaler
    from sklearn.linear_model import Ridge
    first=rows[int(.6*len(rows))]['cutoff'];second=rows[int(.8*len(rows))]['cutoff'];embargo=900
    train=[r for r in rows if r['label_end']+embargo<first];validation=[r for r in rows if r['cutoff']>=first and r['label_end']+embargo<second];test=[r for r in rows if r['cutoff']>=second]
    if len(train)<512 or len(validation)<128 or len(test)<128:
        return {**common,'status':'INSUFFICIENT_PIT_NEWS_VALIDATION','reason':'PURGED_GLOBAL_TIME_SPLITS_TOO_SMALL',
            'arms':[{'arm':a,'mae':None,'status':'INSUFFICIENT_PIT_NEWS_VALIDATION'} for a in ARMS]}
    results=[]
    for arm in ARMS:
        get=lambda rs:np.array([r['arms'][arm] for r in rs])
        scaler=StandardScaler().fit(get(train));model=Ridge(alpha=1).fit(scaler.transform(get(train)),[r['y'] for r in train])
        pred=model.predict(scaler.transform(get(test)))
        results.append({'arm':arm,'mae':float(np.abs(pred-np.array([r['y'] for r in test])).mean()),'status':'RETROSPECTIVE_SHARED_PIT_REGRESSION_PROBE_NOT_PNL'})
    return {**common,'status':'FIXED_FOUR_ARM_PROBE_COMPLETED_NO_PROMOTION','arms':results,
        'train':len(train),'validation':len(validation),'test':len(test),'scaler':'TRAIN_ONLY','fixed_alpha':1,'selection_on_test':False}
