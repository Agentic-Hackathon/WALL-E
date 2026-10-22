"""M6 genuine prospective observation, isolated from any broker authority.

Reuses ForwardLedger real-quote receipts and M5 model artifacts. Conceptual
references: Hindsight leakage audit, Freqtrade prefix checks, Hummingbot durable
identity/reconciliation; original code only (see SOURCES.md). No fake outcomes.
"""
from __future__ import annotations
import json,math,sqlite3,time,uuid,hashlib
from pathlib import Path
from datetime import datetime,timezone
import numpy as np
from .atlas_forward import ForwardLedger,_sha,_canon
from .atlas_deep import COLS,verified_champion,build_model
from .atlas_signals import features
from .atlas_m5_models import make_model
from .atlas_m5_research import load_bundle

M5=Path('atlas_store/research_challengers/milestone5/m5_20261022_frozen_v1')
MODEL_NAMES=('champion','m5_lightgbm','m5_patchtst','zero','historical_quantiles')
HORIZON=2700
QUOTE_TOLERANCE=300

def model_registry(root,m5=M5):
    import torch
    root=Path(root);m5=Path(m5);selection=json.loads((m5/'research_selection.json').read_text())
    checkpoint=m5/Path(selection['directory']).name/'best.pt';result=json.loads((checkpoint.parent/'result.json').read_text())
    if hashlib.sha256(checkpoint.read_bytes()).hexdigest()!=selection['checkpoint_sha256']:raise ValueError('M5_PATCH_CHECKPOINT_CHANGED')
    active=verified_champion(root/'models');cfg=torch.load(active,map_location='cpu',weights_only=True)['config']
    if cfg['resolution']!='15' or int(cfg['horizon'])!=3 or int(cfg['context'])!=96:raise ValueError('UNSUPPORTED_CHAMPION_HORIZON_NO_REINTERPRETATION')
    boosters=[m5/'baselines'/f'lightgbm_q{q}.txt' for q in (.1,.5,.9)]
    receipts={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in boosters}
    # Match M5's immutable delivered manifest, not just whatever is on disk now.
    frozen=json.loads(Path('reports/m5_artifact_manifest.json').read_text())
    expected={r['relative_path']:r['sha256'] for r in frozen['files']}
    for path,digest in receipts.items():
        if expected.get(str(Path(path).relative_to(m5)))!=digest:raise ValueError('M5_LIGHTGBM_ARTIFACT_CHANGED')
    bundle=load_bundle(m5/'dataset_15_0.75')
    from .atlas_m5_data import digest
    if digest(bundle.rows)!=result['config']['dataset_sha256']:raise ValueError('M5_TRAINING_SOURCE_CHANGED')
    y=np.array([r['y'] for r in bundle.rows]);historical=np.quantile(y[bundle.split['indices']['train']],[.1,.5,.9])
    common={'forecast_horizon':HORIZON,'trained_target':'CLOSE_TO_CLOSE_RETURN','authority':'OBSERVATION_ONLY_NO_BROKER',
        'promotion':False,'training_partition':'historical M5 four-way split, NOT prospective evidence'}
    return {
        'champion':{**common,'path':str(active),'model_sha256':hashlib.sha256(active.read_bytes()).hexdigest(),'model_version':cfg['architecture'],'config':cfg,'recipe':'UNCHANGED_CHAMPION_16_V1',
            'training_partition':'existing Champion GLOBAL_UTC_PURGED_V1, not M5 training'},
        'm5_lightgbm':{**common,'paths':[str(p) for p in boosters],'model_sha256':_sha(receipts),'model_version':'M5_LIGHTGBM_QUANTILES_RAW','recipe':'M5_A_21_V1','receipts':receipts},
        'm5_patchtst':{**common,'path':str(checkpoint),'model_sha256':selection['checkpoint_sha256'],'model_version':'M5_PATCHTST_ORDERED_RAW','config':result['config'],'recipe':'M5_A_21_V1'},
        'zero':{**common,'model_sha256':_sha({'rule':'constant zero log-return','horizon':HORIZON}),'model_version':'ZERO_PERSISTENCE_V1','recipe':'NO_IMPUTATION_CONSTANT_FORECAST','constant':[0.,0.,0.]},
        'historical_quantiles':{**common,'model_sha256':_sha({'training_dataset':bundle.config['dataset_sha256'],'quantiles':historical.tolist()}),'model_version':'TRAIN_ONLY_HISTORICAL_QUANTILES_V1','recipe':'TRAIN_LABEL_DISTRIBUTION','constant':historical.tolist()}}

