"""Durable multi-specialist LangGraph research/shadow agent.
All market facts come from Wallex records; only REAL article headlines are considered.
Has NO order-submission tool; persistent session memory lives in SQLite.
Stage 2 source: abstract broker pattern, independently authored; see third_party/SOURCES.md.
"""
from __future__ import annotations
import json, sqlite3, time
from pathlib import Path
from typing import TypedDict
import pandas as pd
from .atlas_archive import Lake
from .atlas_signals import features,strategies
from .atlas_news import news_known_at
from .atlas_deep import predict_latest, verified_champion
from .atlas_shadow import PaperAccount
from .atlas_broker import ShadowBroker,OrderIntent
import hashlib
from .live_scout import measure_book
from .market import depth
from .atlas_context import ContextStore,make_packet
from .atlas_rationale import explain_for_state
from .atlas_mode import ExecutionMode,require_mode
from .atlas_data_sync import DataSyncManager

class AgentState(TypedDict,total=False):
    symbol:str
    observations:dict
    technical:dict
    news:dict
    prediction:dict
    veto_reasons:list[str]
    decision:str
    explanation:dict
    context_packet:dict
    advisory_rationale:dict
    review:dict
    evidence:dict


def select_symbol(lake):
    markets=[]
    for (raw,) in lake.db.execute('SELECT metadata FROM assets'):
        m=json.loads(raw)
        if m.get('is_spot') is True and m.get('quote_asset')=='TMN':
            try:v=float(m.get('quote_volume_24h') or 0)
            except (ValueError,TypeError):v=0
            markets.append((v,m['symbol']))
    if not markets:raise RuntimeError('No TMN spot market discovered; run discover')
    return max(markets)[1]


