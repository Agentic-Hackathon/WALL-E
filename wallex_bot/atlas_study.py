"""M7 fixed-protocol foreground study with independent deadline quote worker.

Reuses M6 ModelObservationLedger, DataSync, actual depth receipts and the
unchanged Agent/ShadowBroker/RiskGate. Concept-only reference patterns from
Hummingbot/Nautilus/Freqtrade/FinRL are audited in SOURCES.md; no code copied.
"""
from __future__ import annotations
import argparse,hashlib,json,sqlite3,threading,time,subprocess
from pathlib import Path
from types import SimpleNamespace
from dataclasses import asdict
from .atlas_forward import _sha,_canon
from .atlas_prospective import ModelObservationLedger,model_registry,input_snapshot,predict_models
from .atlas_liquidation import _save_atomic,liquidate_paper_positions
from .atlas_portfolio import allocate,AllocationLimits,METHODS
from .atlas_risk import RiskGate

DEFAULT_SESSION='atlas_store/research_challengers/milestone7/formal_48h_v1'

def source_manifest(workspace=None):
    workspace=Path(workspace or Path(__file__).resolve().parents[1]).resolve()
    files=set((workspace/'wallex_bot').rglob('*.py'))
    files.update((workspace/'wallex_bot').rglob('*.md'));files.update(workspace.glob('requirements*.txt'))
    files.update(p for p in (workspace/'scripts').rglob('*') if p.is_file() and p.suffix in ('.py','.sh','.ps1'))
    files.add(workspace/'third_party/SOURCES.md')
    return {str(p.relative_to(workspace)):hashlib.sha256(p.read_bytes().replace(b'\r\n',b'\n')).hexdigest() for p in sorted(files) if '__pycache__' not in p.parts}

def settings(symbols=('BTCTMN','PEPETMN'),hours=48,shadow=True):
    if hours not in (48,72) or not 1<=len(symbols)<=4 or len(set(symbols))!=len(symbols):raise ValueError('INVALID_FIXED_UNIVERSE_OR_DURATION')
    return {'version':'ATLAS_FORMAL_STUDY_V1','symbols':list(symbols),'hours':hours,'shadow':bool(shadow),
        'forecast_seconds':2700,'inference_interval_seconds':900,'quote_interval_seconds':60,
        'quote_tolerance_seconds':300,'request_spacing_seconds':.4,'quote_retries':1,
        'initial_hypothetical_tmn':5_000_000,'fee_per_side_assumed':.001,'fee_verified':False,
        'slippage':'real displayed depth sweep estimates; no synthetic or partial fill generation',
        'risk_limits':asdict(RiskGate().limits),'allocation_limits':asdict(AllocationLimits()),
        'allocation_authority':'PROPOSALS_ONLY','executing_policy':'EXISTING_ATLAS_CHAMPION_ONLY' if shadow else 'OBSERVATION_ONLY',
        'statistical_minimum_time_blocks':30,'statistical_minimum_prospective_hours':48,'automatic_promotion':False,'LIVE':'HARD_DISABLED'}

