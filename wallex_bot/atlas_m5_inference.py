"""Read-only M5 historical replay and isolated Agent/News/Memory smoke graph.

Source: Atlas existing BACKTEST, NewsStore and LangGraph contracts. No broker
or risk/execution module is imported. This is not a new live decision path.
"""
import hashlib,json,sqlite3,time,tempfile
from pathlib import Path
from types import SimpleNamespace
import numpy as np
from .atlas_m5_data import digest,feature_groups,iso
from .atlas_m5_research import load_bundle,save

def replay(run,*,sample_id=None):
    """Explicit historical replay only; never present it as a PIT live forecast."""
    import torch
    from .atlas_m5_models import make_model,apply_calibration
    started=time.monotonic();run=Path(run)
    selection=json.loads((run/'research_selection.json').read_text())
    directory=Path(selection['directory']);result=json.loads((directory/'result.json').read_text())
    path=directory/'best.pt';sha=hashlib.sha256(path.read_bytes()).hexdigest()
    if sha!=selection['checkpoint_sha256'] or sha!=result['checkpoint_sha256']:raise ValueError('CHECKPOINT_HASH_MISMATCH')
    b=load_bundle(run/'dataset_15_0.75');config=result['config'];X=b.arrays[config['group']]
    if digest(b.rows)!=config['dataset_sha256'] or digest(b.manifest)!=config['source_manifest_sha256'] or b.split['split_sha256']!=config['split_sha256']:
        raise ValueError('FROZEN_DATASET_PROVENANCE_MISMATCH')
    if hashlib.sha256(X.tobytes()).hexdigest()!=config['feature_input_sha256']:raise ValueError('FEATURE_INPUT_HASH_MISMATCH')
    indices=b.split['indices']['test']
    index=next((i for i in indices if b.rows[i]['sample_id']==sample_id),None) if sample_id else indices[-1]
    if index is None:raise ValueError('NOT_A_FROZEN_TEST_SAMPLE')
    state=torch.load(path,map_location='cpu',weights_only=True)
    if state['config']!=config:raise ValueError('CHECKPOINT_CONFIGURATION_MISMATCH')
    torch.set_num_threads(2);model=make_model(config['architecture'],config['context'],config['channels'],config['head'],'cpu')
    model.load_state_dict(state['state_dict']);model.eval()
    with torch.inference_mode():p=model(torch.from_numpy(X[index:index+1])).numpy()*config['target_scale']+config['target_mean']
    p=apply_calibration(p,result['calibration'])[0];row=b.rows[index]
    return {'symbol':row['symbol'],'sample_id':row['sample_id'],'decision_time':iso(row['feature_cutoff']),
        'horizon':row['target_horizon_hours'],'feature_recipe':json.loads((run/'preflight.json').read_text(encoding='utf8'))['groups'][config['group']],
        'model_sha256':sha,'q10':float(p[0]),'q50':float(p[1]),'q90':float(p[2]),
        'calibration_version':result['calibration']['version'],'data_readiness':'FROZEN_RETROSPECTIVE_REPLAY_NOT_LIVE_PIT',
        'inference_latency_seconds':time.monotonic()-started,'authority':'RESEARCH_ONLY_NO_ORDER',
        'retrospective_warning':'Model/calibration were fitted after this historical cutoff; replay is not prospective evidence'}

def logical_hash(path):
    if not Path(path).exists():return None
    db=sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro',uri=True)
    try:return hashlib.sha256('\n'.join(db.iterdump()).encode()).hexdigest()
    finally:db.close()

