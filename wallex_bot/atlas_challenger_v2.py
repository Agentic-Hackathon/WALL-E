"""Stage 13. Paired feature-recipe research on genuine SHA-verified Wallex candles.

V1_COMMON and V2_COMMON use IDENTICAL timestamped train/validation IDs.
V2_EXPANDED uses additional V2-only TRAIN IDs, but the same held-out
COMMON validation IDs. V2-only validation IDs are NEVER admitted to training.
No Champion promotion, market HTTP, paper orders, fake OHLCV, or live actions.
The internal validation is model-selection evidence, not prospective PnL.
"""
from __future__ import annotations

import hashlib
import json
import math
import time
import uuid
from pathlib import Path
from dataclasses import dataclass

import numpy as np

from .atlas_archive import root_path
from .atlas_deep import COLS, build_model, _torch
from .atlas_feature_health import _read_catalog_symbols, _verified_segments, _last_quote_epoch
from .atlas_feature_recipe import challenger_features, POLICY
from .atlas_operational import _read_connection, _table
from .atlas_mode import require_mode, ExecutionMode

CONTEXT = 96
HORIZON = 3
PERIOD = 900
# Research comparisons with limited time are NOT approved as trading evidence.
SPLIT_HOURS = (24, 18, 12, 8, 6)
MIN_COMMON_TRAIN = 256
MIN_COMMON_VAL = 80


def _canonical_sha(payload):
    return hashlib.sha256(json.dumps(payload,sort_keys=True,separators=(',',':'),
                                      ensure_ascii=False,allow_nan=False).encode('utf8')).hexdigest()


def _scale_feature_window(values):
    """Identical per-window normalization to existing PatchTST recipe."""
    mu=values.mean(axis=0,keepdims=True)
    std=values.std(axis=0,keepdims=True)
    return np.clip((values-mu)/np.maximum(std,1e-6),-20,20).astype(np.float32)


def _window(frame, ending):
    values=frame.iloc[ending-CONTEXT+1:ending+1].to_numpy(dtype=np.float64)
    return None if values.shape!=(CONTEXT,len(COLS)) or not np.isfinite(values).all() else _scale_feature_window(values)


def _assert_chronological_purge(train,valid,cutoff):
    """Pure time/metadata contract. Never constructs market observations."""
    if not train or not valid:
        raise RuntimeError('INSUFFICIENT_REAL_CHRONOLOGICAL_SAMPLES')
    if any(int(row['label_end_ts'])>=cutoff for row in train):
        raise RuntimeError('TRAIN_LABEL_OVERLAPS_GLOBAL_VALIDATION_CUTOFF')
    if any(int(row['t'])<cutoff for row in valid):
        raise RuntimeError('VALIDATION_FEATURE_PRECEDES_GLOBAL_CUTOFF')
    if max(int(row['label_end_ts']) for row in train)>=min(int(row['t']) for row in valid):
        raise RuntimeError('GLOBAL_TIME_LEAKAGE_DETECTED')
    if {tuple(r['key']) for r in train} & {tuple(r['key']) for r in valid}:
        raise RuntimeError('DUPLICATE_TRAIN_VALIDATION_SAMPLE')


def _records_from_genuine_segment(symbol, segment_index, segment):
    stamps=segment.timestamp.to_numpy(dtype=np.int64)
    if len(segment)<CONTEXT+55 or np.any(stamps%PERIOD) or np.any(np.diff(stamps)!=PERIOD):
        return {},{},{}
    v1,v2,_=challenger_features(segment)
    closings=segment.close.to_numpy(dtype=np.float64)
    common={};extra={};auxiliary={}
    for t in range(CONTEXT+54,len(segment)-HORIZON):
        closing_now=closings[t];closing_future=closings[t+HORIZON]
        if (not np.isfinite(closing_now) or not np.isfinite(closing_future)
            or closing_now<=0 or closing_future<=0):
            continue
        x2=_window(v2,t)
        if x2 is None:continue
        x1=_window(v1,t)
        key=(symbol,int(stamps[0]),int(segment_index),int(stamps[t]))
        row={'key':key,'symbol':symbol,'t':int(stamps[t]),
             'label_end_ts':int(stamps[t+HORIZON]),
             'y':float(math.log(closing_future/closing_now))}
        if not math.isfinite(row['y']):continue
        if x1 is not None:
            common[key]=({**row,'x':x1},{**row,'x':x2})
        else:
            extra[key]={**row,'x':x2}
    return common,extra,auxiliary