def prepare(root,directory,config=None,*,require_committed=True):
    root=Path(root).resolve();directory=Path(directory).resolve();config=config or settings()
    if not {'milestone7','milestone8'}.intersection(directory.parts) or 'research_challengers' not in directory.parts:raise ValueError('NEW_MILESTONE7_OR_MILESTONE8_SESSION_REQUIRED')
    if (directory/'study_contract.json').exists():
        contract=json.loads((directory/'study_contract.json').read_text())
        validate(root,contract)
        if contract['settings']!=config:raise ValueError('FROZEN_SETTINGS_MISMATCH')
        return contract
    if directory.exists() and any(directory.iterdir()):raise ValueError('REFUSE_TO_CONVERT_EXISTING_DEVELOPMENT_SESSION')
    if require_committed:
        changed=subprocess.check_output(['git','diff','HEAD','--name-only','--','wallex_bot','scripts','third_party/SOURCES.md'],text=True).strip()
        untracked=subprocess.check_output(['git','ls-files','--others','--exclude-standard','wallex_bot'],text=True).strip()
        if changed or untracked:raise ValueError('COMMIT_RUNTIME_SOURCE_BEFORE_FORMAL_STUDY')
    db=sqlite3.connect((root/'catalog.sqlite').as_uri()+'?mode=ro',uri=True)
    try:
        for symbol in config['symbols']:
            row=db.execute('SELECT metadata FROM assets WHERE symbol=?',(symbol,)).fetchone();m=json.loads(row[0]) if row else {}
            if m.get('is_spot') is not True or m.get('quote_asset')!='TMN':raise ValueError('UNVERIFIED_SPOT_TMN_UNIVERSE')
    finally:db.close()
    registry=model_registry(root)
    contract={'session_id':directory.name,'settings':config,'source_manifest_LF_sha256':source_manifest(),'models':registry,
        'source_commit':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),
        'prepared_at':time.time(),'status':'PREPARED_NOT_STARTED','exchange_credentials_used':False}
    artifacts={root/'models/active_champion.json'}
    for model in registry.values():
        if model.get('path'):artifacts.add(Path(model['path']).resolve())
        artifacts.update(Path(p).resolve() for p in model.get('paths',[]))
    contract['model_file_hashes']={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(artifacts)}
    contract['contract_sha256']=_sha(contract)
    directory.mkdir(parents=True,exist_ok=True);_save_atomic(directory/'study_contract.json',contract)
    return contract

def validate(root,contract):
    expected={k:v for k,v in contract.items() if k!='contract_sha256'}
    if _sha(expected)!=contract['contract_sha256']:raise ValueError('CONTRACT_HASH_INVALID')
    if source_manifest()!=contract['source_manifest_LF_sha256']:raise ValueError('SESSION_SOURCE_CHANGED_NEW_SESSION_REQUIRED')
    if model_registry(root)!=contract['models']:raise ValueError('SESSION_MODEL_CHANGED_NEW_SESSION_REQUIRED')
    return True

def fast_validate(contract):
    if source_manifest()!=contract['source_manifest_LF_sha256']:raise RuntimeError('PINNED_SOURCE_CHANGED')
    if any(hashlib.sha256(Path(p).read_bytes()).hexdigest()!=sha for p,sha in contract['model_file_hashes'].items()):raise RuntimeError('PINNED_MODEL_CHANGED')

