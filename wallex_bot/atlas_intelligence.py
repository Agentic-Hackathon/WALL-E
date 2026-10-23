"""M8 opt-in frozen foreground research profile, not model promotion.

Reuses the M7 scheduler, independent sampler, model ledger and source pinning;
adds bounded intelligence sync and the M8 agentic dynamic-Shadow adapter.
No LIVE command or credential access exists in this entry point.
"""
import argparse,json,signal,threading
from pathlib import Path
from .atlas_study import settings,prepare,run,validate,DeadlineLedger
from .atlas_patterns import DEFAULT_INDEX
from .atlas_intelligence_sync import IntelligenceSyncManager
from .atlas_agentic_cycle import research_cycle,AgenticLedger

DEFAULT_SESSION='atlas_store/research_challengers/milestone8/formal_48h_v1'

def profile(symbols=('BTCTMN','ETHTMN'),hours=48,*,news=True,index_dir=DEFAULT_INDEX):
    config=settings(symbols,hours,shadow=False)
    config.update(research_profile='ATLAS_M8_AGENTIC_V1',executing_policy='M8_OPT_IN_DYNAMIC_SHADOW_EXISTING_CHAMPION_ONLY',
        intelligence={'news_enabled':bool(news),'finbert_competition_decision_use':False,
            'pattern_index_dir':str(Path(index_dir).resolve()),'pattern_decision_use':False,
            'terminal_exit_window_seconds':3600,'review_schedule':'new real sampler receipt + 2s settling; fresh quote <=30s',
            'ablation_selection_or_automatic_promotion':False,'turnover_budget':'per 15m wall-clock bucket, shared across all quote-driven reviews',
            'last_forecast_origin':'due + 300s must be <= study deadline; no fabricated tail labels'})
    return config

def startup_hook(lake,directory,contract):
    cfg=contract['settings']['intelligence']
    return IntelligenceSyncManager(lake).sync_intelligence(directory,index_dir=cfg['pattern_index_dir'],news_enabled=cfg['news_enabled'])

def main():
    p=argparse.ArgumentParser();p.add_argument('command',choices=['prepare','run','status','replay','sync-status'])
    p.add_argument('--root',default='atlas_store');p.add_argument('--session-dir',default=DEFAULT_SESSION);p.add_argument('--symbols',default='BTCTMN,ETHTMN');p.add_argument('--hours',type=int,default=48)
    p.add_argument('--no-news',action='store_true');p.add_argument('--index-dir',default=DEFAULT_INDEX);p.add_argument('--max-runtime-seconds',type=float)
    args=p.parse_args();directory=Path(args.session_dir).resolve();stop=threading.Event()
    for sig in (signal.SIGINT,signal.SIGTERM):signal.signal(sig,lambda *_:stop.set())
    if args.command=='prepare':
        result=prepare(args.root,directory,profile(tuple(args.symbols.split(',')),args.hours,news=not args.no_news,index_dir=args.index_dir))
        result={'session_id':result['session_id'],'contract_sha256':result['contract_sha256'],'source_commit':result['source_commit'],'status':result['status']}
    else:
        contract=json.loads((directory/'study_contract.json').read_text());validate(Path(args.root).resolve(),contract)
        if contract['settings'].get('research_profile')!='ATLAS_M8_AGENTIC_V1':raise ValueError('M8_PROFILE_REQUIRED_NO_SILENT_SESSION_CONVERSION')
        if args.command=='run':result=run(args.root,directory,max_runtime_seconds=args.max_runtime_seconds,stop=stop,startup_hook=startup_hook,research_hook=research_cycle)
        elif args.command=='replay':
            ledger=AgenticLedger(directory)
            try:result=ledger.replay()
            finally:ledger.close()
        elif args.command=='sync-status':
            from .atlas_archive import Lake
            lake=Lake(args.root)
            try:result=IntelligenceSyncManager(lake).intelligence_status(directory,index_dir=contract['settings']['intelligence']['pattern_index_dir'])
            finally:lake.close()
        else:
            ledger=DeadlineLedger(directory)
            try:result={'forward':ledger.status(),'deadlines':ledger.deadline_report(),'profile':contract['settings']['research_profile']}
            finally:ledger.close()
    print(json.dumps(result,ensure_ascii=False,default=str))

if __name__=='__main__':main()
