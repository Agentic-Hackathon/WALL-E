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
from .atlas_mode import ExecutionMode,require_mode

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


def cycle(lake=None,symbol=None,checkpoint=None,thread_id='research-main',fee=.001,mode=ExecutionMode.SHADOW):
    require_mode(mode,permitted=(ExecutionMode.SHADOW,),operation='agent.cycle')
    try:
        from langgraph.graph import StateGraph,START,END
        from langgraph.checkpoint.sqlite import SqliteSaver
    except ImportError as e:
        raise RuntimeError('LangGraph optional dependencies not installed; run pip install -r requirements-agent.txt') from e
    lake=lake or Lake()
    symbol=symbol or select_symbol(lake)
    import torch
    def context_node(state:AgentState):
        # Trusted local code selects tool/skill scope. No article can widen it.
        packet=make_packet(lake,phase='agent-cycle',token_budget=1800,mode=mode)
        return {'context_packet':packet}
    model=verified_champion(lake.root/'models')
    def market_node(state:AgentState):
        raw=depth(state['symbol'])  # REAL currently observed Wallex depth
        book=measure_book(raw,notional_tmn=250000,fee_rate=fee)
        return {'observations':{'book':book,'observed_at_unix':time.time(),
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
        return {'technical':{'selected_strategy':chosen,'current_signal':flag,
                             'last_candle_ts':int(seg.timestamp.iloc[-1]),
                             'selection_origin':'chronological_training_selection' if chosen else 'none'}}
    def news_node(state:AgentState):
        asof=pd.Timestamp.now(tz='UTC').isoformat()
        articles=news_known_at(lake,asof)
        relevant=[a for a in articles if any(word in a['title'].lower() for word in
                         ('crypto','bitcoin','ethereum','exchange','wallex'))]
        # Models are not allowed to score historical headlines retroactively before observed availability.
        negative=[]
        for a in relevant:
            score=a.get('sentiment')
            if not isinstance(score,list):continue
            scores={str(x['label']).lower():float(x['score']) for x in score}
            if scores.get('negative',0)>.80:negative.append(a['url'])
        return {'news':{'known_articles':len(relevant),'strong_negative_urls':negative[:10],
                        'point_in_time':'available_at<=decision_asof_only'}}
    def predictive_node(state:AgentState):
        result=predict_latest(lake,model,state['symbol'])
        return {'prediction':result}
    def risk_node(state:AgentState):
        veto=[]
        if state['technical'].get('current_signal') is False:veto.append('technical_strategy_veto')
        if state['technical'].get('current_signal') is None:veto.append('technical_strategy_unverified')
        if state['news']['strong_negative_urls']:veto.append('observed_finbert_high_negative_news')
        if state['observations']['book']['spread_bps']>70:veto.append('wide_spread')
        if not state['observations']['book']['hypothetical_full_roundtrip_depth_available']:
            veto.append('insufficient_visible_book_depth')
        return {'veto_reasons':veto}
    def shadow_node(state:AgentState):
        # PAPER only. Guarded, persistent and explainable; never invokes Wallex order APIs.
        account=PaperAccount(lake)
        try:
            evidence=state['prediction'].copy()
            if state['veto_reasons']:
                evidence['quantile_log_returns']=dict(evidence['quantile_log_returns'])
                evidence['quantile_log_returns']['q10']=None
            stamp=state['observations']['observed_at_unix']
            intent_id='agent-'+hashlib.sha256((state['symbol']+'|'+str(stamp)+'|'+str(model)).encode()).hexdigest()[:48]
            action=ShadowBroker(account).submit(OrderIntent(intent_id,state['symbol'],'AUTO'),
                forecast=evidence,book=state['observations']['book'],fee=fee).reason
            with account.db:
                account.log(state['symbol'],'MULTI_AGENT_EXPLANATION',{
                    'market_observation':state['observations'],'technical':state['technical'],
                    'news':state['news'],'model_prediction':state['prediction'],
                    'veto_reasons':state['veto_reasons'],'paper_action':action})
        finally:account.close()
        return {'decision':action,'explanation':{'model_file':str(model),'veto':state['veto_reasons'],
                 'audit_db':str(lake.root/'shadow.sqlite'),
                 'trade_execution':'DISABLED'}}
    graph=StateGraph(AgentState)
    for name,fn in [('context_planner_agent',context_node),('market_data_agent',market_node),('technical_agent',indicators_node),
                    ('point_in_time_news_agent',news_node),('deep_forecast_agent',predictive_node),
                    ('risk_agent',risk_node),('shadow_execution_agent',shadow_node)]:graph.add_node(name,fn)
    graph.add_edge(START,'context_planner_agent')
    path=['context_planner_agent','market_data_agent','technical_agent','point_in_time_news_agent',
          'deep_forecast_agent','risk_agent','shadow_execution_agent']
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
    return {'decision':output['decision'],'explanation':output['explanation'],
            'context_memory_event_sha256':memory_hash,
            'context_policy':'trusted fixed context + lazy skills + bounded SQLite-backed memory',
            'symbol':symbol,'checkpoint_db':str(dbpath),
            'guarantee':'NO REAL ORDER FUNCTIONS EXIST IN THIS AGENT'}