def _source_manifest(db, names):
    if not _table(db,'chunks'):return []
    result=[]
    for name in names:
        result.extend({'symbol':name,'resolution':'15','relative_file':file,'sha256':digest,
                       'begin':int(begin),'end':int(end)}
           for file,digest,begin,end in db.execute(
               "SELECT filename,sha256,begin,end FROM chunks WHERE symbol=? AND resolution='15' AND status='COMPLETE' ORDER BY begin,filename",
               (name,)))
    return result


def _choose_split(common, extra, max_validation_hours):
    """Train/validation partition depends only on timestamps and eligibility."""
    if not common:return None
    latest=max(pair[0]['t'] for pair in common.values())
    for hours in SPLIT_HOURS:
        if hours>max_validation_hours:continue
        cutoff=((latest-hours*3600)//PERIOD)*PERIOD
        train=[pair for pair in common.values() if pair[0]['label_end_ts']<cutoff]
        val=[pair for pair in common.values() if pair[0]['t']>=cutoff]
        if len(train)<MIN_COMMON_TRAIN or len(val)<MIN_COMMON_VAL or len(train)<1.2*len(val):
            continue
        extra_train=[record for record in extra.values() if record['label_end_ts']<cutoff]
        extra_val=[record for record in extra.values() if record['t']>=cutoff]
        train_v1=sorted((p[0] for p in train),key=lambda r:r['key'])
        train_v2=sorted((p[1] for p in train),key=lambda r:r['key'])
        val_v1=sorted((p[0] for p in val),key=lambda r:r['key'])
        val_v2=sorted((p[1] for p in val),key=lambda r:r['key'])
        train_extra=sorted(extra_train,key=lambda r:r['key'])
        _assert_chronological_purge(train_v1,val_v1,cutoff)
        _assert_chronological_purge(train_v2,val_v2,cutoff)
        _assert_chronological_purge(train_v2+train_extra,val_v2,cutoff)
        return {'hours':hours,'cutoff':cutoff,'train_v1':train_v1,
                'train_v2':train_v2,'valid_v1':val_v1,'valid_v2':val_v2,
                'extra_train_v2':train_extra,'extra_valid_v2':sorted(extra_val,key=lambda r:r['key'])}
    return None


def _data_for_model(records):
    X=np.stack([r['x'] for r in records]).astype(np.float32)
    y=np.array([r['y'] for r in records],dtype=np.float32)
    if not np.isfinite(X).all() or not np.isfinite(y).all():
        raise RuntimeError('NONFINITE_REAL_RESEARCH_INPUTS')
    return X,y


def _metadata_rows(rows):
    return [{'key':list(r['key']),'label_end_ts':r['label_end_ts']} for r in rows]


@dataclass
class ResearchBundle:
    public_report: dict
    split: dict | None
    source_manifest: list


def prepare(root,top=8,validation_hours=24):
    """Never opens writable SQLite. Gaps, tampering, missing quotes fail closed."""
    require_mode(ExecutionMode.BACKTEST,permitted=(ExecutionMode.BACKTEST,),operation='challenger research')
    if not isinstance(top,int) or not 1<=top<=40:raise ValueError('top must be 1..40')
    if not isinstance(validation_hours,int) or validation_hours<6 or validation_hours>48:
        raise ValueError('validation_hours must be 6..48')
    root=Path(root).resolve();db=_read_connection(root/'catalog.sqlite')
    base={'mode':'BACKTEST_RESEARCH_ONLY_NO_EXECUTION',
          'policy':'STAGE13_PAIRED_GLOBAL_PURGED_V1_V2_COMPARISON',
          'feature_recipe_v2':POLICY,
          'v2_feature_recipe_sha256':hashlib.sha256(Path(__file__).with_name('atlas_feature_recipe.py').read_bytes()).hexdigest(),
          'training_target':'REAL_CLOSE_TO_CLOSE_H3_NOT_EXECUTABLE_QUOTE_PNL',
          'validation_is_not_prospective_48h':True,
          'no_champion_promotion':True,'real_order_submission':False,
          'read_only_data_access':True}
    if db is None:
        return ResearchBundle({**base,'status':'NO_EXISTING_GENUINE_CATALOG'},None,[])
    try:
        names=_read_catalog_symbols(db,top)
        if not names:return ResearchBundle({**base,'status':'NO_ELIGIBLE_TMN_SPOT_SYMBOLS'},None,[])
        common={};extra={};audit=[]
        manifest=_source_manifest(db,names)
        for symbol in names:
            quote=_last_quote_epoch(root,symbol)
            if quote is None:
                audit.append({'symbol':symbol,'status':'NO_RECORDED_PIT_QUOTE'});continue
            try:
                segments,chunks=_verified_segments(root,db,symbol,'15')
                count_common=0;count_extra=0
                for i,seg in enumerate(segments):
                    # Exclude any candle not definitely CLOSED by a real observed quote.
                    closed=seg.loc[seg.timestamp+PERIOD<=quote].reset_index(drop=True)
                    c,e,_=_records_from_genuine_segment(symbol,i,closed)
                    count_common+=len(c);count_extra+=len(e)
                    if set(c)&set(common) or set(e)&(set(extra)|set(common)):
                        raise RuntimeError('DUPLICATE_RESEARCH_KEYS')
                    common.update(c);extra.update(e)
                audit.append({'symbol':symbol,'status':'VERIFIED_GENUINE_ARCHIVE',
                              'sha256_verified_chunks':chunks,'common_sample_ids':count_common,
                              'additional_v2_only_sample_ids':count_extra})
            except (ValueError,KeyError,TypeError,RuntimeError,OSError,OverflowError) as exc:
                # Never proceed with partial silently corrupted archive.
                return ResearchBundle({**base,'status':'SOURCE_AUDIT_FAILED',
                      'symbol':symbol,'reason_code':type(exc).__name__,'audit':audit},None,manifest)
        split=_choose_split(common,extra,validation_hours)
        summary={**base,'symbols':audit,'original_common_total':len(common),
                 'v2_only_total':len(extra),'source_manifest_sha256':_canonical_sha(manifest),
                 'sources':len(manifest)}
        if split is None:
            return ResearchBundle({**summary,'status':'INSUFFICIENT_GLOBAL_PURGED_GENUINE_SAMPLES',
                'reason':'No fixed global split has >=256 shared train, >=80 shared validation and >=1.2 train/validation ratio. No model trained.'},None,manifest)
        common_train=split['train_v1'];common_val=split['valid_v1'];extra_train=split['extra_train_v2']
        if [r['key'] for r in common_train]!=[r['key'] for r in split['train_v2']]:
            raise RuntimeError('UNPAIRED_TRAIN_SAMPLE_IDS')
        if [r['key'] for r in common_val]!=[r['key'] for r in split['valid_v2']]:
            raise RuntimeError('UNPAIRED_VALIDATION_SAMPLE_IDS')
        training_samples_signature=_canonical_sha({'train':_metadata_rows(common_train),
              'validation':_metadata_rows(common_val),'extra_v2_train':_metadata_rows(extra_train)})
        return ResearchBundle({**summary,'status':'RESEARCH_TRAINING_ELIGIBLE_NOT_TRADING_APPROVED',
             'validation_hours_effective':split['hours'],
             'global_cutoff_feature_epoch':split['cutoff'],
             'common_train_samples':len(common_train),'common_validation_samples':len(common_val),
             'v2_additional_train_samples':len(extra_train),
             'v2_additional_validation_samples_HELD_OUT_NOT_TRAINED':len(split['extra_valid_v2']),
             'shared_validation_and_sample_ids':True,
             'global_label_purge_verified':True,
             'split_sha256':training_samples_signature,
             'limitation':'Validation is used for epoch selection; not independent future OOS or economic PnL.'},split,manifest)
    finally:db.close()


def _fit_arm(architecture, train, valid, epochs, seed=20261022):
    torch=_torch()
    torch.manual_seed(seed)
    np.random.seed(seed)
    if torch.cuda.is_available():torch.cuda.manual_seed_all(seed)
    device='cuda' if torch.cuda.is_available() else 'cpu'
    X,y=_data_for_model(train);VX,Vy=_data_for_model(valid)
    model=build_model(architecture,CONTEXT,len(COLS),device)
    optim=torch.optim.AdamW(model.parameters(),lr=3e-4,weight_decay=1e-3)
    quant=torch.tensor([.1,.5,.9],device=device)
    best=float('inf');best_epoch=0;best_state=None;history=[]
    def batch_loss(xx,yy):
        pred=model(xx)
        error=yy[:,None]-pred
        return torch.maximum(quant*error,(quant-1)*error).mean()+0.05*torch.relu(pred[:,:2]-pred[:,1:]).mean()
    for ep in range(1,epochs+1):
        model.train();order=np.random.default_rng(seed+ep).permutation(len(X));total=0
        for st in range(0,len(X),64):
            ids=order[st:st+64];xx=torch.from_numpy(X[ids]).to(device);yy=torch.from_numpy(y[ids]).to(device)
            loss=batch_loss(xx,yy);optim.zero_grad(set_to_none=True);loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(),1.0);optim.step()
            total+=float(loss.detach().cpu())*len(ids)
        model.eval()
        with torch.no_grad():
            v_total=0
            for st in range(0,len(VX),128):
                xx=torch.from_numpy(VX[st:st+128]).to(device);yy=torch.from_numpy(Vy[st:st+128]).to(device)
                v_total+=float(batch_loss(xx,yy).cpu())*len(xx)
        vl=v_total/len(VX)
        history.append({'epoch':ep,'train_loss':total/len(X),'validation_pinball_with_crossing_penalty':vl})
        print(f'[Stage13] epoch={ep} train={total/len(X):.6f} shared_val={vl:.6f}',flush=True)
        if vl<best:
            best=vl;best_epoch=ep
            best_state={k:v.detach().cpu().clone() for k,v in model.state_dict().items()}
        if ep-best_epoch>=4:break
    return {'state_dict':best_state,'best_epoch':best_epoch,'validation_loss':best,'history':history,'device':device}


