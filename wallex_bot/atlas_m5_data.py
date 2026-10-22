"""M5 frozen real-Wallex datasets and explicitly retrospective label contracts.

Reuses Atlas V1/V2/V3 recipes and verified archive reader. No Champion mutation.
Unknown legacy receipt times remain unknown: historical closed-bar experiments
are never relabelled as prospectively observable evidence.
"""
from __future__ import annotations
import hashlib,json,sqlite3
from pathlib import Path
from dataclasses import dataclass
from datetime import datetime,timezone
import numpy as np
import pandas as pd
from .atlas_archive import period_seconds
from .atlas_feature_health import _read_catalog_symbols,_verified_segments
from .atlas_feature_recipe import challenger_features,POLICY
from .atlas_deep import COLS
from .atlas_feature_registry import compute_ohlcv_features,RECIPE_VERSION

PROTOCOL='M5_GLOBAL_PURGED_FOUR_WAY_V1'
SEEDS=(17,29,43)
CORE=['log_open_relative_last','log_high_relative_last','log_low_relative_last','log_close_relative_last','log1p_volume']
SELECTED_V3=['ema50_ratio','hma20_ratio','bb_width20','trend_persistence20']

def canonical(value):return json.dumps(value,sort_keys=True,ensure_ascii=False,allow_nan=False,separators=(',',':'))
def digest(value):return hashlib.sha256(canonical(value).encode()).hexdigest()
def iso(epoch):return datetime.fromtimestamp(float(epoch),timezone.utc).isoformat()

def feature_groups():
    groups={}
    for name,version,columns in [('A','ATLAS_EXISTING_V1',CORE+COLS),('B',POLICY,CORE+COLS),
        ('C',RECIPE_VERSION,CORE+COLS+SELECTED_V3),('D',RECIPE_VERSION,CORE+COLS+SELECTED_V3+['hourly_ema50_ratio']),
        ('E',RECIPE_VERSION,CORE+COLS+SELECTED_V3+['book_spread_bps','book_imbalance']),
        ('F',RECIPE_VERSION,CORE+COLS+SELECTED_V3+['news_sentiment_1h','news_count_24h','news_missing_mask']),
        ('G',RECIPE_VERSION,CORE+COLS+SELECTED_V3+['book_spread_bps','book_imbalance','news_sentiment_1h','news_count_24h','news_missing_mask'])]:
        groups[name]={'version':version,'columns':columns,'warmup_bars':55,'context':96,
            'missing_policy':'exclude nonfinite input windows; no price/news imputation',
            'normalization':'per observed input window; no statistics from future rows',
            'optional_dependency':{'D':'receipt-verified hourly','E':'real timely book','F':'verified PIT news','G':'real timely book and verified PIT news'}.get(name),
            'availability':'retrospective closed bars for prices, actual receipt cutoff for optional inputs'}
        groups[name]['definition_sha256']=digest(groups[name])
    return groups