class DeadlineLedger(ModelObservationLedger):
    def __init__(self,root):
        super().__init__(root)
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS deadline_queue_v7(prediction_id TEXT PRIMARY KEY,symbol TEXT NOT NULL,due REAL NOT NULL,expires REAL NOT NULL,status TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS deadline_queue_v7_due ON deadline_queue_v7(status,due,symbol);
        CREATE TABLE IF NOT EXISTS quote_io_v7(quote_id INTEGER PRIMARY KEY,request_started REAL NOT NULL,response_received REAL NOT NULL,observed REAL NOT NULL,stored REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS study_events_v7(id INTEGER PRIMARY KEY,observed REAL NOT NULL,kind TEXT NOT NULL,payload TEXT NOT NULL,sha256 TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS study_runtime_v7(key TEXT PRIMARY KEY,payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS inference_audit_v7(prediction_id TEXT PRIMARY KEY,contract_sha TEXT NOT NULL,started REAL NOT NULL,finished REAL NOT NULL);
        ''');self.db.commit()
    def event(self,kind,payload):
        with self.db:self.db.execute('INSERT INTO study_events_v7(observed,kind,payload,sha256) VALUES(?,?,?,?)',(time.time(),kind,_canon(payload),_sha(payload)))
    def sync_queue(self):
        with self.db:
            self.db.execute('''INSERT OR IGNORE INTO deadline_queue_v7 SELECT prediction_id,symbol,due,due+300,status FROM m6_predictions''')
            self.db.execute('''UPDATE deadline_queue_v7 SET status=(SELECT status FROM m6_predictions p WHERE p.prediction_id=deadline_queue_v7.prediction_id)''')
    def next_sample(self,symbol,last_observed=None,now=None,interval=60):
        now=float(time.time() if now is None else now);self.sync_queue()
        due=self.db.execute("SELECT min(due) FROM deadline_queue_v7 WHERE symbol=? AND status='PENDING' AND expires>=?",(symbol,now)).fetchone()[0]
        regular=now if last_observed is None else last_observed+interval
        if due is not None:regular=min(regular,due if due>now else now)
        return max(now,regular)
    def reconcile(self,now=None):
        before={key:state for key,state in self.db.execute('SELECT prediction_id,status FROM m6_predictions')}
        result=super().reconcile(now);self.sync_queue()
        for key,state in self.db.execute('SELECT prediction_id,status FROM m6_predictions').fetchall():
            if before.get(key)!=state:self.event('SCORING_TRANSITION',{'prediction_id':key,'from':before.get(key),'to':state,'scored_at':time.time()})
        # Append-only outcome memory uses actual availability, never the earlier
        # decision timestamp as creation time. Restart safely retries this copy.
        from .atlas_memory import ResearchMemory
        memory=ResearchMemory(self.root)
        try:
            for key,symbol,raw,sha in self.db.execute('SELECT o.prediction_id,p.symbol,o.payload,o.payload_sha FROM m6_outcomes o JOIN m6_predictions p USING(prediction_id)'):
                outcome=json.loads(raw)
                if _sha(outcome)!=sha:raise ValueError('OUTCOME_HASH_MISMATCH')
                memory.record('m7-outcome-'+key,symbol,outcome['future_observed_epoch'],outcome['available_at'],
                    'MATURED_FORECAST_OUTCOME',sha,outcome,'QUOTE_PROXY_NOT_TRADING_PNL')
        finally:memory.close()
        return result
    def deadline_report(self):
        self.sync_queue();now=time.time();rows=[]
        for key,symbol,due,expires,state in self.db.execute('SELECT * FROM deadline_queue_v7 ORDER BY due,prediction_id'):
            future=self.db.execute('SELECT future_quote_id,payload FROM m6_outcomes WHERE prediction_id=?',(key,)).fetchone()
            lag=None;scored_at=None
            if future:
                p=json.loads(future[1]);lag=p['future_observed_epoch']-due;scored_at=p['available_at']
            effective=state if state!='PENDING' or now<=expires else 'UNSCORED_NO_REAL_FUTURE_QUOTE'
            rows.append({'prediction_id':key,'symbol':symbol,'due':due,'expires':expires,'stored_status':state,'effective_status':effective,
                'future_quote_latency_seconds':lag,'scored_at':scored_at,'reason':'WAITING_REAL_FUTURE_QUOTE' if effective=='PENDING' else effective})
        matured=[r for r in rows if r['due']<=now];scored=[r for r in matured if r['effective_status']=='SCORED_REAL_FUTURE_QUOTE']
        return {'rows':rows,'matured':len(matured),'scored':len(scored),'pending':sum(r['effective_status']=='PENDING' for r in rows),
            'missing_future_quote':sum(r['effective_status']=='UNSCORED_NO_REAL_FUTURE_QUOTE' for r in rows),
            'timely_coverage':len(scored)/len(matured) if matured else None,'sampling_interval_seconds':60,
            'tolerance_seconds':300,'timestamp_contract':'request_started / response_received / observed / stored / outcome.available_at separately recorded',
            'imputation':False}

def quote_worker(root,directory,contract,owner,stop):
    from .market import depth
    from .live_scout import measure_book
    ledger=DeadlineLedger(directory);ledger.owner=owner;config=contract['settings'];last_start=0.
    try:
        while not stop.is_set():
            fast_validate(contract)
            if not ledger.claim():raise RuntimeError('COLLECTOR_OWNERSHIP_LOST')
            ledger.reconcile();work=[]
            for symbol in config['symbols']:
                row=ledger.db.execute('SELECT max(observed_epoch) FROM quotes WHERE symbol=?',(symbol,)).fetchone()
                work.append((ledger.next_sample(symbol,row[0]),symbol))
            scheduled,symbol=min(work)
            if scheduled>time.time():stop.wait(min(1.,scheduled-time.time()));continue
            for attempt in range(config['quote_retries']+1):
                if stop.wait(max(0,.4-(time.monotonic()-last_start))):break
                started=time.time();last_start=time.monotonic()
                try:
                    raw=depth(symbol);received=time.time();metrics=measure_book(raw,250000,config['fee_per_side_assumed']);observed=time.time()
                    quote_id=ledger.forward.record_real_quote(symbol,raw,metrics,observed)
                    with ledger.db:ledger.db.execute('INSERT INTO quote_io_v7 VALUES(?,?,?,?,?)',(quote_id,started,received,observed,time.time()))
                    ledger.reconcile();break
                except Exception as exc:
                    ledger.event('QUOTE_NETWORK_OR_VALIDATION_ERROR',{'symbol':symbol,'attempt':attempt+1,'error_type':type(exc).__name__,'request_started':started})
                    if stop.wait(.5*(attempt+1)):break
            else:
                # No tight retry loop when a source is down; keep deadlines but
                # wait briefly before trying this same genuinely missing quote.
                stop.wait(5)
    except Exception as exc:
        ledger.event('QUOTE_WORKER_STOPPED_SAFE',{'error_type':type(exc).__name__,'reason_code':str(exc)[:150],
            'contract_broken':str(exc).startswith(('PINNED_','COLLECTOR_'))});stop.set()
    finally:ledger.close()

def risk_estimates(lake,symbols,cutoff):
    import numpy as np,pandas as pd
    from .atlas_feature_health import _verified_segments
    series={};vol={}
    for symbol in symbols:
        parts,_=_verified_segments(lake.root,lake.db,symbol,'15')
        if not parts:continue
        f=parts[-1];f=f[f.timestamp.astype('int64')+900<=cutoff].tail(129)
        if len(f)<97:continue
        returns=pd.Series(np.diff(np.log(f.close.to_numpy(float))),index=f.timestamp.iloc[1:].to_numpy()+900)
        if not np.isfinite(returns).all():continue
        series[symbol]=returns;vol[symbol]={'volatility':float(returns.std()),'volatility_observations':len(returns)}
    corr={}
    for a in series:
        for b in series:
            joined=pd.concat([series[a],series[b]],axis=1).dropna()
            if a!=b and len(joined)>=96 and all(joined.std()>0):corr[(a,b)]=float(joined.corr().iloc[0,1])
    return vol,corr

def propose_portfolio(lake,directory,ledger,contract):
    from .atlas_shadow import PaperAccount
    from .atlas_memory import ResearchMemory
    account=PaperAccount(SimpleNamespace(root=Path(directory)));memory=ResearchMemory(directory)
    try:
        if not account.verify():raise RuntimeError('PAPER_ACCOUNT_CHAIN_INVALID')
        account.db.execute('''CREATE TABLE IF NOT EXISTS allocation_proposals_v7(proposal_id TEXT PRIMARY KEY,observed REAL NOT NULL,model TEXT NOT NULL,method TEXT NOT NULL,payload TEXT NOT NULL,sha256 TEXT NOT NULL)''');account.db.commit()
        volatility,correlations=risk_estimates(lake,contract['settings']['symbols'],time.time())
        for model in contract['models']:
            candidates={}
            for symbol in contract['settings']['symbols']:
                p=ledger.db.execute('SELECT payload FROM m6_predictions WHERE symbol=? AND model=? ORDER BY decision DESC LIMIT 1',(symbol,model)).fetchone()
                q=ledger.db.execute('SELECT id FROM quotes WHERE symbol=? ORDER BY observed_epoch DESC LIMIT 1',(symbol,)).fetchone()
                if not p or not q:continue
                p=json.loads(p[0]);meta=json.loads(lake.db.execute('SELECT metadata FROM assets WHERE symbol=?',(symbol,)).fetchone()[0])
                candidates[symbol]={'quote':ledger.quote(q[0]),'forecast':{'quantile_log_returns':{k:p[k] for k in ('q10','q50','q90')}},
                    'prediction_id':p['prediction_id'],'prediction_available_at':p['prediction_available_at'],
                    'spot_tmn':meta.get('is_spot') is True and meta.get('quote_asset')=='TMN','fee':.001,'metadata':meta,**volatility.get(symbol,{})}
            for method in METHODS:
                account.db.execute('BEGIN IMMEDIATE')
                try:
                    state={'cash_tmn':float(account.get('cash_tmn')),'positions':account.db.execute('SELECT symbol,quantity,entry_cost FROM positions').fetchall(),'stopped':account.get('stopped')=='1','high_water_tmn':float(account.get('high_water_tmn'))}
                    proposal=allocate(method,state,candidates,correlations=correlations)
                    proposal['contract_sha256']=contract['contract_sha256'];proposal['model']=model
                    proposal['source_forecast_ids']={s:c['prediction_id'] for s,c in candidates.items()}
                    key=_sha({'model':model,'method':method,'forecast_ids':proposal['source_forecast_ids'],
                        'quote_hashes':{s:c['quote']['receipt_sha256'] for s,c in candidates.items()},'account':state,'contract':contract['contract_sha256'],
                        'quality':[proposal['status'],proposal['rejections']]})
                    cached=account.db.execute('SELECT payload FROM allocation_proposals_v7 WHERE proposal_id=?',(key,)).fetchone()
                    if cached:proposal=json.loads(cached[0])
                    account.db.execute('INSERT OR IGNORE INTO allocation_proposals_v7 VALUES(?,?,?,?,?,?)',(key,time.time(),model,method,_canon(proposal),_sha(proposal)));account.db.commit()
                except Exception:account.db.rollback();raise
                memory.record('allocation-'+key,'PORTFOLIO',proposal['decision_time'],time.time(),'STRATEGY_PERFORMANCE_EVIDENCE',_sha(proposal),
                    {'model':model,'method':method,'proposal_id':key,'target_weights':proposal['target_weights'],'cash_weight':proposal['cash_weight'],
                        'evaluation_status':'RESEARCH_PROPOSAL_NOT_EXECUTED','exchange_PnL':None},'UNVALIDATED_RESEARCH_PROPOSAL')
    finally:account.close();memory.close()

def persist_research_evidence(directory,ledger):
    """Append original immutable evidence with actual memory creation time."""
    from .atlas_memory import ResearchMemory
    memory=ResearchMemory(directory)
    try:
        for key,symbol,observed,raw,sha in ledger.db.execute('SELECT prediction_id,symbol,decision,payload,payload_sha FROM m6_predictions'):
            if _sha(json.loads(raw))!=sha:raise ValueError('FORECAST_RECEIPT_HASH_MISMATCH')
            memory.record('m7-forecast-'+key,symbol,observed,observed,'PAST_FORECAST',sha,json.loads(raw),'PENDING_REAL_FUTURE_QUOTE')
        path=Path(directory)/'agent_evidence.sqlite'
        if path.exists():
            db=sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)
            try:
                for key,stamp,symbol,evidence,review,action,risk,sha in db.execute('SELECT * FROM decisions_v6'):
                    payload={'evidence':json.loads(evidence),'review':json.loads(review),'action':action,'risk_replay':json.loads(risk)}
                    if _sha(payload)!=sha:raise ValueError('DECISION_HASH_INVALID')
                    memory.record('m7-decision-'+key,symbol,stamp,stamp,'DECISION_RISK_VETO',sha,payload,'PAPER_DECISION_NOT_EXCHANGE_FILL')
            finally:db.close()
    finally:memory.close()

def _research_hook_safe(hook,lake,directory,ledger,contract):
    try:return hook(lake,directory,ledger,contract)
    except Exception as exc:
        failure={'status':'M8_RESEARCH_HOOK_FAILED_SAFE_NO_FALLBACK_ORDER','error_type':type(exc).__name__,'reason_code':str(exc)[:150]}
        ledger.event('M8_RESEARCH_HOOK_FAILED_SAFE',failure);return failure

def run(root,directory,*,max_inference_cycles=None,max_runtime_seconds=None,stop=None,startup_hook=None,research_hook=None):
    from .atlas_archive import Lake
    from .atlas_data_sync import DataSyncManager
    from .atlas_agent import cycle
    root=Path(root).resolve();directory=Path(directory).resolve();contract=json.loads((directory/'study_contract.json').read_text());validate(root,contract)
    if (startup_hook or research_hook) and contract['settings'].get('research_profile')!='ATLAS_M8_AGENTIC_V1':raise ValueError('M8_HOOKS_REQUIRE_SEPARATE_FROZEN_M8_PROFILE')
    if max_inference_cycles is not None and max_inference_cycles<1:raise ValueError('INVALID_CYCLE_BOUND')
    if max_runtime_seconds is not None and max_runtime_seconds<=0:raise ValueError('INVALID_RUNTIME_BOUND')
    process_started=time.monotonic()
    stop=stop or threading.Event();ledger=DeadlineLedger(directory);lake=Lake(root);worker=None;cycles=0
    if not ledger.claim():ledger.close();lake.db.close();return {'status':'LEASE_HELD_NO_REQUESTS'}
    try:
        row=ledger.db.execute("SELECT payload FROM study_runtime_v7 WHERE key='session'").fetchone()
        runtime=json.loads(row[0]) if row else {'started_epoch':time.time(),'cycles':0,'next_inference':time.time()}
        runtime['deadline_epoch']=runtime['started_epoch']+contract['settings']['hours']*3600
        with ledger.db:ledger.db.execute("INSERT OR REPLACE INTO study_runtime_v7 VALUES('session',?)",(_canon(runtime),))
        _save_atomic(directory/'watch_session.json',{'started_epoch':runtime['started_epoch'],'deadline_epoch':runtime['deadline_epoch'],'hours':contract['settings']['hours'],'status':'RUNNING'})
        worker=threading.Thread(target=quote_worker,args=(root,directory,contract,ledger.owner,stop),name='wallex-real-quote-deadlines',daemon=False);worker.start()
        while not stop.is_set() and time.time()<runtime['deadline_epoch']:
            if max_runtime_seconds is not None and time.monotonic()-process_started>=max_runtime_seconds:break
            fast_validate(contract)
            if research_hook and time.time()>=runtime.get('next_review',0):
                latest=ledger.db.execute('SELECT max(observed_epoch) FROM quotes').fetchone()[0]
                if latest is not None and latest>runtime.get('last_review_quote',0) and 2<=time.time()-latest<=15:
                    runtime['last_review_quote']=latest;runtime['next_review']=time.time()+5
                    with ledger.db:ledger.db.execute("INSERT OR REPLACE INTO study_runtime_v7 VALUES('session',?)",(_canon(runtime),))
                    _research_hook_safe(research_hook,lake,directory,ledger,contract)
            if time.time()<runtime['next_inference']:
                stop.wait(min(1.,runtime['next_inference']-time.time()));continue
            validate(root,contract)
            report={'started':time.time(),'models':{},'shadow':[]}
            report['sync']=DataSyncManager(lake).run(symbols=contract['settings']['symbols'],target_resolutions=('15',),target_warmup_hours={'15':37.75},max_windows=8,retries=1,purpose='m7-inference')
            if startup_hook:
                try:report['intelligence_sync']=startup_hook(lake,directory,contract)
                except Exception as exc:report['intelligence_sync']={'status':'FAILED_SAFE_OPTIONAL_INTELLIGENCE_SYNC','error_type':type(exc).__name__}
            for symbol in contract['settings']['symbols']:
                if stop.is_set():break
                started=time.time()
                try:
                    snapshot=input_snapshot(lake,symbol);outputs,errors=predict_models(contract['models'],snapshot)
                    quote=ledger.db.execute('SELECT id FROM quotes WHERE symbol=? ORDER BY observed_epoch DESC LIMIT 1',(symbol,)).fetchone()
                    if not quote:raise ValueError('WAITING_REAL_SAMPLER_QUOTE')
                    inserted=ledger.register(symbol,contract['models'],snapshot,outputs,quote[0]);finished=time.time();ledger.sync_queue()
                    with ledger.db:
                        for key, in ledger.db.execute('SELECT prediction_id FROM m6_predictions WHERE symbol=? AND cutoff=?',(symbol,snapshot['cutoff'])).fetchall():
                            ledger.db.execute('INSERT OR IGNORE INTO inference_audit_v7 VALUES(?,?,?,?)',(key,contract['contract_sha256'],started,finished))
                    report['models'][symbol]={'inserted':inserted,'errors':errors,'latency_seconds':finished-started}
                    if contract['settings']['shadow'] and not stop.is_set():
                        report['shadow'].append(cycle(lake,symbol=symbol,paper_root=directory,checkpoint=directory/'agent_checkpoints.sqlite',thread_id='m7-'+symbol,sync_enabled=False))
                except Exception as exc:report['models'][symbol]={'error_type':type(exc).__name__,'reason':str(exc)[:120]}
            propose_portfolio(lake,directory,ledger,contract)
            persist_research_evidence(directory,ledger)
            if research_hook:
                report['agentic']=_research_hook_safe(research_hook,lake,directory,ledger,contract)
                runtime['last_review_quote']=ledger.db.execute('SELECT max(observed_epoch) FROM quotes').fetchone()[0] or 0
                runtime['next_review']=time.time()+5
            ledger.event('INFERENCE_CYCLE',report);runtime['cycles']+=1;cycles+=1;runtime['next_inference']=time.time()+900
            with ledger.db:ledger.db.execute("INSERT OR REPLACE INTO study_runtime_v7 VALUES('session',?)",(_canon(runtime),))
            print(json.dumps({'cycle':runtime['cycles'],'model_status':report['models'],'proposals_only':True}),flush=True)
            if max_inference_cycles is not None and cycles>=max_inference_cycles:break
        if time.time()>=runtime['deadline_epoch'] and contract['settings']['shadow']:
            ledger.event('FINAL_TMN',liquidate_paper_positions(SimpleNamespace(root=directory),fee=.001,require_watch_deadline=True))
        broken=any(json.loads(p).get('contract_broken') for p, in ledger.db.execute("SELECT payload FROM study_events_v7 WHERE kind='QUOTE_WORKER_STOPPED_SAFE'"))
        return {'status':'SESSION_CONTRACT_BROKEN' if broken else ('PENDING_FORMAL_WINDOW_NOT_COMPLETE' if time.time()<runtime['deadline_epoch'] else 'WINDOW_ELAPSED_REVIEW_COVERAGE_REQUIRED'),
            'cycles_this_process':cycles,'contract_sha256':contract['contract_sha256']}
    finally:
        stop.set()
        if worker:worker.join(timeout=60)
        if worker and worker.is_alive():raise RuntimeError('QUOTE_WORKER_NOT_YET_STOPPED')
        ledger.event('FOREGROUND_PROCESS_STOPPED',{'cycles_this_process':cycles,'observed_at':time.time(),'automatic_background_execution':False})
        ledger.release();ledger.close();lake.db.close()

def main():
    import signal
    parser=argparse.ArgumentParser(description='M7 formal foreground study; NO live orders')
    parser.add_argument('command',choices=['prepare','run','status','reconcile']);parser.add_argument('--root',default='atlas_store');parser.add_argument('--session-dir',default=DEFAULT_SESSION)
    parser.add_argument('--hours',type=int,default=48);parser.add_argument('--symbols',default='BTCTMN,PEPETMN');parser.add_argument('--observation-only',action='store_true');parser.add_argument('--max-inference-cycles',type=int);parser.add_argument('--max-runtime-seconds',type=float)
    args=parser.parse_args();stop=threading.Event()
    for sig in (signal.SIGINT,signal.SIGTERM):signal.signal(sig,lambda *_:stop.set())
    if args.command=='prepare':result=prepare(args.root,args.session_dir,settings(tuple(args.symbols.split(',')),args.hours,not args.observation_only))
    elif args.command=='run':result=run(args.root,args.session_dir,max_inference_cycles=args.max_inference_cycles,max_runtime_seconds=args.max_runtime_seconds,stop=stop)
    else:
        contract=json.loads((Path(args.session_dir)/'study_contract.json').read_text());validate(args.root,contract);ledger=DeadlineLedger(args.session_dir)
        try:
            if args.command=='reconcile':ledger.reconcile()
            result={'forward':ledger.status(),'deadlines':ledger.deadline_report(),'evaluation':ledger.evaluation()}
        finally:ledger.close()
    print(json.dumps(result,ensure_ascii=False,default=str))

if __name__=='__main__':main()