def train(root,architecture='patchtst',top=8,validation_hours=24,epochs=6):
    """Three-arm controlled experiment. Persists ONLY in isolated research directory."""
    require_mode(ExecutionMode.BACKTEST,permitted=(ExecutionMode.BACKTEST,),operation='train-challenger-v2')
    if architecture not in ('patchtst','itransformer'):raise ValueError('invalid research architecture')
    if not isinstance(epochs,int) or not 1<=epochs<=20:raise ValueError('epochs must be 1..20')
    bundle=prepare(root,top,validation_hours)
    if bundle.split is None:return {**bundle.public_report,'training_performed':False}
    split=bundle.split;valid=split['valid_v1']
    # No reliance on saved checkpoint provenance from the incumbent research Champion.
    # Arm 1 and 2 share all IDs, Arm 3 adds only V2-only TRAIN rows.
    arms=(('V1_COMMON',split['train_v1'],valid),
          ('V2_COMMON',split['train_v2'],split['valid_v2']),
          ('V2_EXPANDED',sorted(split['train_v2']+split['extra_train_v2'],key=lambda r:r['key']),split['valid_v2']))
    root=Path(root).resolve()
    folder=root/'research_challengers'/'stage13_paired_v2'/(
       time.strftime('%Y%m%dT%H%M%SZ',time.gmtime())+'_'+uuid.uuid4().hex[:8])
    torch=_torch()  # Dependency preflight before creating any output.
    folder.mkdir(parents=True,exist_ok=False)
    records=[]
    for name,tr,va in arms:
        print(f'[Stage13] {name}: train={len(tr)} shared_validation={len(va)}',flush=True)
        fit=_fit_arm(architecture,tr,va,epochs)
        model_file=folder/f'{name}.pt'
        metadata={**bundle.public_report,'arm':name,'architecture':architecture,
                  'epochs_requested':epochs,'best_epoch':fit['best_epoch'],
                  'training_examples':len(tr),'validation_examples':len(va),
                  'validation_loss':fit['validation_loss'],'training_history':fit['history'],
                  'device_used':fit['device'],
                  'checkpoint_kind':'NON_PROMOTABLE_RESEARCH_ONLY',
                  'model_feature_columns':COLS,'seed':20261022}
        torch.save({'state_dict':fit['state_dict'],'metadata':metadata},model_file)
        metadata['checkpoint_sha256']=hashlib.sha256(model_file.read_bytes()).hexdigest()
        (folder/f'{name}.json').write_text(json.dumps(metadata,indent=2,ensure_ascii=False),encoding='utf8')
        records.append({'arm':name,'samples':len(tr),'shared_validation_samples':len(va),
                        'best_epoch':fit['best_epoch'],'validation_loss':fit['validation_loss'],
                        'checkpoint_file':model_file.name,'checkpoint_sha256':metadata['checkpoint_sha256']})
    result={**bundle.public_report,'status':'COMPLETED_RESEARCH_ONLY_NOT_OOS_ECONOMICS',
            'training_performed':True,'arms':records,
            'output_dir':str(folder),'risk_or_champion_changed':False,
            'comparison_caveat':'Shared validation optimizes epochs and is not independent future OOS. Expanded arm has additional genuine training samples.'}
    (folder/'source_manifest.json').write_text(json.dumps(bundle.source_manifest,indent=2,ensure_ascii=False),encoding='utf8')
    (folder/'report.json').write_text(json.dumps(result,indent=2,ensure_ascii=False),encoding='utf8')
    return result