def smoke(root,run):
    from typing import TypedDict
    from langgraph.graph import StateGraph,START,END
    from .atlas_context import make_packet
    from .atlas_news_features import advisory_packet
    root=Path(root).resolve();run=Path(run);prediction=replay(run)
    paths=[root/'context_memory.sqlite',root/'news.sqlite',root/'paper.sqlite',root/'shadow.sqlite']
    paths+=list(root.glob('*account*.sqlite'))
    before={str(p):logical_hash(p) for p in paths}
    manifest=root/'models'/'active_champion.json';champion=hashlib.sha256(manifest.read_bytes()).hexdigest() if manifest.exists() else None
    class State(TypedDict,total=False):
        prediction:dict
        memory:dict
        news:dict
        disposition:str
    with tempfile.TemporaryDirectory(prefix='atlas_m5_smoke_') as tmp:
        src=root/'news.sqlite'
        if src.exists():
            source=sqlite3.connect(src.as_uri()+'?mode=ro',uri=True);dest=sqlite3.connect(str(Path(tmp)/'news.sqlite'))
            source.backup(dest);source.close();dest.close()
        graph=StateGraph(State)
        graph.add_node('memory',lambda state:{'memory':make_packet(SimpleNamespace(root=root),phase='research',mode='BACKTEST',as_of_utc=prediction['decision_time'],symbol=prediction['symbol'])})
        graph.add_node('news',lambda state:{'news':advisory_packet(tmp,prediction['symbol'],prediction['decision_time'],mode='BACKTEST',record_memory=False)})
        graph.add_node('research_agent',lambda state:{'disposition':'REPLAY_ONLY_NO_EXECUTION_NO_LLM_REQUIRED'})
        graph.add_edge(START,'memory');graph.add_edge('memory','news');graph.add_edge('news','research_agent');graph.add_edge('research_agent',END)
        state=graph.compile().invoke({'prediction':prediction})
    after={str(p):logical_hash(p) for p in paths}
    current=hashlib.sha256(manifest.read_bytes()).hexdigest() if manifest.exists() else None
    report={'mode':'BACKTEST','graph':'memory -> actual cutoff news -> research agent disposition',
        'scope':'isolated research graph, not operational SHADOW trading graph',
        'external_LLM_called':False,'broker_imported':False,'operational_stores_unchanged':before==after,
        'champion_manifest_unchanged':champion==current,'before':before,'after':after,
        'prediction':prediction,'news_summary':state['news']['summary'],'disposition':state['disposition']}
    if before!=after or champion!=current:raise RuntimeError('OPERATIONAL_ISOLATION_FAILURE')
    save(Path('reports')/'m5_backtest_smoke.json',report)
    return report

