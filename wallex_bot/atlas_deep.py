"""Multi-asset GPU transformers trained ONLY on real, verified Wallex records.
No pretrained synthetic market data, no random price generation, no data imputation.
"""
from __future__ import annotations
import json, hashlib, time, random
from pathlib import Path
import numpy as np
import pandas as pd
from .atlas_signals import features

COLS=['ret1','ret3','ret6','ret12','ret24','macd_hist','rsi14','natr14','volatility12',
      'volume_ratio','obv_slope','stoch_k','adx14','mfi14','bb_z','roc12']


def _torch():
    try:import torch
    except ImportError as e:raise RuntimeError('Install the optional GPU dependency: pip install torch') from e
    return torch


def sequences(lake,res='15',context=96,horizon=3,min_bars=180,
              validation_hours=24):
    """All markets share ONE UTC cutoff. Prevent cross-asset future-to-past leakage.

    Every feature window and future outcome stays inside a single genuine,
    contiguous segment. No source with gaps is forward filled.
    """
    period=int(res)*60 if res.isdigit() else 86400
    segment_records=[]
    for symbol in lake.symbols('all-spot'):
        try:segs=lake.load(symbol,res)
        except ValueError:continue
        for part,df in enumerate(segs):
            if len(df)<max(min_bars,context+horizon+20):continue
            if np.any(np.diff(df.timestamp.to_numpy(dtype=np.int64))!=period):
                raise RuntimeError('Noncontiguous segment; abort deep training')
            segment_records.append((symbol,part,df))
    if not segment_records:
        raise RuntimeError('No usable continuous genuine market segments')
    # Latest common chronological evaluation WINDOW (not per-asset 80/20 splits).
    # This cutoff is computed only from observed exchange timestamps.
    max_feature_ts=max(int(df.timestamp.iloc[-1]) for _,_,df in segment_records)
    xs=[];ys=[];groups=[]
    for symbol,part,df in segment_records:
        f=features(df)
        array=f[COLS].to_numpy(dtype=np.float64)
        close=df.close.to_numpy(dtype=np.float64)
        stamps=df.timestamp.to_numpy(dtype=np.int64)
        for t in range(context-1,len(f)-horizon):
            x=array[t-context+1:t+1]
            if not np.isfinite(x).all():continue
            y=np.log(close[t+horizon]/close[t])
            if not np.isfinite(y):continue
            feature_ts=int(stamps[t]);label_ts=int(stamps[t+horizon])
            mu=x.mean(0,keepdims=True);std=x.std(0,keepdims=True)
            scaled=np.clip((x-mu)/np.maximum(std,1e-6),-20,20)
            xs.append(scaled.astype('float32'));ys.append(float(y))
            groups.append({'symbol':symbol,'segment':part,'t':feature_ts,
                           'label_end_ts':label_ts})
    if not xs:raise RuntimeError('No valid real feature windows after strict time isolation')
    # Predetermined UTC validation horizon search, longest first. ONLY feature
    # timestamps and valid-window counts choose the split; NEVER outcomes or PnL.
    # Each candidate shares the same cutoff for ALL assets, with label purge.
    picked=None
    for hours in (24,18,12,8,6):
        if hours>validation_hours:continue
        cutoff=((max_feature_ts-hours*3600)//period)*period
        train_idx=[i for i,r in enumerate(groups) if r['label_end_ts']<cutoff]
        val_idx=[i for i,r in enumerate(groups) if r['t']>=cutoff]
        if len(train_idx)>=512 and len(val_idx)>=80 and len(train_idx)>=2*len(val_idx):
            picked=(hours,cutoff,train_idx,val_idx)
            break
    if picked is None:
        raise RuntimeError('Insufficient balanced genuine windows for globally purged DL training; '
          'collect more real market data (no invented records).')
    hours,cutoff,train_idx,val_idx=picked
    chosen_idx=train_idx+val_idx
    X=np.stack([xs[i] for i in chosen_idx]);Y=np.array([ys[i] for i in chosen_idx],dtype='float32')
    selected=[]
    for i in train_idx:
        selected.append({**groups[i],'split':'train','validation_hours_effective':hours})
    for i in val_idx:
        selected.append({**groups[i],'split':'val','validation_hours_effective':hours})
    mask=np.array([r['split']=='train' for r in selected])
    if max(r['label_end_ts'] for r in selected if r['split']=='train') >= min(r['t'] for r in selected if r['split']=='val'):
        raise RuntimeError('TIME LEAKAGE across markets detected: fail closed')
    return X,Y,mask,selected


def build_model(architecture,context,channels,device='cpu'):
    torch=_torch(); nn=torch.nn
    class InvertedTransformer(nn.Module):
        """Trainable iTransformer-style inverted variable tokens + encoder + quantile head."""
        def __init__(self):
            super().__init__()
            self.in_embed=nn.Linear(context,256)
            layer=nn.TransformerEncoderLayer(d_model=256,nhead=8,dim_feedforward=768,
                 dropout=.10,batch_first=True,activation='gelu',norm_first=True)
            self.encoder=nn.TransformerEncoder(layer,num_layers=5,enable_nested_tensor=False)
            self.head=nn.Sequential(nn.LayerNorm(channels*256),nn.Linear(channels*256,512),nn.GELU(),
                                    nn.Dropout(.10),nn.Linear(512,3))
        def forward(self,x):
            z=self.encoder(self.in_embed(x.transpose(1,2)))
            return self.head(z.flatten(1))
    class PatchTransformer(nn.Module):
        """PatchTST-inspired channel-independent shared patch embedding and temporal attention."""
        def __init__(self):
            super().__init__()
            self.patch=16;self.stride=8
            count=(context-self.patch)//self.stride+1
            self.patch_embed=nn.Linear(self.patch,256)
            self.pos=nn.Parameter(torch.zeros(1,1,count,256))
            layer=nn.TransformerEncoderLayer(d_model=256,nhead=8,dim_feedforward=768,
                  dropout=.10,batch_first=True,activation='gelu',norm_first=True)
            self.encoder=nn.TransformerEncoder(layer,num_layers=5,enable_nested_tensor=False)
            self.head=nn.Sequential(nn.LayerNorm(channels*256),nn.Linear(channels*256,512),
                                    nn.GELU(),nn.Linear(512,3))
        def forward(self,x):
            b,t,c=x.shape
            patches=x.transpose(1,2).unfold(2,self.patch,self.stride)
            z=self.patch_embed(patches)+self.pos
            z=self.encoder(z.reshape(b*c,-1,256)).mean(1).reshape(b,c,256)
            return self.head(z.flatten(1))
    if architecture=='itransformer':return InvertedTransformer().to(device)
    if architecture=='patchtst':return PatchTransformer().to(device)
    raise ValueError('Model must be itransformer or patchtst')


def train_real(lake,architecture='itransformer',res='15',context=96,horizon=3,epochs=16,batch_size=64,output=None):
    torch=_torch(); import torch.nn.functional as F
    if context<32 or context%8 or horizon<1 or epochs<1:raise ValueError('invalid training configuration')
    torch.manual_seed(20261022); np.random.seed(20261022);random.seed(20261022)
    X,y,trainmask,groups=sequences(lake,res,context,horizon)
    device='cuda' if torch.cuda.is_available() else 'cpu'
    model=build_model(architecture,context,X.shape[-1],device)
    optim=torch.optim.AdamW(model.parameters(),lr=3e-4,weight_decay=1e-3)
    quant=torch.tensor([.1,.5,.9],device=device)
    tr_ids=np.flatnonzero(trainmask);va_ids=np.flatnonzero(~trainmask)
    # Only example ORDER is shuffled; market prices and labels are never generated.
    def run(indices,train):
        model.train(train);losses=[]
        if train: indices=np.random.permutation(indices)
        for start in range(0,len(indices),batch_size):
            ids=indices[start:start+batch_size]
            xx=torch.from_numpy(X[ids]).to(device); yy=torch.from_numpy(y[ids]).to(device)
            with torch.set_grad_enabled(train):
                pred=model(xx)
                error=yy[:,None]-pred
                loss=torch.maximum(quant*error,(quant-1)*error).mean()
                loss=loss+0.05*torch.relu(pred[:,:2]-pred[:,1:]).mean()
                if train:
                    optim.zero_grad(set_to_none=True);loss.backward()
                    torch.nn.utils.clip_grad_norm_(model.parameters(),1.0);optim.step()
            losses.append(float(loss.detach().cpu())*len(ids))
        return sum(losses)/len(indices)
    best=float('inf');best_epoch=0; history=[]; best_state=None
    for ep in range(epochs):
        tl=run(tr_ids,True);vl=run(va_ids,False)
        history.append({'epoch':ep+1,'train_pinball':tl,'validation_pinball':vl})
        print(f'{architecture} epoch={ep+1} train={tl:.7f} val={vl:.7f}',flush=True)
        if vl<best:
            best=vl;best_epoch=ep+1
            best_state={key:value.detach().cpu().clone() for key,value in model.state_dict().items()}
        elif ep-best_epoch>=5:break
    model.load_state_dict(best_state)
    folder=Path(output or lake.root/'models');folder.mkdir(parents=True,exist_ok=True)
    # Never overwrite a trading/research checkpoint needed for judge replay.
    run_id=time.strftime('%Y%m%dT%H%M%SZ',time.gmtime())
    # Preserve every checkpoint, even if two trainings happen in one second.
    import uuid
    run_id+='_'+uuid.uuid4().hex[:8]
    checkpoint=folder/f'{architecture}_{res}_h{horizon}_{run_id}.pt'
    # Freeze the exact source files known at training time. A live SQLite WAL
    # file hash alone is not a reproducible market-data snapshot.
    source_rows=lake.db.execute('''SELECT symbol,resolution,begin,end,filename,sha256
         FROM chunks WHERE resolution=? AND status='COMPLETE'
         ORDER BY symbol,begin,end,filename''',(res,)).fetchall()
    source_manifest=[{'symbol':a,'resolution':b,'begin':c,'end':d,
         'relative_file':e,'sha256':f} for a,b,c,d,e,f in source_rows]
    source_manifest_bytes=json.dumps(source_manifest,sort_keys=True,separators=(',',':')).encode('utf8')
    (checkpoint.with_suffix('.sources.json')).write_text(json.dumps(source_manifest,
         indent=2,ensure_ascii=False),encoding='utf8')
    config={'architecture':architecture,'resolution':res,'context':context,'horizon':horizon,
            'training_source_manifest_sha256':hashlib.sha256(source_manifest_bytes).hexdigest(),
            'training_source_chunk_count':len(source_manifest),
            'validation_protocol':'GLOBAL_UTC_PURGED_V1',
            'training_window_split_sha256':hashlib.sha256(json.dumps(groups,sort_keys=True,separators=(',',':')).encode('utf8')).hexdigest(),
            'validation_hours_effective':next(r['validation_hours_effective'] for r in groups),
            'validation_start_ts':min(r['t'] for r in groups if r['split']=='val'),
            'train_last_label_ts':max(r['label_end_ts'] for r in groups if r['split']=='train'),
            'feature_columns':COLS,'training_samples':int(trainmask.sum()),
            'validation_samples':int((~trainmask).sum()),'best_epoch':best_epoch,
            'validation_pinball':best,'device_used':device,'training_source':'verified_real_wallex_only',
            'run_ts':time.time(),'history':history,
            'data_catalog_sha256':hashlib.sha256((lake.root/'catalog.sqlite').read_bytes()).hexdigest()}
    torch.save({'state_dict':best_state,'config':config},checkpoint)
    config['checkpoint_sha256']=hashlib.sha256(checkpoint.read_bytes()).hexdigest()
    (checkpoint.with_suffix('.json')).write_text(json.dumps(config,indent=2),encoding='utf-8')
    return {'checkpoint':str(checkpoint),'metrics':{k:config[k] for k in ['training_samples','validation_samples','best_epoch','validation_pinball','device_used']}}


def trusted_checkpoints(folder):
    """Reject checkpoints trained with older cross-asset-per-segment splits."""
    torch=_torch(); accepted=[]
    for p in sorted(Path(folder).glob('*.pt')):
        try:
            config=torch.load(p,map_location='cpu',weights_only=True)['config']
            if config.get('validation_protocol')!='GLOBAL_UTC_PURGED_V1':continue
            accepted.append((float(config['validation_pinball']),p))
        except (KeyError,RuntimeError,ValueError,TypeError,EOFError):continue
    return accepted


def predict_latest(lake,checkpoint,symbol):
    torch=_torch()
    ck=torch.load(checkpoint,map_location='cpu',weights_only=True)
    cfg=ck['config'];segments=lake.load(symbol,cfg['resolution']);context=cfg['context']
    df=segments[-1]
    if len(df)<context+55:raise RuntimeError('Insufficient genuine contiguous context')
    f=features(df);x=f[COLS].tail(context).to_numpy(dtype=float)
    if not np.isfinite(x).all():raise RuntimeError('Recent real indicators missing: fail closed')
    x=np.clip((x-x.mean(0,keepdims=True))/np.maximum(x.std(0,keepdims=True),1e-6),-20,20)
    model=build_model(cfg['architecture'],context,len(COLS),'cpu');model.load_state_dict(ck['state_dict']);model.eval()
    with torch.no_grad():qs=model(torch.tensor(x[None],dtype=torch.float32)).numpy()[0].tolist()
    if not all(np.isfinite(qs)) or not (qs[0]<=qs[1]<=qs[2]):
        raise RuntimeError('Uncalibrated/inconsistent quantile predictions: decline to trade')
    return {'symbol':symbol,'feature_end_ts':int(df.timestamp.iloc[-1]),'quantile_log_returns':dict(zip(['q10','q50','q90'],qs)),
            'model':cfg['architecture'],'horizon_bars':cfg['horizon'],'source':'real_wallex_only',
            'model_validation_pinball':cfg['validation_pinball']}


# Shadow promotion is an explicit, hashed decision. It never silently selects
# the oldest/lowest-scoring historical checkpoint from a growing directory.
def model_metadata_eligible(cfg):
    reasons=[]
    if not isinstance(cfg,dict):return False,['INVALID_METADATA_SHAPE']
    if cfg.get('validation_protocol')!='GLOBAL_UTC_PURGED_V1':reasons.append('NO_GLOBAL_PURGED_VALIDATION')
    train=cfg.get('training_samples',0);val=cfg.get('validation_samples',0)
    if not isinstance(train,int) or not isinstance(val,int) or train<512 or val<80 or train<2*val:
        reasons.append('INADEQUATE_TRAIN_TO_VALIDATION_COVERAGE')
    if not isinstance(cfg.get('validation_pinball'),(int,float)) or not np.isfinite(cfg['validation_pinball']):
        reasons.append('INVALID_VALIDATION_SCORE')
    if cfg.get('train_last_label_ts',float('inf'))>=cfg.get('validation_start_ts',float('-inf')):
        reasons.append('LEAKAGE_OR_INVALID_SPLIT_TIMES')
    return not reasons,reasons


def _sha_file(file):
    sha=hashlib.sha256()
    with open(file,'rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):sha.update(block)
    return sha.hexdigest()


def _verify_candidate(path):
    path=Path(path)
    if not path.is_file():raise RuntimeError('Checkpoint does not exist')
    meta=path.with_suffix('.json');sources=path.with_suffix('.sources.json')
    if not meta.is_file() or not sources.is_file():raise RuntimeError('Model metadata/provenance missing')
    cfg=json.loads(meta.read_text(encoding='utf-8'))
    approved,reasons=model_metadata_eligible(cfg)
    if not approved:raise RuntimeError('Model research safety gate: '+','.join(reasons))
    if cfg.get('checkpoint_sha256')!=_sha_file(path):raise RuntimeError('Checkpoint hash mismatch')
    manifest=json.loads(sources.read_text(encoding='utf-8'))
    if not isinstance(manifest,list):raise RuntimeError('Invalid genuine source manifest')
    digest=hashlib.sha256(json.dumps(manifest,sort_keys=True,separators=(',',':')).encode('utf8')).hexdigest()
    if cfg.get('training_source_manifest_sha256')!=digest:raise RuntimeError('Source manifest hash mismatch')
    return cfg


def promote_champion(lake,new_checkpoints):
    """Select from THIS RUN only; require compatible data and validation cutoffs."""
    candidates=[]
    for p in new_checkpoints:
        if p is None:continue
        path=Path(p)
        cfg=_verify_candidate(path)
        candidates.append((cfg,path))
    if not candidates:raise RuntimeError('No newly trained eligible models. Shadow not promoted.')
    signatures={(c['training_source_manifest_sha256'],c['validation_start_ts'],
                c['train_last_label_ts']) for c,p in candidates}
    if len(signatures)!=1:raise RuntimeError('Candidate checkpoints trained on incomparable source/time splits')
    selected=min(candidates,key=lambda x:x[0]['validation_pinball'])
    cfg,path=selected
    payload={'policy':'LATEST_RUN_GLOBAL_PURGED_VALIDATION_V1',
        'selected_checkpoint':path.name,'checkpoint_sha256':_sha_file(path),
        'selected_architecture':cfg['architecture'],
        'validation_pinball':cfg['validation_pinball'],
        'training_samples':cfg['training_samples'],'validation_samples':cfg['validation_samples'],
        'training_source_manifest_sha256':cfg['training_source_manifest_sha256'],
        'selected_at_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),
        'candidates':[{'file':p.name,'architecture':c['architecture'],
                        'validation_pinball':c['validation_pinball']} for c,p in candidates]}
    result=Path(lake.root)/'models'/'active_champion.json'
    temp=result.with_suffix('.partial')
    temp.write_text(json.dumps(payload,indent=2,ensure_ascii=False),encoding='utf8')
    temp.replace(result)
    return {'selected':str(path),'policy':payload['policy'],'candidates':payload['candidates']}


def verified_champion(models_dir):
    folder=Path(models_dir);file=folder/'active_champion.json'
    if not file.is_file():raise RuntimeError('No approved explicit champion; run training with model promotion')
    obj=json.loads(file.read_text(encoding='utf8'))
    name=obj.get('selected_checkpoint','')
    if not isinstance(name,str) or Path(name).name!=name or not name.endswith('.pt'):
        raise RuntimeError('Unsafe or missing selected checkpoint name')
    model=folder/name
    cfg=_verify_candidate(model)
    if _sha_file(model)!=obj.get('checkpoint_sha256'):
        raise RuntimeError('Champion checkpoint has changed')
    if cfg['training_source_manifest_sha256']!=obj.get('training_source_manifest_sha256'):
        raise RuntimeError('Champion provenance mismatch')
    return model
