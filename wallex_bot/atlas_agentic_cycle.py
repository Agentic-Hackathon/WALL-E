"""M8 opt-in LangGraph research cycle over shared Atlas contracts.

No duplicate market GETs: use the independent sampler's actual receipts.
Existing Champion only may reach DynamicShadowBroker; news/pattern/memory
remain unqualified for order influence until separately validated/licensed.
"""
import json,math,sqlite3,time
from datetime import datetime,timezone
from pathlib import Path
from typing import TypedDict
from .atlas_forward import _sha,_canon
from .atlas_agentic_review import board,ABLATIONS
from .atlas_dynamic_shadow import DynamicShadowBroker,account_snapshot,replay
from .atlas_technical_evidence import technical_evidence
from .atlas_patterns import PatternIndex,DEFAULT_INDEX,make_query
from .atlas_portfolio import allocate,cost_audit
from .atlas_study import risk_estimates
from .atlas_memory import ResearchMemory

class CycleState(TypedDict,total=False):
    evidence:dict
    review:dict
    intent:dict
    receipt:dict
    allocation:dict
    allocation_inputs:dict

class AgenticLedger:
    def __init__(self,directory):
        self.db=sqlite3.connect(Path(directory)/'agentic_decisions.sqlite',timeout=30)
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('''CREATE TABLE IF NOT EXISTS agentic_decisions_v8(id TEXT PRIMARY KEY,created REAL NOT NULL,
            symbol TEXT NOT NULL,payload TEXT NOT NULL,sha256 TEXT NOT NULL)''');self.db.commit()
    def record(self,payload):
        key=payload['intent']['intent_id'];digest=_sha(payload)
        with self.db:
            old=self.db.execute('SELECT sha256 FROM agentic_decisions_v8 WHERE id=?',(key,)).fetchone()
            if old and old[0]!=digest:raise ValueError('M8_DECISION_EVIDENCE_CONFLICT')
            self.db.execute('INSERT OR IGNORE INTO agentic_decisions_v8 VALUES(?,?,?,?,?)',(key,time.time(),payload['evidence']['symbol'],_canon(payload),digest))
        return key
    def replay(self):
        result=[]
        for key,raw,sha in self.db.execute('SELECT id,payload,sha256 FROM agentic_decisions_v8 ORDER BY created'):
            p=json.loads(raw);repeated=board(p['evidence'])
            result.append({'id':key,'receipt_hash_valid':_sha(p)==sha,'review_identical':repeated==p['review'],**replay(p['receipt'])})
        return result
    def close(self):self.db.close()