class ProspectiveLedger:
    """Dedicated research-only ledger. No premature outcomes or candle fills.

    Accepts ONLY genuinely prospective, receipt-ready forecasts. Missing
    eligible 48/72h models prevents insertion rather than fabricating records.
    Future quote pairing remains Atlas's real-quote forward evaluator's job.
    """
    def __init__(self,path):
        path=Path(path).resolve()
        if 'research_challengers' not in path.parts:raise ValueError('RESEARCH_LEDGER_PATH_REQUIRED')
        path.parent.mkdir(parents=True,exist_ok=True);self.db=sqlite3.connect(path)
        self.db.execute('CREATE TABLE IF NOT EXISTS forecasts(id TEXT PRIMARY KEY, symbol TEXT NOT NULL, decision_epoch REAL NOT NULL, target_epoch REAL NOT NULL, payload TEXT NOT NULL, status TEXT NOT NULL)')
    def record(self,forecast):
        if forecast.get('data_readiness')!='VERIFIED_PROSPECTIVE_RECEIPTS' or forecast.get('horizon') not in (48,72):raise ValueError('NO_ELIGIBLE_PROSPECTIVE_FORECAST')
        from datetime import datetime
        decision=datetime.fromisoformat(forecast['decision_time']).timestamp()
        now=time.time()
        if decision>now or now-decision>300:raise ValueError('STALE_OR_FUTURE_DECISION')
        if not forecast.get('source_manifest_sha256') or not forecast.get('model_sha256'):raise ValueError('PROVENANCE_REQUIRED')
        q=[forecast[k] for k in ('q10','q50','q90')]
        if not np.isfinite(q).all() or q!=sorted(q):raise ValueError('INVALID_QUANTILES')
        key=digest(forecast)
        with self.db:self.db.execute('INSERT OR IGNORE INTO forecasts VALUES(?,?,?,?,?,?)',(key,forecast['symbol'],decision,decision+3600*forecast['horizon'],json.dumps(forecast),'PENDING_REAL_FUTURE_QUOTES'))
        return key
    def status(self):return {'counts':dict(self.db.execute('SELECT status,count(*) FROM forecasts GROUP BY status')),'outcomes':'NEVER_SYNTHESIZED','orders':'NO_INTERFACE'}
    def reconcile(self,root,*,max_lag_seconds=300):
        """Pair actual independently collected quotes, never make HTTP calls.

        Only the mid-to-mid descriptive label is resolved here. Executable net
        proxy and opportunity stay null without independently verified fees.
        The FORECAST payload remains unchanged; labels go in a separate table.
        """
        from .atlas_forward import _sha
        self.db.execute('CREATE TABLE IF NOT EXISTS quote_labels(forecast_id TEXT PRIMARY KEY, observed_epoch REAL NOT NULL, payload TEXT NOT NULL)')
        path=(Path(root)/'forward_observations.sqlite').resolve()
        if not path.exists():return {'resolved':0,'reason':'NO_REAL_QUOTE_LEDGER'}
        quotes=sqlite3.connect(path.as_uri()+'?mode=ro',uri=True);resolved=0;pending=0
        try:
            for key,symbol,decision,target in self.db.execute("SELECT id,symbol,decision_epoch,target_epoch FROM forecasts WHERE status='PENDING_REAL_FUTURE_QUOTES'").fetchall():
                if target>time.time():pending+=1;continue
                pair=[]
                for cutoff in (decision,target):
                    row=quotes.execute('SELECT symbol,observed_epoch,best_bid,best_ask,mid,raw_book,receipt_sha256 FROM quotes WHERE symbol=? AND observed_epoch>=? AND observed_epoch<=? ORDER BY observed_epoch LIMIT 1',(symbol,cutoff,cutoff+max_lag_seconds)).fetchone()
                    if row is None:break
                    s,stamp,bid,ask,mid,raw,sha=row
                    payload={'symbol':s,'observed_epoch':stamp,'best_bid':bid,'best_ask':ask,'mid':mid,'raw_book':json.loads(raw)}
                    if _sha(payload)!=sha or stamp>time.time() or not (0<bid<=ask and bid<=mid<=ask):break
                    pair.append({**payload,'receipt_sha256':sha})
                if len(pair)!=2:pending+=1;continue
                label={'label_type':'MID_TO_MID_RETURN','value':float(np.log(pair[1]['mid']/pair[0]['mid'])),
                    'entry_receipt_sha256':pair[0]['receipt_sha256'],'exit_receipt_sha256':pair[1]['receipt_sha256'],
                    'entry_observed_epoch':pair[0]['observed_epoch'],'exit_observed_epoch':pair[1]['observed_epoch'],
                    'ASK_TO_FUTURE_BID_NET_PROXY':None,'POSITIVE_AFTER_COST_OPPORTUNITY':None,
                    'reason':'No verified fee receipt; mid return is NOT executable PnL'}
                with self.db:
                    self.db.execute('INSERT INTO quote_labels VALUES(?,?,?)',(key,pair[1]['observed_epoch'],json.dumps(label)))
                    self.db.execute("UPDATE forecasts SET status='REAL_QUOTES_OBSERVED' WHERE id=?",(key,))
                resolved+=1
        finally:quotes.close()
        return {'resolved':resolved,'pending_real_future_quotes':pending,'orders':'NO_INTERFACE'}
    def close(self):self.db.close()

def main():
    import argparse
    parser=argparse.ArgumentParser(description='Research-only replay/forward ledger; never orders')
    parser.add_argument('command',choices=['replay','smoke','forward-status','forward-reconcile'])
    parser.add_argument('--run-directory',required=True);parser.add_argument('--root',default='atlas_store')
    args=parser.parse_args();run=Path(args.run_directory)
    if args.command=='replay':result=replay(run)
    elif args.command=='smoke':result=smoke(args.root,run)
    else:
        ledger=ProspectiveLedger(run/'prospective.sqlite')
        try:result=ledger.status() if args.command=='forward-status' else ledger.reconcile(args.root)
        finally:ledger.close()
    print(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