def cycle(lake=None,symbol=None,checkpoint=None,thread_id='research-main',fee=.001,mode=ExecutionMode.SHADOW,enable_llm=False,paper_root=None,sync_enabled=True):
    require_mode(mode,permitted=(ExecutionMode.SHADOW,),operation='agent.cycle')
    try:
        from langgraph.graph import StateGraph,START,END
        from langgraph.checkpoint.sqlite import SqliteSaver
    except ImportError as e:
        raise RuntimeError('LangGraph optional dependencies not installed; run pip install -r requirements-agent.txt') from e
    lake=lake or Lake()
    from types import SimpleNamespace
    account_lake=SimpleNamespace(root=Path(paper_root).resolve()) if paper_root is not None else lake
    account_lake.root.mkdir(parents=True,exist_ok=True)
    symbol=symbol or select_symbol(lake)
    import torch
    model=verified_champion(lake.root/'models')
    # A market without recent, SHA-verified, continuous model input cannot
    # enter the graph or reach the paper broker. Startup sync is bounded and
    # uses public GET only; it never backfills the catalog during this cycle.
    try:
        cfg=torch.load(model,map_location='cpu',weights_only=True)['config']
        required_resolution=cfg['resolution']
        sync=DataSyncManager(lake)
        sync_result=(sync.run(top=1,scope='catalog',target_resolutions=(required_resolution,),
                             max_windows=4,purpose='agent-startup',symbols=(symbol,)) if sync_enabled else {'status':'SYNC_DISABLED'})
        ready=sync.market_readiness(symbol,required_resolution)
    except Exception as exc:
        sync_result={'status':'DATA_SYNC_CHECK_FAILED','error_type':type(exc).__name__}
        ready={'ready':False,'reason':'DATA_SYNC_CHECK_FAILED'}
    if not ready.get('ready'):
        return {'decision':'NO_PAPER_ACTION_DATA_NOT_READY','symbol':symbol,'data_sync':sync_result,
                'data_readiness':ready,'trade_execution':'DISABLED',
                'guarantee':'No graph forecast, broker intent, paper action or real order was created.'}
    def context_node(state:AgentState):
        # Trusted local code selects tool/skill scope. No article can widen it.
        packet=make_packet(lake,phase='agent-cycle',token_budget=1800,mode=mode,symbol=state.get('symbol'))
        from .atlas_memory import ResearchMemory
        research=ResearchMemory(lake.root,mode=mode)
        try:
            packet['research_memory']=[{k:r[k] for k in ('event_id','memory_type','source_hash','evaluation_status','recency','relevance')}
                for r in research.retrieve(state['symbol'],pd.Timestamp.now(tz='UTC').isoformat(),limit=8)]
        finally:research.close()
        return {'context_packet':packet}
    def market_node(state:AgentState):
        raw=depth(state['symbol'])  # REAL currently observed Wallex depth
        book=measure_book(raw,notional_tmn=250000,fee_rate=fee)
        stamp=time.time()
        from .atlas_forward import ForwardLedger
        observer=ForwardLedger(lake.root)
        try:
            quote_id=observer.record_real_quote(state['symbol'],raw,book,stamp)
            quote_hash=observer.db.execute('SELECT receipt_sha256 FROM quotes WHERE id=?',(quote_id,)).fetchone()[0]
        finally:observer.close()
        account=PaperAccount(account_lake)
        try:
            if not account.verify():raise RuntimeError('PAPER_CHAIN_INVALID')
            bids={}
            for held, in account.db.execute('SELECT symbol FROM positions'):
                bids[held]=measure_book(depth(held),notional_tmn=250000,fee_rate=fee)['best_bid_tmn']
            equity=account.update_equity_from_observed_quotes(bids,fee=fee)
            portfolio={'cash_tmn':float(account.get('cash_tmn')),'positions':account.db.execute('SELECT symbol,quantity,entry_cost FROM positions').fetchall(),
                'stopped':account.get('stopped')=='1','equity':equity,'all_held_assets_marked_from_real_bids':True}
        finally:account.close()
        return {'observations':{'book':book,'observed_at_unix':stamp,'quote_id':quote_id,'quote_receipt_sha256':quote_hash,'portfolio':portfolio,
                    'observation_id':hashlib.sha256(json.dumps({'symbol':state['symbol'],'raw':raw,'received':stamp},sort_keys=True).encode()).hexdigest(),
                    'data_provenance':'Wallex public REST depth, local observed timestamp'}}
    def indicators_node(state:AgentState):
        cfg=torch.load(model,map_location='cpu',weights_only=True)['config']
        seg=lake.load(state['symbol'],cfg['resolution'])[-1]
        sec=int(cfg['resolution'])*60
        if time.time()-int(seg.timestamp.iloc[-1])>3*sec:
            return {'technical':{'signal':None,'reason':'stale genuine candle history'}}
        f=features(seg);states=strategies(f)
        results=lake.root/'research'/'chronological_winners.csv'
        chosen=None
        if results.exists():
            df=pd.read_csv(results)
            match=df[df.symbol==state['symbol']]
            if len(match): chosen=str(match.iloc[-1].strategy)
        flag=bool(states[chosen].iloc[-1]) if chosen in states else None
        import math
        regime={k:float(f[k].iloc[-1]) for k in ('ret24','volatility12','adx14') if k in f and math.isfinite(float(f[k].iloc[-1]))}
        if 'adx14' in regime:regime['descriptive_state']='TRENDING_ADX_GE_25' if regime['adx14']>=25 else 'LOW_ADX'
        return {'technical':{'selected_strategy':chosen,'current_signal':flag,
                             'last_candle_ts':int(seg.timestamp.iloc[-1]),
                             'regime_evidence':regime,
                             'selection_origin':'chronological_training_selection' if chosen else 'none'}}
    def news_node(state:AgentState):
        asof=pd.Timestamp.now(tz='UTC').isoformat()
        try:articles=news_known_at(lake,asof)
        except Exception:articles=[]  # Optional news outage is not a Core veto.
        relevant=[a for a in articles if any(word in a['title'].lower() for word in
                         ('crypto','bitcoin','ethereum','exchange','wallex'))]
        # Models are not allowed to score historical headlines retroactively before observed availability.
        negative=[]
        for a in relevant:
            score=a.get('sentiment')
            if not isinstance(score,list):continue
            scores={str(x['label']).lower():float(x['score']) for x in score}
            if scores.get('negative',0)>.80:negative.append(a['url'])
        # New scores stay advisory; they are deliberately not copied into the
        # legacy strong_negative_urls veto consumed by the existing risk node.
        from .atlas_news_pipeline import NewsStore
        try:
            with NewsStore(lake.root) as store:
                advisory=store.evidence_at(state['symbol'],asof,limit=20)
                news_features=store.features_at(state['symbol'],asof)
                memory=store.record_memory(state['symbol'],asof,mode)
        except Exception as exc:
            advisory=[];news_features={'status':'ADVISORY_UNAVAILABLE','error_type':type(exc).__name__};memory=None
        return {'news':{'known_articles':len(relevant),'strong_negative_urls':negative[:10],
                        'point_in_time':'available_at<=decision_asof_only',
                        'advisory_evidence':advisory,'research_news_features':news_features,
                        'news_memory_receipt':memory,'authority':'ADVISORY_ONLY_NO_NEW_VETO'}}
    def predictive_node(state:AgentState):
        seconds=__import__('wallex_bot.market',fromlist=['ALLOWED_RESOLUTIONS']).ALLOWED_RESOLUTIONS[required_resolution]
        segment=lake.load(state['symbol'],required_resolution)[-1]
        if int(segment.timestamp.iloc[-1])+seconds>time.time():raise RuntimeError('UNCLOSED_MODEL_INPUT')
        result=predict_latest(lake,model,state['symbol'])
        if time.time()-(result['feature_end_ts']+seconds)>2*seconds:raise RuntimeError('STALE_MODEL_INPUT')
        result['model_sha256']=hashlib.sha256(model.read_bytes()).hexdigest()
        result['feature_source_receipts']=[{'file':f,'sha256':sha} for f,sha in lake.db.execute(
            "SELECT filename,sha256 FROM chunks WHERE symbol=? AND resolution=? AND status='COMPLETE' ORDER BY filename",(state['symbol'],required_resolution))]
        return {'prediction':result}
    def risk_node(state:AgentState):
        from .atlas_review import review
        cutoff=time.time()
        evidence={'symbol':state['symbol'],'decision_time':cutoff,'available_at':cutoff,
            'observation_id':state['observations']['observation_id'],'technical':state['technical'],
            'news':state['news'],'prediction':state['prediction'],'readiness':ready,
            'book':state['observations']['book'],'portfolio':state['observations']['portfolio'],
            'quote_id':state['observations']['quote_id'],'quote_receipt_sha256':state['observations']['quote_receipt_sha256'],
            'regime':state['technical'].get('regime_evidence',{}),
            'memory_references':state['context_packet'].get('research_memory',[])}
        result=review(evidence)
        return {'veto_reasons':result['proposal']['veto_reasons'],'review':result,'evidence':evidence}
    def rationale_node(state:AgentState):
        # Stage 7: advisory ONLY; its sole output is text+evidence receipt.
        # No downstream trading inputs depend on this node, even if the local
        # LLM returns untrusted instructions or is offline.
        if not enable_llm:return {'advisory_rationale':{'status':'OPTIONAL_LLM_DISABLED','authority':'ADVISORY_ONLY'}}
        try:
            advisory=explain_for_state(lake.root,state)
        except Exception as exc:
            advisory={'status':'ADVISORY_UNAVAILABLE','reason_code':type(exc).__name__,
                      'authority':'ADVISORY_ONLY'}
        return {'advisory_rationale':advisory}

    def shadow_node(state:AgentState):
        # PAPER only. Guarded, persistent and explainable; never invokes Wallex order APIs.
        if time.time()-state['observations']['observed_at_unix']>60:raise RuntimeError('STALE_ORDER_EVIDENCE')
        account=PaperAccount(account_lake)
        try:
            from .atlas_review import broker_evidence
            evidence=broker_evidence(state['prediction'],state['review'])
            stamp=state['observations']['observed_at_unix']
            intent_id='agentv6-'+hashlib.sha256((state['symbol']+'|'+str(state['prediction']['feature_end_ts'])+'|'+str(model)).encode()).hexdigest()[:48]
            action=ShadowBroker(account).submit(OrderIntent(intent_id,state['symbol'],'AUTO'),
                forecast=evidence,book=state['observations']['book'],fee=fee).reason
            from .atlas_orchestration import DecisionLedger
            row=account.db.execute("SELECT payload FROM events WHERE json_extract(payload,'$.client_order_id')=? ORDER BY id DESC LIMIT 1",(intent_id,)).fetchone()
            risk_replay=json.loads(row[0]).get('risk_replay_inputs') if row else None
            ledger=DecisionLedger(account_lake.root)
            try:ledger.record(state['evidence'],state['review'],action,risk_replay)
            finally:ledger.close()
            with account.db:
                account.log(state['symbol'],'MULTI_AGENT_EXPLANATION',{
                    'market_observation':state['observations'],'technical':state['technical'],
                    'news':state['news'],'model_prediction':state['prediction'],
                    'veto_reasons':state['veto_reasons'],'paper_action':action,
                    'broker_client_order_id':intent_id,
                    'llm_advisory':state.get('advisory_rationale',{'status':'NO_RATIONALE'})})
        finally:account.close()
        return {'decision':action,'explanation':{'model_file':str(model),'veto':state['veto_reasons'],
                 'audit_db':str(account_lake.root/'shadow.sqlite'),
                 'trade_execution':'DISABLED',
                 'llm_advisory':state.get('advisory_rationale',{'status':'NO_RATIONALE'})}}
    graph=StateGraph(AgentState)
    for name,fn in [('context_planner_agent',context_node),('market_data_agent',market_node),('technical_agent',indicators_node),
                    ('point_in_time_news_agent',news_node),('deep_forecast_agent',predictive_node),
                    ('risk_agent',risk_node),('llm_rationale_agent',rationale_node),('shadow_execution_agent',shadow_node)]:graph.add_node(name,fn)
    graph.add_edge(START,'context_planner_agent')
    path=['context_planner_agent','market_data_agent','technical_agent','point_in_time_news_agent',
          'deep_forecast_agent','risk_agent','llm_rationale_agent','shadow_execution_agent']
    for a,b in zip(path,path[1:]):graph.add_edge(a,b)
    graph.add_edge(path[-1],END)
    dbpath=Path(checkpoint or lake.root/'agent_checkpoints.sqlite');dbpath.parent.mkdir(parents=True,exist_ok=True)
    conn=sqlite3.connect(dbpath,check_same_thread=False)
    try:
        compiled=graph.compile(checkpointer=SqliteSaver(conn))
        output=compiled.invoke({'symbol':symbol},config={'configurable':{'thread_id':thread_id}})
    finally:conn.close()
    memory=ContextStore(lake.root,mode=mode)
    try:
        evidence={'symbol':symbol,'decision':output['decision'],'model_digest':output['prediction'].get('model_sha256'),
                  'source':'LangGraph-shadow-ledger','context_skills':[x['name'] for x in output['context_packet']['task_skills']]}
        memory_hash=memory.record('GRAPH_DECISION',str(lake.root/'shadow.sqlite'),evidence)
    finally:memory.close()
    from .atlas_memory import ResearchMemory
    structured=ResearchMemory(lake.root,mode=mode)
    try:
        stamp=output['evidence']['decision_time']
        structured.record('decision-'+output['review']['proposal']['source_evidence_hash'],symbol,stamp,time.time(),
            'DECISION_RISK_VETO',output['review']['review_sha256'],{'symbol':symbol,'decision':output['decision'],
                'veto_reasons':output['veto_reasons'],'model_sha256':output['prediction'].get('model_sha256')})
    finally:structured.close()
    return {'decision':output['decision'],'explanation':output['explanation'],
            'context_memory_event_sha256':memory_hash,
            'context_policy':'trusted fixed context + lazy skills + bounded SQLite-backed memory',
            'symbol':symbol,'checkpoint_db':str(dbpath),
            'review':output['review'],'observation_id':output['observations']['observation_id'],
            'guarantee':'NO REAL ORDER FUNCTIONS EXIST IN THIS AGENT'}