def research_cycle(lake,directory,observer,contract):
    from langgraph.graph import StateGraph,START,END
    from langgraph.checkpoint.sqlite import SqliteSaver
    from .atlas_news_features import advisory_packet
    from .atlas_intelligence_sync import IntelligenceSyncManager
    directory=Path(directory);symbols=contract['settings']['symbols'];quotes={};predictions={};candidates={};errors=[]
    for symbol in symbols:
        row=observer.db.execute('SELECT id FROM quotes WHERE symbol=? ORDER BY observed_epoch DESC LIMIT 1',(symbol,)).fetchone()
        if row:quotes[symbol]=observer.quote(row[0])
        row=observer.db.execute("SELECT prediction_id,payload,payload_sha FROM m6_predictions WHERE symbol=? AND model='champion' ORDER BY decision DESC LIMIT 1",(symbol,)).fetchone()
        if row:
            p=json.loads(row[1])
            if _sha(p)!=row[2]:raise ValueError('CHAMPION_FORECAST_HASH_INVALID')
            if 0<=time.time()-p['prediction_available_at']<=p['forecast_horizon']:predictions[symbol]=p
    broker=DynamicShadowBroker(directory,contract);decisions=AgenticLedger(directory);memory=ResearchMemory(directory)
    pattern_index=None;checkpoints=None;results=[]
    try:
        index_dir=contract['settings']['intelligence']['pattern_index_dir']
        if (Path(index_dir)/'patterns.sqlite').exists():pattern_index=PatternIndex(index_dir,readonly=True);pattern_index.verify_sources()
        vol,corr=risk_estimates(lake,symbols,time.time())
        for symbol in symbols:
            p=predictions.get(symbol);q=quotes.get(symbol)
            if not p or not q:continue
            meta=json.loads(lake.db.execute('SELECT metadata FROM assets WHERE symbol=?',(symbol,)).fetchone()[0])
            candidates[symbol]={'quote':q,'forecast':{'quantile_log_returns':{k:p[k] for k in ('q10','q50','q90')}},
                'prediction_available_at':p['prediction_available_at'],'prediction_id':p['prediction_id'],
                'spot_tmn':meta.get('is_spot') is True and meta.get('quote_asset')=='TMN','metadata':meta,'fee':.001,**vol.get(symbol,{})}
        runtime=json.loads(observer.db.execute("SELECT payload FROM study_runtime_v7 WHERE key='session'").fetchone()[0])
        cycle_id=str(int(time.time()//900)*900)
        quote_cohort=_sha({s:q['receipt_sha256'] for s,q in quotes.items()})
        # Exits are considered before entries, but every leg rechecks actual
        # holdings and the common atomic turnover/cost budget. No switch assumes
        # that its exit succeeded or buys with projected proceeds.
        held={s for s, in broker.db.execute('SELECT symbol FROM positions')}
        for symbol in sorted(symbols,key=lambda s:(s not in held,s)):
            try:
                p=predictions.get(symbol);q=quotes.get(symbol)
                if q is None or not 0<=time.time()-q['observed_epoch']<=30:
                    errors.append({'symbol':symbol,'reason':'WAITING_FRESH_INDEPENDENT_SAMPLER_QUOTE'});continue
                before=account_snapshot(broker.account,quotes)
                technical=technical_evidence(lake,symbol)
                pattern={'status':'PATTERN_INDEX_UNAVAILABLE','decision_path_eligible':False}
                if pattern_index:
                    try:pattern=pattern_index.search(make_query(lake,symbol))
                    except ValueError as exc:pattern={'status':str(exc),'decision_path_eligible':False}
                cutoff=time.time();asof=datetime.fromtimestamp(cutoff,timezone.utc).isoformat()
                news=advisory_packet(lake.root,symbol,asof)
                # Preserve article identity/linking but do not operationalize
                # NC model weights, or replace missing sentiment with neutral.
                article_ids=[item['article_id'] for item in news['evidence']]
                news_packet={'article_ids':article_ids,'decision_use_licensed':False,'value_added_validated':False,
                    'sentiment':None,'license_status':'FINBERT_CONTEST_USE_NOT_AUTHORIZED','strong_negative_urls':[],
                    'advisory_evidence':[{'article_id':i} for i in article_ids],'status':news['research_features'].get('status','OPTIONAL_NEWS_INSUFFICIENT')}
                recent=memory.retrieve(symbol,asof,limit=12)
                prediction={'quantile_log_returns':{k:p[k] for k in ('q10','q50','q90')},'model_sha256':p['model_sha256'],
                    'prediction_id':p['prediction_id'],'forecast_horizon':2700,'feature_recipe':p['feature_recipe']} if p else {'quantile_log_returns':{'q10':None,'q50':None,'q90':None}}
                audit=cost_audit(q,500000);ready=IntelligenceSyncManager(lake).core_preflight(symbol)
                st=technical.get('supertrend_trailing_band_v1',{}).get('direction');kijun=technical.get('ichimoku',{}).get('kijun26')
                # Research-only technical filter; Champion feature inputs and
                # weights are not changed. Missing/stale technical is explicit.
                signal=st==1 if st is not None and kijun is not None and technical['status']=='VERIFIED_CLOSED_TECHNICAL_EVIDENCE' else None
                evidence={'symbol':symbol,'decision_time':cutoff,'available_at':cutoff,'observation_id':q['receipt_sha256'],
                    'quote_receipt_sha256':q['receipt_sha256'],'technical':{'current_signal':signal,'origin':'M8_RESEARCH_SUPERTREND_FILTER_NOT_VALIDATED_PROMOTION'},
                    'technical_extended':technical,'news':news_packet,'prediction':prediction,'readiness':ready,'book':audit,'portfolio':before,
                    'regime':{'supertrend_direction':st,'atr14':technical.get('supertrend_trailing_band_v1',{}).get('atr14')},
                    'research_memory':recent,'pattern':pattern,'model_feature_source':p,'source_contract_sha256':contract['contract_sha256']}
                def review_node(state):return {'review':board(state['evidence'])}
                def sizing_node(state):
                    # Re-read inside the later broker transaction too; this
                    # advisory snapshot never reserves future sale proceeds.
                    current=account_snapshot(broker.account,quotes)
                    inputs={'account':current,'candidates':candidates,'correlations':[[a,b,v] for (a,b),v in sorted(corr.items())]}
                    proposal=allocate('confidence_aware',current,candidates,now=state['evidence']['decision_time'],correlations=corr)
                    own=next((x for x in current['positions'] if x[0]==symbol),None);action='HOLD' if own else 'STAY_IN_CASH';amount=None;quantity=None;purpose='STRATEGY'
                    terminal=time.time()>=runtime['deadline_epoch']-contract['settings']['intelligence']['terminal_exit_window_seconds']
                    if own and terminal:action='SELL';quantity=own[1];purpose='FINAL_TMN'
                    elif own:
                        assessment=broker.account.risk.assess_equity(current['nav_tmn'],current['high_water_tmn'],current['stopped'])
                        gate=broker.account.risk.evaluate(symbol,state['review']['forecast_for_gate'],audit,current['cash_tmn'],current['positions'],assessment.stopped,.001)
                        if gate.action=='PAPER_SELL':
                            quantity=min(own[1],current['nav_tmn']*.1/q['mid']);action='REDUCE' if quantity<own[1] else 'SELL'
                    elif not terminal and time.time()+3000<=runtime['deadline_epoch']:
                        weight=proposal.get('target_weights',{}).get(symbol,0)
                        if weight and state['review']['recommendation']=='EVALUATE_WITH_UNCHANGED_RISKGATE':
                            width=p['q90']-p['q10'];margin=p['q10']-(audit['estimated_roundtrip_log_cost'] or 0)
                            penalty=min(1.,max(0,margin/max(width,1e-8)))
                            amount=weight*current['nav_tmn']*penalty
                            if amount>=100000:action='BUY'
                    reasons=list(state['review']['veto_reasons'])+proposal.get('rejections',{}).get(symbol,[])+proposal.get('rejections',{}).get('PORTFOLIO',[])
                    if not reasons:reasons=[proposal['status'] if action in ('STAY_IN_CASH','REJECT') else 'CURRENT_POSITION_OR_GATE_AUTHORIZED_ACTION']
                    intent={'intent_id':_sha({'contract':contract['contract_sha256'],'cycle':cycle_id,'quote_cohort':quote_cohort,'symbol':symbol,'prediction':p['prediction_id'] if p else None,'action':action}),
                        'symbol':symbol,'action':action,'notional_tmn':amount if action=='BUY' else None,'quantity':quantity,
                        'prediction_id':p['prediction_id'] if p else None,'purpose':purpose,'sizing_version':'CONSERVATIVE_M7_CAPS_EDGE_OVER_INTERVAL_V1',
                        'limits':'existing RiskGate + min 80% cash, 10% cycle turnover, 0.1% cost','reason_codes':reasons}
                    return {'intent':intent,'allocation':proposal,'allocation_inputs':inputs}
                def broker_node(state):
                    return {'receipt':broker.submit(state['intent'],forecast=state['review']['forecast_for_gate'],quotes=quotes,review=state['review'],cycle_id=cycle_id)}
                def memory_node(state):
                    key=decisions.record(state);receipt=state['receipt'];created=receipt['actual_created_at']
                    memory.record('m8-decision-'+key,symbol,created,created,'DECISION_RISK_VETO',_sha(state),
                        {'decision_id':key,'symbol':symbol,'action':state['intent']['action'],'reason':receipt['reason'],
                            'paper_status':receipt['status'],'paper_nav_tmn':receipt['after']['nav_tmn'],'exchange_pnl':None,
                            'evidence_sha256':state['review']['source_evidence_hash']},'SHADOW_ESTIMATE_NOT_EXCHANGE_PROFIT')
                    return {}
                graph=StateGraph(CycleState)
                for name,fn in [('specialists_and_cross_review',review_node),('portfolio_manager',sizing_node),('unchanged_risk_and_shadow_boundary',broker_node),('explanation_and_pit_memory',memory_node)]:graph.add_node(name,fn)
                path=['specialists_and_cross_review','portfolio_manager','unchanged_risk_and_shadow_boundary','explanation_and_pit_memory'];graph.add_edge(START,path[0])
                for a,b in zip(path,path[1:]):graph.add_edge(a,b)
                graph.add_edge(path[-1],END)
                checkpoints=sqlite3.connect(directory/'agentic_checkpoints.sqlite',check_same_thread=False)
                try:
                    compiled=graph.compile(checkpointer=SqliteSaver(checkpoints))
                    result=compiled.invoke({'evidence':evidence},config={'configurable':{'thread_id':contract['session_id']+'-'+cycle_id+'-'+symbol+'-'+quote_cohort[:16]}})
                finally:checkpoints.close();checkpoints=None
                results.append({'symbol':symbol,'action':result['intent']['action'],'status':result['receipt']['status'],'reason':result['receipt']['reason'],
                    'decision_id':result['intent']['intent_id'],'agent_count':len(result['review']['agents'])})
            except Exception as exc:errors.append({'symbol':symbol,'error_type':type(exc).__name__,'reason':str(exc)[:150]})
        summary={'decisions':results,'errors':errors,'policy':'M8_OPT_IN_RESEARCH_ONLY','model_promotion':False}
        observer.event('M8_AGENTIC_CYCLE',summary);return summary
    finally:
        if checkpoints:checkpoints.close()
        if pattern_index:pattern_index.close()
        broker.close();decisions.close();memory.close()
