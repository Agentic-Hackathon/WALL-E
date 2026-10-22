"""M6 stoppable/resumable foreground observer and isolated Shadow study.

Reuses DataSyncManager, actual ForwardLedger, existing Agent/ShadowBroker and
final-TMN path. No external framework, private endpoint or LLM is executed.
"""
import argparse,json,time,threading,math
from pathlib import Path
from types import SimpleNamespace
from datetime import datetime,timezone
from .atlas_prospective import ModelObservationLedger,model_registry,input_snapshot,predict_models
from .atlas_data_sync import DataSyncManager
from .atlas_memory import ResearchMemory
from .atlas_forward import _sha
from .atlas_liquidation import _save_atomic,liquidate_paper_positions,liquidation_status

def iso(epoch):return datetime.fromtimestamp(epoch,timezone.utc).isoformat()

def strategy_status(session_dir,ledger,now=None):
    now=float(time.time() if now is None else now);path=Path(session_dir)/'watch_session.json'
    session=json.loads(path.read_text()) if path.exists() else {}
    rows=ledger.db.execute('SELECT observed_epoch FROM quotes ORDER BY observed_epoch').fetchall()
    start=session.get('started_epoch',now);elapsed=max(0,now-start);interval=session.get('interval_seconds',900)
    stamps=sorted(set(float(r[0]) for r in rows));covered=len({int((s-start)//interval) for s in stamps if s>=start})
    expected=max(1,math.ceil(elapsed/interval));max_gap=max((b-a for a,b in zip([start]+stamps,stamps+[now])),default=elapsed)
    enough=elapsed>=48*3600 and covered/expected>=.9 and max_gap<=2*interval
    paper=liquidation_status(session_dir);metrics=None
    if (Path(session_dir)/'shadow.sqlite').exists():
        import sqlite3
        db=sqlite3.connect((Path(session_dir)/'shadow.sqlite').resolve().as_uri()+'?mode=ro',uri=True)
        try:
            marks=[(at,json.loads(raw)) for at,raw in db.execute("SELECT observed_at,payload FROM events WHERE action='FRESH_REAL_BID_MARK_TO_MARKET' ORDER BY id")]
            equity=[p['equity_tmn'] for _,p in marks];peak=5_000_000.;drawdown=0.
            for value in equity:peak=max(peak,value);drawdown=max(drawdown,1-value/peak)
            actions=dict(db.execute("SELECT action,count(*) FROM events WHERE action IN ('PAPER_BUY','PAPER_SELL') GROUP BY action"))
            turnover=sum(float(json.loads(raw).get('risk_gate',{}).get('notional_tmn',0)) for raw, in db.execute("SELECT payload FROM events WHERE action IN ('PAPER_BUY','PAPER_SELL')"))
            metrics={'valuation':'HYPOTHETICAL actual-bid liquidation, assumed fee; NOT fills or exchange PnL',
                'actual_bid_marks':len(marks),'observed_hypothetical_equity_change':equity[-1]/5_000_000.-1 if equity else None,
                'observed_hypothetical_max_drawdown':drawdown if equity else None,'paper_actions':actions,
                'paper_notional_turnover_tmn':turnover,'latest_entry_cost_exposure_tmn':sum(p['entry_cost_tmn'] for p in paper['paper_positions']),
                'full_48h_result_valid':enough}
        finally:db.close()
    return {'strategy_evaluation_hours':session.get('hours',48),'forecast_horizon_minutes':45,
        'initial_hypothetical_tmn':5_000_000,'elapsed_hours':elapsed/3600,'observed_time_bins':covered,
        'expected_time_bins':expected,'coverage_fraction':min(1.,covered/expected),'maximum_observation_gap_seconds':max_gap,
        'status':'COVERAGE_READY_FOR_REVIEW_NOT_PROFIT_PROOF' if enough else 'PENDING_INSUFFICIENT_48H_PROSPECTIVE_COVERAGE',
        'paper':paper,'portfolio_metrics':metrics,'cost_assumption':{'fee_per_side':.001,'verified':False,'slippage':'observed best-quote hypothetical only'},
        'max_exposure_tmn':1_000_000,'drawdown_limit_fraction':.03,'risk_limits_changed':False,
        'realized_exchange_pnl':None,'economic_edge':'NO_VERIFIED_ECONOMIC_EDGE','cash_holding_permitted':True}

def collect(lake,session_dir,*,top=2,hours=48,interval_seconds=900,max_cycles=None,shadow=False,stop_event=None,sync_enabled=True):
    from .market import depth
    from .live_scout import measure_book
    if not 1<=top<=8 or hours not in (48,72) or not 60<=interval_seconds<=3600:raise ValueError('INVALID_FOREGROUND_PROTOCOL')
    if max_cycles is not None and (not isinstance(max_cycles,int) or max_cycles<1):raise ValueError('INVALID_CYCLE_BOUND')
    session_dir=Path(session_dir).resolve()
    if 'research_challengers' not in session_dir.parts:raise ValueError('ISOLATED_RESEARCH_SESSION_REQUIRED')
    session_dir.mkdir(parents=True,exist_ok=True);stop_event=stop_event or threading.Event()
    ledger=ModelObservationLedger(session_dir);path=session_dir/'watch_session.json'
    if not ledger.claim():ledger.close();return {'status':'LEASE_HELD_NO_NETWORK','cycles':[]}
    cycles=[]
    try:
        registry=model_registry(lake.root)
        identity=lambda models:_sha({name:{k:m[k] for k in ('model_sha256','recipe','forecast_horizon')} for name,m in models.items()})
        if path.exists():
            session=json.loads(path.read_text())
            if (session['hours'],session['interval_seconds'],session['shadow_enabled'])!=(hours,interval_seconds,shadow):raise ValueError('SESSION_PROTOCOL_CONFLICT')
            if session.get('models_identity_sha256'):
                if session['models_identity_sha256']!=identity(registry):raise ValueError('SESSION_MODELS_CHANGED_USE_NEW_SESSION')
            elif session['models_sha256']!=_sha(registry):
                # Preserve initial metadata hash; audit-only wording correction
                # may migrate only if every actual model/recipe/horizon matches.
                old=json.loads((session_dir/'last_result.json').read_text())['registry']
                if identity(old)!=identity(registry):raise ValueError('SESSION_MODELS_CHANGED_USE_NEW_SESSION')
                session['metadata_migration']='Champion training partition attribution clarified; original hash retained; model identities unchanged'
            session['models_identity_sha256']=identity(registry)
        else:
            started=time.time();session={'started_epoch':started,'deadline_epoch':started+hours*3600,'hours':hours,
                'interval_seconds':interval_seconds,'shadow_enabled':shadow,'models_sha256':_sha(registry),
                'status':'RUNNING','cycles_completed':0,'live':'HARD_DISABLED','models_identity_sha256':identity(registry)}
            _save_atomic(path,session)
        memory=ResearchMemory(lake.root)
        try:
            while time.time()<session['deadline_epoch'] and not stop_event.is_set() and (max_cycles is None or len(cycles)<max_cycles):
                if not ledger.claim():break
                start=time.monotonic();sync=DataSyncManager(lake);symbols=sync._priority_symbols(top,'priority')
                cycle={'observed_at':time.time(),'symbols':symbols,'registered':0,'quote_requests':0,'errors':[],'models':{},'shadow':[]}
                try:
                    cycle['sync']=sync.run(top=top,target_resolutions=('15',),target_warmup_hours={'15':37.75},max_windows=8,retries=1,
                        purpose='m6-prospective',symbols=symbols) if sync_enabled else {'status':'SYNC_DISABLED_INDEPENDENTLY'}
                except Exception as exc:cycle['sync']={'status':'SYNC_FAILED_SAFE','error_type':type(exc).__name__}
                for symbol in symbols:
                    if stop_event.is_set():break
                    # Renew after bounded sync and between assets; never keep
                    # making public requests after losing collector ownership.
                    if not ledger.claim():
                        cycle['errors'].append({'phase':'lease','error_type':'COLLECTOR_OWNERSHIP_LOST'});break
                    raw=None
                    for attempt in range(2):
                        try:
                            if stop_event.wait(.4 if attempt==0 else .8):break
                            cycle['quote_requests']+=1;raw=depth(symbol);break
                        except Exception as exc:cycle['errors'].append({'symbol':symbol,'phase':'public_depth','attempt':attempt+1,'error_type':type(exc).__name__})
                    if raw is None:continue
                    try:
                        measured=measure_book(raw,notional_tmn=250000,fee_rate=.001);stamp=time.time()
                        quote_id=ledger.forward.record_real_quote(symbol,raw,measured,stamp)
                        receipt=ledger.quote(quote_id)
                        memory.record('market-'+receipt['receipt_sha256'],symbol,stamp,stamp,'RECENT_MARKET_CONTEXT',receipt['receipt_sha256'],
                            {'symbol':symbol,'quote_id':quote_id,'bid':receipt['best_bid'],'ask':receipt['best_ask'],'source':'actual Wallex public depth'})
                        try:
                            snapshot=input_snapshot(lake,symbol);outputs,errors=predict_models(registry,snapshot)
                            count=ledger.register(symbol,registry,snapshot,outputs,quote_id)
                            cycle['registered']+=count;cycle['models'][symbol]={'available':list(outputs),'errors':errors,'data_cutoff':snapshot['cutoff'],'inserted':count,'cached':len(outputs)-count}
                            for key,raw_prediction,sha in ledger.db.execute('SELECT prediction_id,payload,payload_sha FROM m6_predictions WHERE symbol=? AND cutoff=?',(symbol,snapshot['cutoff'])):
                                payload=json.loads(raw_prediction)
                                memory.record('forecast-'+key,symbol,payload['decision_time'],payload['prediction_available_at'],'PAST_FORECAST',sha,
                                    {'symbol':symbol,'prediction_id':key,'model':payload['model_version'],'due':payload['quote_due'],'label_type':payload['trained_target']},'PENDING_REAL_FUTURE_QUOTE')
                        except Exception as exc:cycle['models'][symbol]={'status':'INSUFFICIENT_EVIDENCE','reason':type(exc).__name__+':'+str(exc)[:100]}
                        from .atlas_news_pipeline import NewsStore
                        try:
                            with NewsStore(lake.root) as news:evidence=news.evidence_at(symbol,iso(time.time()),limit=10)
                            for item in evidence:
                                key=item['article_id'];sha=_sha(item)
                                # The creation time is NOW, never the old publication time.
                                memory.record('news-'+symbol+'-'+sha,symbol,stamp,time.time(),'NEWS_EVENT',sha,
                                    {'symbol':symbol,'article_id':key,'source':'verified PIT NewsStore reference','sentiment_is_estimate':True})
                        except Exception as exc:cycle['errors'].append({'symbol':symbol,'phase':'optional_news','error_type':type(exc).__name__})
                        if shadow:
                            # This is the same LangGraph used by Watch, but its
                            # PaperAccount starts in a NEW isolated study folder.
                            from .atlas_agent import cycle as agent_cycle
                            try:
                                action=agent_cycle(lake,symbol=symbol,checkpoint=session_dir/'agent_checkpoints.sqlite',thread_id='m6-'+symbol,
                                    paper_root=session_dir,enable_llm=False,sync_enabled=sync_enabled)
                                cycle['shadow'].append(action)
                            except Exception as exc:cycle['shadow'].append({'symbol':symbol,'status':'FAIL_CLOSED','error_type':type(exc).__name__,'reason':str(exc)[:120]})
                    except Exception as exc:cycle['errors'].append({'symbol':symbol,'phase':'observation','error_type':type(exc).__name__})
                cycle['reconciliation']=ledger.reconcile()
                for key,raw_outcome,sha in ledger.db.execute('SELECT prediction_id,payload,payload_sha FROM m6_outcomes'):
                    p=json.loads(raw_outcome);symbol=ledger.db.execute('SELECT symbol FROM m6_predictions WHERE prediction_id=?',(key,)).fetchone()[0]
                    memory.record('outcome-'+key,symbol,p['future_observed_epoch'],p['available_at'],'MATURED_FORECAST_OUTCOME',sha,
                        {'symbol':symbol,'prediction_id':key,'label_type':'MID_TO_MID_RETURN_QUOTE_PROXY','exchange_PnL':None},'SCORED_REAL_FUTURE_QUOTES_NOT_FILLS')
                cycle['finished_at']=time.time()
                with ledger.db:ledger.db.execute('INSERT INTO m6_cycles(created,payload) VALUES(?,?)',(cycle['observed_at'],json.dumps(cycle)))
                session['cycles_completed']+=1;session['last_completed']=cycle['finished_at'];_save_atomic(path,session);cycles.append(cycle)
                print(json.dumps({'cycle':session['cycles_completed'],'forecasts_registered':cycle['registered'],'quote_requests':cycle['quote_requests'],'errors':cycle['errors']},ensure_ascii=False),flush=True)
                if max_cycles is not None and len(cycles)>=max_cycles:break
                delay=max(0,interval_seconds-(time.monotonic()-start))
                while delay>0 and not stop_event.is_set():
                    before=time.monotonic();stop_event.wait(min(60,delay));delay-=time.monotonic()-before
            if time.time()>=session['deadline_epoch']:
                if shadow:session['liquidation']=liquidate_paper_positions(SimpleNamespace(root=session_dir),fee=.001,require_watch_deadline=True)
                session['status']='OBSERVATION_WINDOW_FINISHED_REVIEW_COVERAGE'
            _save_atomic(path,session)
            return {'status':'STOPPED_GRACEFULLY' if stop_event.is_set() else 'BOUNDED_RUN_FINISHED',
                'session':session,'cycles':cycles,'forward':ledger.status(),'strategy':strategy_status(session_dir,ledger),'registry':registry,'memory':memory.status()}
        finally:memory.close()
    finally:ledger.release();ledger.close()

def main():
    import signal
    from .atlas_archive import Lake
    p=argparse.ArgumentParser(description='M6 public foreground observation; no exchange orders')
    p.add_argument('command',choices=['collect','status','reconcile']);p.add_argument('--root',default='atlas_store')
    p.add_argument('--session-dir',default='atlas_store/research_challengers/milestone6/forward_v1')
    p.add_argument('--hours',type=int,default=48);p.add_argument('--top',type=int,default=2)
    p.add_argument('--interval-seconds',type=int,default=900);p.add_argument('--max-cycles',type=int)
    p.add_argument('--shadow',action='store_true');p.add_argument('--no-sync',action='store_true')
    a=p.parse_args();event=threading.Event()
    for sig in (signal.SIGINT,signal.SIGTERM):signal.signal(sig,lambda *_:event.set())
    if a.command=='collect':
        lake=Lake(a.root)
        try:result=collect(lake,a.session_dir,top=a.top,hours=a.hours,interval_seconds=a.interval_seconds,max_cycles=a.max_cycles,
            shadow=a.shadow,stop_event=event,sync_enabled=not a.no_sync)
        finally:lake.db.close()
    else:
        ledger=ModelObservationLedger(a.session_dir)
        try:
            if a.command=='reconcile':ledger.reconcile()
            result={'forward':ledger.status(),'strategy':strategy_status(a.session_dir,ledger)}
        finally:ledger.close()
    _save_atomic(Path(a.session_dir)/'last_result.json',result)
    print(json.dumps(result,ensure_ascii=False,default=str))

if __name__=='__main__':main()