def four_way_split(rows,horizon_seconds,*,min_counts=(256,64,64,64)):
    """Fixed global timestamp ratios; target end purge + one-bar embargo.

    Boundaries depend exclusively on unique feature timestamps, never outcomes.
    Calibration is a distinct later interval, untouched during epoch selection.
    """
    if not rows:return {'status':'INSUFFICIENT_REAL_TRAINING_HISTORY','indices':{},'counts':{}}
    if len({r['sample_id'] for r in rows})!=len(rows):raise ValueError('DUPLICATE_SAMPLE_IDS')
    times=sorted({int(r['feature_cutoff']) for r in rows});n=len(times)
    if n<8:return {'status':'INSUFFICIENT_REAL_TRAINING_HISTORY','indices':{},'counts':{}}
    cuts=[times[min(n-1,int(n*f))] for f in (.55,.70,.85)]
    period=min((b-a for a,b in zip(times,times[1:]) if b>a),default=900)
    indices={name:[] for name in ('train','validation','calibration','test')}
    for i,row in enumerate(rows):
        start=int(row['feature_cutoff']);end=int(row['target_end'])
        if end<=start or end-start!=horizon_seconds:raise ValueError('TARGET_HORIZON_MISMATCH')
        if end<cuts[0]-period:indices['train'].append(i)
        elif cuts[0]<=start and end<cuts[1]-period:indices['validation'].append(i)
        elif cuts[1]<=start and end<cuts[2]-period:indices['calibration'].append(i)
        elif start>=cuts[2]:indices['test'].append(i)
    counts={name:len(ids) for name,ids in indices.items()}
    for left,right in zip(indices,list(indices)[1:]):
        if indices[left] and indices[right] and max(rows[i]['target_end'] for i in indices[left])>=min(rows[i]['feature_cutoff'] for i in indices[right]):raise ValueError('GLOBAL_LABEL_LEAKAGE')
    return {'status':'ELIGIBLE_RETROSPECTIVE_RESEARCH' if all(counts[k]>=m for k,m in zip(indices,min_counts)) else 'INSUFFICIENT_REAL_TRAINING_HISTORY',
            'indices':indices,'counts':counts,'boundaries':cuts,'embargo_seconds':period,
            'horizon_seconds':horizon_seconds,'minimum_counts':list(min_counts),'independent_symbols_not_assumed':True,
            'purged_samples':len(rows)-sum(counts.values()),'split_sha256':digest({k:[rows[i]['sample_id'] for i in ids] for k,ids in indices.items()})}

@dataclass
class Bundle:
    config:dict
    rows:list
    arrays:dict
    split:dict
    coverage:list
    manifest:list