def input_snapshot(lake,symbol,now=None):
    from .atlas_feature_health import _verified_segments
    now=float(time.time() if now is None else now)
    if lake.db.in_transaction:raise RuntimeError('MODEL_SNAPSHOT_REQUIRES_OWN_READ_TRANSACTION')
    lake.db.execute('BEGIN')
    try:
        segments,_=_verified_segments(lake.root,lake.db,symbol,'15')
        sources=[{'file':f,'sha256':sha} for f,sha in lake.db.execute("SELECT filename,sha256 FROM chunks WHERE symbol=? AND resolution='15' AND status='COMPLETE' ORDER BY filename",(symbol,))]
    finally:lake.db.rollback()
    closed=[s[s.timestamp.astype('int64')+900<=now] for s in segments]
    closed=[s for s in closed if len(s)]
    if not closed or len(closed[-1])<151:raise ValueError('INSUFFICIENT_REAL_CONTIGUOUS_CONTEXT')
    frame=closed[-1];cutoff=int(frame.timestamp.iloc[-1])+900
    if now-cutoff>1800:raise ValueError('STALE_REAL_CONTEXT')
    v1=features(frame)[COLS].tail(96).to_numpy(float)
    core=np.column_stack([np.log(frame[k].tail(96).to_numpy(float)) for k in ('open','high','low','close')]+[np.log1p(frame.volume.tail(96).to_numpy(float))])
    core[:,:4]-=float(np.log(frame.close.iloc[-1]))  # Exact M5-A transform.
    joined=np.column_stack([core,v1])
    if not np.isfinite(joined).all():raise ValueError('NONFINITE_REAL_CONTEXT')
    normalize=lambda x:np.clip((x-x.mean(0))/np.maximum(x.std(0),1e-6),-20,20).astype('float32')
    return {'cutoff':cutoff,'champion':normalize(v1),'research':normalize(joined),
        'source_receipts':sources,'source_sha256':_sha(sources),'input_sha256':hashlib.sha256(joined.tobytes()).hexdigest(),
        'verified_available_at':time.time(),'legacy_policy':'Verified actual bytes observed NOW; no historical receipt time is inferred'}

def predict_models(registry,snapshot):
    import torch
    from lightgbm import Booster
    torch.set_num_threads(2);outputs={};errors={}
    for name,meta in registry.items():
        try:
            if 'constant' in meta:pred=np.array(meta['constant'])
            elif name=='m5_lightgbm':
                pred=np.array([Booster(model_file=p).predict(snapshot['research'][-1:])[0] for p in meta['paths']])
            else:
                cfg=meta['config'];state=torch.load(meta['path'],map_location='cpu',weights_only=True)
                if hashlib.sha256(Path(meta['path']).read_bytes()).hexdigest()!=meta['model_sha256']:raise ValueError('MODEL_HASH_CHANGED')
                if name=='champion':
                    model=build_model(cfg['architecture'],96,16,'cpu');x=snapshot['champion'];model.load_state_dict(state['state_dict'])
                else:
                    model=make_model(cfg['architecture'],96,21,cfg['head'],'cpu');x=snapshot['research'];model.load_state_dict(state['state_dict'])
                model.eval()
                with torch.inference_mode():pred=model(torch.from_numpy(x[None])).numpy()[0]
                if name!='champion':pred=pred*cfg['target_scale']+cfg['target_mean']
            if not np.isfinite(pred).all() or not (pred[0]<=pred[1]<=pred[2]):raise ValueError('NONFINITE_OR_CROSSING_FORECAST')
            outputs[name]=[float(x) for x in pred]
        except Exception as exc:errors[name]=type(exc).__name__+':'+str(exc)[:100]
    return outputs,errors

