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
from .atlas_mode import ExecutionMode,require_mode
from .atlas_data_sync import DataSyncManager


def _save_state(path, state):
    tmp=Path(str(path)+'.partial')
    tmp.write_text(json.dumps(state,indent=2,ensure_ascii=False),encoding='utf8')
    tmp.replace(path)


def run(lake, hours=48, interval_seconds=900, top=8,mode=ExecutionMode.SHADOW,stop_event=None):
    require_mode(mode,permitted=(ExecutionMode.SHADOW,),operation='watch.run')
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
        if stop_event is not None and stop_event.is_set():
            _save_state(session_path,state)
            return {'status':'STOPPED_GRACEFULLY_RESUMABLE','cycles':state['cycles_completed'],'watch_session_state':str(session_path)}
        started=time.monotonic()
        # Bounded startup/continuous reconciliation: no full-catalog backfill
        # may block a watch cycle. DataSync reuses the archive progress ledger.
        sync=DataSyncManager(lake)
        feature_plan=sync.feature_sync_plan(symbols=sync._priority_symbols(top,'priority'),profile='watch_core')
        sync_result=sync.run(top=top,scope='priority',target_resolutions=('15',),
                             target_warmup_hours={'15':37.75},max_windows=top,
                             delay=.4,retries=2,backoff_seconds=.5,workers=1,purpose='watch-cycle')
        summary=sync_result.get('harvest',sync_result)
        derived={'requested_by_data_sync':sync_result.get('derived_requested',[])}
        news=harvest_news(lake,hours=24)
        readiness=[sync.feature_readiness(symbol,'watch_core') for symbol in sync_result['plan']['symbols']]
        eligible=[item['symbol'] for item in readiness if item['ready']]
        if not eligible:
            # Fail closed per asset: an unhealthy market cannot reach Shadow,
            # but one unhealthy peer no longer suppresses healthy peers.
            context_packet=None
            result={'shadow_cycle_skipped':'NO_ELIGIBLE_MARKET_DATA',
                    'readiness':readiness}
        else:
            try:
                context_packet=make_packet(lake,phase='watch',mode=mode)
            except Exception as exc:
                # A compromised/invalid memory chain cannot influence an action.
                context_packet=None
                result={'shadow_cycle_skipped':'CONTEXT_INTEGRITY_OR_BUDGET_FAILURE',
                        'error_type':type(exc).__name__}
            try:
                if context_packet is not None: result=shadow_cycle(lake,top=len(eligible),mode=mode,allowed_symbols=eligible)
            except Exception as exc:
                result={'shadow_cycle_failed':type(exc).__name__+': '+str(exc)[:180]}
        watch_record={'utc':datetime.now(timezone.utc).isoformat(),
                'downloaded_chunks':summary.get('complete',0),'failed_chunks':summary.get('failed',0),
                'data_sync_status':sync_result.get('status'),'feature_sync_requirements':feature_plan['feature_requirements'],
                'eligible_markets':eligible,'ineligible_markets':[x['symbol'] for x in readiness if not x['ready']],
                'news':news,'derived':derived,'shadow':result,
                'context_engineering':{'enabled':context_packet is not None,
                    'skills_loaded':len(context_packet['task_skills']) if context_packet else 0,
                    'registered_tools_for_phase':len(context_packet['pinned_start']['tool_menu']) if context_packet else 0}}
        with (lake.root/'watch_log.jsonl').open('a',encoding='utf8') as log:
            log.write(json.dumps(watch_record,ensure_ascii=False,default=str)+'\n')
        # Store compact, machine-verifiable observations. Raw details remain in
        # watch_log.jsonl, forward_observations.sqlite and shadow.sqlite.
        context_store=ContextStore(lake.root,mode=mode)
        try:
            context_store.record('WATCH_CYCLE',str(lake.root/'watch_log.jsonl'),{
                'cycles_completed':state['cycles_completed']+1,
                'downloaded_chunks':summary.get('complete',0),
                'failed_chunks':summary.get('failed',0),
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
        if delay>0:
            if stop_event is None:time.sleep(min(delay,max(0,deadline-time.time())))
            else:stop_event.wait(min(delay,max(0,deadline-time.time())))

    # Stage 3: settlement has one atomic Broker/RiskGate path. No direct
    # position deletion or cash mutation is permitted in this watch loop.
    from .atlas_liquidation import liquidate_paper_positions
    report = liquidate_paper_positions(lake, fee=.001, require_watch_deadline=True)
    state['status'] = ('COMPLETE' if report['remaining_paper_positions'] == 0
                       else 'CLOSED_WITH_UNRESOLVED_PAPER_POSITIONS')
    state['finished_at_utc'] = datetime.now(timezone.utc).isoformat()
    state['remaining_paper_positions'] = report['remaining_paper_positions']
    state['paper_liquidation_status'] = report['status']
    _save_state(session_path, state)
    return {'cycles': state['cycles_completed'],
            'last_paper_cash_tmn': report['paper_cash_tmn'],
            'remaining_paper_positions': report['remaining_paper_positions'],
            'watch_session_state': str(session_path),
            'mode': 'PAPER ONLY, NOT EXCHANGE EXECUTION',
            'liquidation': report}