def prepare(root,resolution='15',horizon_hours=.75,top=8,context=96):
    if resolution not in ('15','60','1D') or horizon_hours not in (.75,48,72):raise ValueError('unsupported research horizon')
    period=period_seconds(resolution);horizon=int(horizon_hours*3600)//period
    if horizon<1 or horizon*period!=int(horizon_hours*3600):raise ValueError('horizon not aligned to resolution')
    root=Path(root).resolve();path=root/'catalog.sqlite'
    config={'resolution':resolution,'horizon_hours':horizon_hours,'horizon_bars':horizon,'context':context,
            'label_type':'CLOSE_TO_CLOSE_RETURN','evaluation_track':'RETROSPECTIVE_CLOSED_BAR_ASSUMPTION_NOT_PROSPECTIVE_PIT','protocol':PROTOCOL}
    if not path.exists():return Bundle(config,[],{},four_way_split([],horizon*period),[],[])
    db=sqlite3.connect(path.as_uri()+'?mode=ro',uri=True);all_rows={};arrays={g:{} for g in 'ABC'};coverage=[];manifest=[]
    try:
        symbols=_read_catalog_symbols(db,top)
        for symbol in symbols:
            sources=[dict(zip(('symbol','resolution','begin','end','relative_file','sha256'),row)) for row in db.execute(
                "SELECT symbol,resolution,begin,end,filename,sha256 FROM chunks WHERE symbol=? AND resolution=? AND status='COMPLETE' ORDER BY begin,filename",(symbol,resolution))]
            manifest.extend(sources)
        manifest_hash=digest(manifest)
        now=datetime.now(timezone.utc).timestamp()
        for symbol in symbols:
            parts,files=_verified_segments(root,db,symbol,resolution);counts={g:0 for g in 'ABC'};raw_candidates=0;longest=0
            receipt_rows=db.execute('''SELECT o.retrieved_at,o.available_at FROM chunk_observations o
                WHERE symbol=? AND resolution=?''',(symbol,resolution)).fetchall()
            latest_receipt=max((str(r[1]) for r in receipt_rows if r[1]),default=None)
            # Missing receipt coverage is explicitly unknown; no source times are invented.
            legacy=files>len(receipt_rows)
            for segment_id,raw in enumerate(parts):
                frame=raw[raw.timestamp.astype('int64')+period<=now].reset_index(drop=True);longest=max(longest,len(frame))
                raw_candidates+=max(0,len(frame)-horizon)
                if len(frame)<context+55+horizon:continue
                v1,v2,_=challenger_features(frame);v3=compute_ohlcv_features(frame)
                core=np.column_stack([np.log(frame[k].to_numpy(dtype=float)) for k in ('open','high','low','close')]+[np.log1p(frame.volume.to_numpy(dtype=float))])
                for t in range(context+54,len(frame)-horizon):
                    cutoff=int(frame.timestamp.iloc[t])+period;end=int(frame.timestamp.iloc[t+horizon])+period
                    key=digest({'symbol':symbol,'resolution':resolution,'cutoff':cutoff,'horizon':horizon_hours})
                    market_core=core[t-context+1:t+1].copy();market_core[:,:4]-=float(np.log(frame.close.iloc[t]))
                    sample={'sample_id':key,'symbol':symbol,'segment':segment_id,'feature_cutoff':cutoff,
                        'feature_available_at':None if legacy else latest_receipt,'target_horizon_hours':horizon_hours,
                        'target_start':cutoff,'target_end':end,'target_observed_at':None if legacy else latest_receipt,
                        'feature_recipe_version':'PER_GROUP_VERSIONED','source_manifest_sha256':manifest_hash,
                        'label_type':'CLOSE_TO_CLOSE_RETURN','data_quality_status':'LEGACY_RECEIPTS_UNCERTAIN_RETROSPECTIVE_ONLY' if legacy else 'RECEIPTS_AFTER_HISTORICAL_DECISION_RETROSPECTIVE_ONLY',
                        'y':float(np.log(frame.close.iloc[t+horizon]/frame.close.iloc[t])),
                        'past_log_return':float(np.log(frame.close.iloc[t]/frame.close.iloc[max(0,t-horizon)])),
                        'history_close_log':np.log(frame.close.iloc[t-context+1:t+1].to_numpy(dtype=float)/frame.close.iloc[t]).tolist()}
                    for group,features in [('A',v1),('B',v2),('C',pd.concat([v1,v3[SELECTED_V3]],axis=1))]:
                        matrix=np.column_stack([market_core,features.iloc[t-context+1:t+1].to_numpy(dtype=float)])
                        if not np.isfinite(matrix).all():continue
                        arrays[group][key]=np.clip((matrix-matrix.mean(0))/np.maximum(matrix.std(0),1e-6),-20,20).astype('float32')
                        counts[group]+=1;all_rows[key]=sample
            coverage.append({'symbol':symbol,'resolution':resolution,'horizon_hours':horizon_hours,'verified_chunks':files,
                'longest_contiguous_bars':longest,'raw_close_label_candidates':raw_candidates,
                'finite_context_samples':counts,'has_legacy_uncertainty':legacy})
    finally:db.close()
    common=set(arrays['A'])&set(arrays['B'])&set(arrays['C'])
    rows=sorted((all_rows[k] for k in common),key=lambda r:(r['feature_cutoff'],r['symbol']))
    X={group:np.stack([arrays[group][r['sample_id']] for r in rows]) for group in 'ABC'} if rows else {}
    config['source_manifest_sha256']=digest(manifest);config['dataset_sha256']=digest(rows)
    return Bundle(config,rows,X,four_way_split(rows,horizon*period),coverage,manifest)

def freeze(bundle,directory):
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=False)
    for name,value in [('config.json',bundle.config),('samples.json',bundle.rows),('source_manifest.json',bundle.manifest),('split.json',bundle.split),('coverage.json',bundle.coverage)]:
        (directory/name).write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf8')
    if bundle.arrays:np.savez_compressed(directory/'inputs.npz',**bundle.arrays)
    return {'dataset_sha256':bundle.config.get('dataset_sha256',digest([])),'split_sha256':bundle.split.get('split_sha256'),
            'manifest_sha256':digest(bundle.manifest),'directory':str(directory)}
