"""Resumable foreground SHORT-HORIZON shadow research. Never place live orders."""
from __future__ import annotations
import json
import time
from pathlib import Path
from datetime import datetime, timezone
from .atlas_news import harvest_news
from .atlas_shadow import shadow_cycle, PaperAccount
from . import market
from .atlas_context import ContextStore,make_packet


def _save_state(path, state):
    tmp=Path(str(path)+'.partial')
    tmp.write_text(json.dumps(state,indent=2,ensure_ascii=False),encoding='utf8')
    tmp.replace(path)


def run(lake, hours=48, interval_seconds=900, top=8):
    if not 1<=hours<=72:raise ValueError('Research watch hours must be 1..72')
    if interval_seconds<60 or interval_seconds>3600:raise ValueError('Polling interval outside safe range')
    if not 1<=top<=24:raise ValueError('Select up to 24 market observations per cycle')
    if not lake.symbols('tmn-spot'):lake.discover()
    session_path=lake.root/'watch_session.json'
    now=time.time()
    if session_path.is_file():
        state=json.loads(session_path.read_text(encoding='utf8'))
    else:state={}
    if state.get('status')!='RUNNING' or state.get('hours')!=hours:
        state={'started_at_utc':datetime.now(timezone.utc).isoformat(),
               'started_epoch':now,'deadline_epoch':now+hours*3600,
               'hours':hours,'status':'RUNNING','cycles_completed':0,
               'mode':'FOREGROUND_REAL_QUOTES_SHADOW_NO_EXCHANGE_ORDERS'}
        _save_state(session_path,state)
    deadline=float(state['deadline_epoch'])
    while time.time()<deadline:
        started=time.monotonic()
        # All source observations are actual exchange history. Caching prevents
        # duplicate stable window requests; interruptions preserve existing data.
        summary=lake.harvest(scope='tmn-spot',days=2,resolutions=('1',),
                             max_markets=top,chunk_hours=3,delay=.4)
        derived=lake.materialize_derived(['15'])
        news=harvest_news(lake,hours=24)
        try:
            context_packet=make_packet(lake,phase='watch')
        except Exception as exc:
            # A compromised/invalid memory chain cannot influence an action.
            context_packet=None
            result={'shadow_cycle_skipped':'CONTEXT_INTEGRITY_OR_BUDGET_FAILURE',
                    'error_type':type(exc).__name__}
        try:
            if context_packet is not None: result=shadow_cycle(lake,top=top)
        except Exception as exc:
            result={'shadow_cycle_failed':type(exc).__name__+': '+str(exc)[:180]}
        watch_record={'utc':datetime.now(timezone.utc).isoformat(),
                'downloaded_chunks':summary['complete'],'failed_chunks':summary['failed'],
                'news':news,'derived':derived,'shadow':result,
                'context_engineering':{'enabled':context_packet is not None,
                    'skills_loaded':len(context_packet['task_skills']) if context_packet else 0,
                    'registered_tools_for_phase':len(context_packet['pinned_start']['tool_menu']) if context_packet else 0}}
        with (lake.root/'watch_log.jsonl').open('a',encoding='utf8') as log:
            log.write(json.dumps(watch_record,ensure_ascii=False,default=str)+'\n')
        # Store compact, machine-verifiable observations. Raw details remain in
        # watch_log.jsonl, forward_observations.sqlite and shadow.sqlite.
        context_store=ContextStore(lake.root)
        try:
            context_store.record('WATCH_CYCLE',str(lake.root/'watch_log.jsonl'),{
                'cycles_completed':state['cycles_completed']+1,
                'downloaded_chunks':summary['complete'],
                'failed_chunks':summary['failed'],
                'observed_markets':top,
                'shadow_actions':[r.get('action','ERROR') for r in result.get('events',[])],
                'recorded_news':news.get('fetched_articles_count_attempted',0)})
            if 'shadow_cycle_failed' in result:
                incident=context_store.record('RESEARCH_INCIDENT',str(lake.root/'watch_log.jsonl'),{
                    'error_type':result['shadow_cycle_failed'].split(':')[0],
                    'source':'watch-shadow-cycle'})
                # Lesson remains a research candidate; NEVER auto-tunes strategy.
                context_store.propose_lesson(incident,'Investigate repeated shadow-cycle failures using verified runtime logs')
        finally:context_store.close()
        state['cycles_completed']+=1
        state['last_cycle_finished_utc']=datetime.now(timezone.utc).isoformat()
        _save_state(session_path,state)
        delay=interval_seconds-(time.monotonic()-started)
        if delay>0:time.sleep(min(delay,max(0,deadline-time.time())))

    # The final PAPER liquidation uses real public bids, never invented values.
    paper=PaperAccount(lake)
    try:
        with paper.db:
            for symbol,qty,cost in paper.db.execute('SELECT symbol,quantity,entry_cost FROM positions').fetchall():
                try:
                    from .live_scout import measure_book
                    book=measure_book(market.depth(symbol),notional_tmn=250000,fee_rate=.001)
                    positions=paper.db.execute('SELECT symbol,quantity,entry_cost FROM positions').fetchall()
                    cash=float(paper.get('cash_tmn'))
                    gate=paper.risk.final_tmn_liquidation(symbol,book,cash,positions,.001)
                    if gate.action!='PAPER_SELL':
                        paper.log(symbol,'PAPER_END_CLOSE_REJECTED',{'risk_gate':gate.audit_payload(),
                            'status':'position retained; no invented quote or bypass'})
                        continue
                    proceeds=qty*book['best_bid_tmn']*(1-.001)
                    paper._set('cash_tmn',cash+proceeds)
                    paper.db.execute('DELETE FROM positions WHERE symbol=?',(symbol,))
                    paper.log(symbol,'PAPER_END_OF_WATCH_SELL',{'observed_bid':book['best_bid_tmn'],
                        'proceeds_tmn':proceeds,'risk_gate':gate.audit_payload(),'NOT_A_REAL_FILL':True})
                except Exception as exc:
                    paper.log(symbol,'PAPER_END_CLOSE_FAILED',{'error':type(exc).__name__,
                        'status':'unvalued position; no invented quote'})
        remaining=paper.db.execute('SELECT count(*) FROM positions').fetchone()[0]
        state['status']='COMPLETE' if remaining==0 else 'CLOSED_WITH_UNRESOLVED_PAPER_POSITIONS'
        state['finished_at_utc']=datetime.now(timezone.utc).isoformat()
        state['remaining_paper_positions']=remaining
        _save_state(session_path,state)
        return {'cycles':state['cycles_completed'],
                'last_paper_cash_tmn':paper.get('cash_tmn'),
                'remaining_paper_positions':remaining,
                'watch_session_state':str(session_path),
                'mode':'PAPER ONLY, NOT EXCHANGE EXECUTION'}
    finally:paper.close()