class ModelObservationLedger:
    def __init__(self,root):
        self.root=Path(root).resolve();self.forward=ForwardLedger(self.root);self.db=self.forward.db;self.owner=uuid.uuid4().hex
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS m6_lease(name TEXT PRIMARY KEY,owner TEXT NOT NULL,expires REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS m6_predictions(prediction_id TEXT PRIMARY KEY,symbol TEXT NOT NULL,model TEXT NOT NULL,
            decision REAL NOT NULL,cutoff INTEGER NOT NULL,due REAL NOT NULL,quote_id INTEGER NOT NULL,
            model_sha TEXT NOT NULL,status TEXT NOT NULL,payload TEXT NOT NULL,payload_sha TEXT NOT NULL,
            UNIQUE(symbol,model_sha,cutoff));
        CREATE TABLE IF NOT EXISTS m6_outcomes(prediction_id TEXT PRIMARY KEY,future_quote_id INTEGER NOT NULL,
            payload TEXT NOT NULL,payload_sha TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS m6_cycles(id INTEGER PRIMARY KEY,created REAL NOT NULL,payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS m6_session(key TEXT PRIMARY KEY,payload TEXT NOT NULL);
        ''');self.db.commit()
    def claim(self):
        self.db.execute('BEGIN IMMEDIATE')
        try:
            row=self.db.execute("SELECT owner,expires FROM m6_lease WHERE name='collector'").fetchone()
            if row and row[0]!=self.owner and row[1]>time.time():self.db.rollback();return False
            self.db.execute("INSERT OR REPLACE INTO m6_lease VALUES('collector',?,?)",(self.owner,time.time()+600));self.db.commit();return True
        except Exception:self.db.rollback();raise
    def release(self):
        with self.db:self.db.execute("DELETE FROM m6_lease WHERE name='collector' AND owner=?",(self.owner,))
    def quote(self,quote_id):
        row=self.db.execute('SELECT symbol,observed_epoch,best_bid,best_ask,mid,raw_book,receipt_sha256 FROM quotes WHERE id=?',(quote_id,)).fetchone()
        if not row:raise ValueError('REAL_QUOTE_REQUIRED')
        payload=dict(zip(('symbol','observed_epoch','best_bid','best_ask','mid','raw_book'),row[:-1]));payload['raw_book']=json.loads(payload['raw_book'])
        if _sha(payload)!=row[-1]:raise ValueError('REAL_QUOTE_HASH_MISMATCH')
        return {**payload,'receipt_sha256':row[-1]}
    def register(self,symbol,registry,snapshot,outputs,quote_id,fee=.001):
        quote=self.quote(quote_id);decision=time.time();count=0
        if not isinstance(fee,(float,int)) or not math.isfinite(fee) or not 0<=fee<.05:raise ValueError('EXPLICIT_ASSUMED_FEE_REQUIRED')
        if symbol!=quote['symbol'] or not 0<=decision-quote['observed_epoch']<=60:raise ValueError('NO_FRESH_REAL_QUOTE')
        if snapshot['verified_available_at']>decision or snapshot['cutoff']>decision or decision-snapshot['cutoff']>1800:raise ValueError('NO_CURRENT_OBSERVABLE_INPUT')
        for name,q in outputs.items():
            meta=registry[name]
            if meta['forecast_horizon']!=HORIZON or len(q)!=3 or not np.isfinite(q).all() or list(q)!=sorted(q):raise ValueError('INVALID_REGISTERED_FORECAST')
            key=_sha({'symbol':symbol,'model':meta['model_sha256'],'cutoff':snapshot['cutoff']})
            payload={'prediction_id':key,'model_sha256':meta['model_sha256'],'model_version':meta['model_version'],
                'symbol':symbol,'decision_time':decision,'observed_quote_time':quote['observed_epoch'],'data_cutoff':snapshot['cutoff'],
                'feature_recipe':meta['recipe'],'forecast_horizon':HORIZON,'q10':q[0],'q50':q[1],'q90':q[2],
                'expected_cost':{'fee_per_side_assumed':fee,'fee_verified':False,'spread_bps_observed':(quote['best_ask']-quote['best_bid'])/quote['mid']*10000,
                    'slippage_assumption':'top-of-book counterfactual only, no guaranteed fill'},
                'data_quality_status':'ACTUAL_BYTES_VERIFIED_BEFORE_CURRENT_DECISION','prediction_available_at':decision,
                'source_receipts':snapshot['source_receipts'],'input_sha256':snapshot['input_sha256'],
                'input_verified_available_at':snapshot['verified_available_at'],'target_units':'NATURAL_LOG_RETURN',
                'trained_target':'CLOSE_TO_CLOSE_RETURN','model_target_end':snapshot['cutoff']+HORIZON,
                'evaluated_target':'MID_TO_MID_RETURN_QUOTE_PROXY','quote_due':decision+HORIZON,
                'quote_tolerance_seconds':QUOTE_TOLERANCE,'origin_quote_sha256':quote['receipt_sha256'],
                'alignment_warning':'Quote-origin proxy differs from candle-close training target; not calibrated executable return'}
            with self.db:
                cursor=self.db.execute('INSERT OR IGNORE INTO m6_predictions VALUES(?,?,?,?,?,?,?,?,?,?,?)',(key,symbol,name,decision,snapshot['cutoff'],decision+HORIZON,quote_id,meta['model_sha256'],'PENDING',_canon(payload),_sha(payload)))
                count+=cursor.rowcount
        return count
    def reconcile(self,now=None):
        now=float(time.time() if now is None else now)
        if now>time.time()+1:raise ValueError('CANNOT_ADVANCE_OBSERVATION_CLOCK')
        scored=0
        for key,symbol,due,origin_id,raw,sha in self.db.execute("SELECT prediction_id,symbol,due,quote_id,payload,payload_sha FROM m6_predictions WHERE status IN ('PENDING','UNSCORED_NO_REAL_FUTURE_QUOTE') AND due<=?",(now,)).fetchall():
            p=json.loads(raw)
            if _sha(p)!=sha:raise ValueError('FORECAST_RECEIPT_HASH_MISMATCH')
            future=self.db.execute('SELECT id FROM quotes WHERE symbol=? AND observed_epoch>=? AND observed_epoch<=? ORDER BY observed_epoch,id LIMIT 1',(symbol,due,min(now,due+QUOTE_TOLERANCE))).fetchone()
            if not future:
                if now>due+QUOTE_TOLERANCE:
                    with self.db:self.db.execute("UPDATE m6_predictions SET status='UNSCORED_NO_REAL_FUTURE_QUOTE' WHERE prediction_id=?",(key,))
                continue
            origin=self.quote(origin_id);later=self.quote(future[0]);fee=p['expected_cost']['fee_per_side_assumed']
            actual=math.log(later['mid']/origin['mid']);net=math.log(later['best_bid']/origin['best_ask'])+math.log1p(-fee)-math.log1p(fee)
            result={'MID_TO_MID_RETURN':actual,'ASK_TO_FUTURE_BID_NET_PROXY':net,'POSITIVE_AFTER_COST_OPPORTUNITY':net>0,
                'CLOSE_TO_CLOSE_RETURN':None,'cost_status':'ASSUMED_NOT_VERIFIED','realized_PnL':None,
                'origin_sha256':origin['receipt_sha256'],'future_sha256':later['receipt_sha256'],
                'future_observed_epoch':later['observed_epoch'],'available_at':time.time(),
                'target_alignment':'quote proxy, not candle target or fill','quantiles':[p['q10'],p['q50'],p['q90']]}
            with self.db:
                self.db.execute('INSERT OR IGNORE INTO m6_outcomes VALUES(?,?,?,?)',(key,future[0],_canon(result),_sha(result)))
                self.db.execute("UPDATE m6_predictions SET status='SCORED_REAL_FUTURE_QUOTE' WHERE prediction_id=?",(key,))
            scored+=1
        return {'scored_now':scored,'advance_clock':False}
    def status(self):
        span=self.db.execute('SELECT min(observed_epoch),max(observed_epoch),count(*) FROM quotes').fetchone()
        return {'forecast_statuses':dict(self.db.execute('SELECT status,count(*) FROM m6_predictions GROUP BY status')),
            'by_model':dict(self.db.execute('SELECT model,count(*) FROM m6_predictions GROUP BY model')),
            'quote_count':span[2],'first_quote':span[0],'last_quote':span[1],'observed_span_hours':(span[1]-span[0])/3600 if span[0] is not None else 0,
            'matured_scored':self.db.execute('SELECT count(*) FROM m6_outcomes').fetchone()[0],
            'status':'PENDING_48_72H_REAL_OBSERVATION','orders':'NO_INTERFACE'}
    def evaluation(self):
        """Score matched actual quote proxies; no test-selected model ranking."""
        from .atlas_m5_models import metrics,QUANT
        cohorts={}
        for symbol,model,raw,raw_outcome,sha in self.db.execute('''SELECT p.symbol,p.model,p.payload,o.payload,o.payload_sha
            FROM m6_predictions p JOIN m6_outcomes o ON p.prediction_id=o.prediction_id'''):
            p=json.loads(raw);outcome=json.loads(raw_outcome)
            if _sha(outcome)!=sha:raise ValueError('OUTCOME_HASH_MISMATCH')
            cohorts.setdefault((symbol,p['decision_time']),{})[model]=(p,outcome)
        shared={key:value for key,value in cohorts.items() if set(MODEL_NAMES)<=set(value)}
        report={'track':'PROSPECTIVE_REAL_MID_QUOTE_PROXY_NOT_CANDLE_TARGET_OR_PNL',
            'matched_all_five_cohorts':len(shared),'matured_partial_cohorts':len(cohorts)-len(shared),
            'status':'EARLY_QUOTE_PROXY_DIAGNOSTIC_NOT_48H_EVIDENCE' if shared else 'PENDING_NO_SHARED_MATURED_QUOTES',
            'per_model':{},'per_symbol':{},'block_aware':{},'model_selection_or_promotion':False,
            'multiple_testing':'All five predeclared models retained; no significance or superiority claim on a short window'}
        if not shared:return report
        keys=sorted(shared,key=lambda key:(key[1],key[0]));first=keys[0][1]
        for model in MODEL_NAMES:
            actual=np.array([shared[k][model][1]['MID_TO_MID_RETURN'] for k in keys]);pred=np.array([[shared[k][model][0][q] for q in ('q10','q50','q90')] for k in keys])
            report['per_model'][model]=metrics(actual,pred)
            for symbol in sorted({k[0] for k in keys}):
                ids=[i for i,k in enumerate(keys) if k[0]==symbol]
                report['per_symbol'][symbol+'|'+model]=metrics(actual[ids],pred[ids])
            loss=np.maximum(QUANT*(actual[:,None]-pred),(QUANT-1)*(actual[:,None]-pred)).mean(1)
            bins=np.array([int((k[1]-first)//HORIZON) for k in keys])
            blocks=[float(loss[bins==b].mean()) for b in sorted(set(bins))]
            report['block_aware'][model]={'block_seconds':HORIZON,'time_blocks':len(blocks),'equal_block_pinball':float(np.mean(blocks)),
                'block_pinball':blocks,'cross_asset_dependence_not_independent':True,'confidence_interval':None}
        return report
    def close(self):self.forward.close()
