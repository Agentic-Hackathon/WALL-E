"""One-command autonomous RESEARCH pipeline. It never submits exchange orders.
Stage 2 broker status is read-only; source concepts in third_party/SOURCES.md.
"""
from __future__ import annotations
import argparse,json,sys,datetime,traceback,os
from pathlib import Path
from .atlas_archive import Lake,ALL_RESOLUTIONS
from .atlas_mode import cli_mode,mode_status,ExecutionMode


def pretty(value):print(json.dumps(value,ensure_ascii=False,indent=2,default=str))

def main(argv=None):
    p=argparse.ArgumentParser(prog='python -m wallex_bot.atlas_cli',
        description='Wallex Atlas: real-data-only all-market research + ML/DL + news + read-only MCP')
    p.add_argument('command',nargs='?',default='run',choices=['run','discover','archive-all',
        'benchmark','news','finbert','train-deep','shadow-cycle','status','mcp-smoke','inspect','account-audit','account-read-status','agent-cycle','capture-live','watch','audit-v3','forward-report','contest-readiness','context-status','context-preview','context-review','broker-status','liquidation-status','liquidate-paper','validate','mode-status','memory-rank','rationale-status','replay-decision','operations-report','edge-triage','feature-health','feature-recipe-audit','feature-audit-v3','challenger-preflight','train-challenger-v2','challenger-evaluate','data-quality-audit','data-sync-status','data-sync-plan','data-sync-run'])
    p.add_argument('--event-id',type=int,default=None,help='Recorded paper ledger event ID for read-only replay')
    p.add_argument('--checkpoint-dir',default=None,help='Exact Stage13 saved research run directory, never auto-select checkpoints')
    p.add_argument('--days',type=int,default=7)
    p.add_argument('--minutes',type=int,default=10)
    p.add_argument('--hours',type=int,default=48)
    p.add_argument('--scope',choices=['all-spot','tmn-spot','all-listed'],default='all-spot')
    p.add_argument('--resolutions',default='15,60')
    p.add_argument('--model',choices=['itransformer','patchtst','both'],default='both')
    p.add_argument('--epochs',type=int,default=16)
    p.add_argument('--symbol',default=None)
    p.add_argument('--resolution',default='15')
    p.add_argument('--limit-markets',type=int,default=None)
    p.add_argument('--delay',type=float,default=.35)
    p.add_argument('--workers',type=int,default=1,help='Controlled public-data GET workers (1..8); no worker writes the archive')
    p.add_argument('--retries',type=int,default=2,help='Bounded public-data retry count per window (0..6)')
    p.add_argument('--backoff-seconds',type=float,default=.5,help='Exponential retry backoff base for public-data GETs')
    p.add_argument('--output-dir',default='reports',help='Output directory for read-only data-quality audit reports')
    p.add_argument('--probe-symbol',default=None,help='Optional public UDF contract probe; records observed response grids without orders')
    p.add_argument('--sync-scope',choices=('priority','tmn','spot','catalog'),default='priority')
    p.add_argument('--sync-hours',type=float,default=None,help='Recent warmup window for data sync, bounded to 1..72 hours')
    p.add_argument('--max-windows',type=int,default=8,help='Maximum public source windows per bounded data-sync run')
    p.add_argument('--sync-resolutions',default=None,help='Comma-separated demanded target resolutions; default comes from active model metadata')
    p.add_argument('--package-id',type=int,default=None,help='Optional read-only package lookup; never enables order submission')
    p.add_argument('--fee',type=float,default=.001)
    p.add_argument('--slippage',type=float,default=.0005)
    p.add_argument('--top',type=int,default=8)
    p.add_argument('--as-of-utc',default=None,help='PIT memory cutoff, ISO-8601 UTC; never future')
    p.add_argument('--mode',choices=('BACKTEST','SHADOW','LIVE'),default=None,
                   help='Explicit contract for validate/benchmark (BACKTEST) or paper agent/watch (SHADOW); LIVE disabled')
    args=p.parse_args(argv)
    effective_mode=cli_mode(args.command,args.mode)
    if args.command=='challenger-evaluate':
        from .atlas_challenger_eval import evaluate
        from .atlas_archive import root_path
        pretty(evaluate(root_path(),run_dir=args.checkpoint_dir));return
    if args.command in ('challenger-preflight','train-challenger-v2'):
        from .atlas_challenger_v2 import prepare, train
        from .atlas_archive import root_path
        if args.command=='challenger-preflight':
            pretty(prepare(root_path(),top=args.top,validation_hours=args.hours).public_report)
        else:
            if args.model=='both':
                p.error('Stage13 requires explicit --model patchtst or --model itransformer (no implicit selection)')
            pretty(train(root_path(),architecture=args.model,
                         top=args.top,validation_hours=args.hours,epochs=args.epochs))
        return
    if args.command=='feature-recipe-audit':
        from .atlas_feature_recipe import feature_recipe_report
        from .atlas_archive import root_path
        pretty(feature_recipe_report(root_path(),resolution=args.resolution,top=args.top,symbol=args.symbol));return
    if args.command=='feature-health':
        from .atlas_feature_health import feature_health_report
        from .atlas_archive import root_path
        pretty(feature_health_report(root_path(),resolution=args.resolution,top=args.top,symbol=args.symbol));return
    if args.command=='feature-audit-v3':
        from .atlas_feature_audit_v3 import build_reports
        from .atlas_archive import root_path
        pretty(build_reports(root_path(),args.output_dir,top=args.top));return
    if args.command=='edge-triage':
        from .atlas_edge_triage import edge_triage_report
        from .atlas_archive import root_path
        pretty(edge_triage_report(root_path()));return
    if args.command=='operations-report':
        from .atlas_operational import operational_report
        from .atlas_archive import root_path
        pretty(operational_report(root_path()));return
    if args.command=='replay-decision':
        from .atlas_replay import replay_decision
        from .atlas_archive import root_path
        pretty(replay_decision(root_path(),event_id=args.event_id));return
    if args.command=='rationale-status':
        from .atlas_rationale import rationale_status
        from .atlas_archive import root_path
        pretty(rationale_status(root_path()));return
    if args.command=='mode-status':
        pretty(mode_status());return
    lake=Lake()
    try:
        if args.command=='memory-rank':
            from .atlas_context import ContextStore
            # Truly read-only, including when no context database has been created.
            store=ContextStore(lake.root,mode=ExecutionMode.SHADOW,read_only=True)
            try:
                pretty({'mode':'SHADOW_READ_ONLY_MEMORY_VIEW','memory_policy':'EVIDENCE_ONLY_NO_ORDER_AUTHORITY',
                        'items':store.ranked(as_of_utc=args.as_of_utc,symbol=args.symbol,
                                             purpose='watch',limit=min(max(args.top,1),40)),
                        'integrity':store.verify()})
            finally:store.close()
            return
        if args.command in ('context-status','context-preview','context-review'):
            from .atlas_context import ContextStore,make_packet
            if args.command=='context-preview':
                pretty(make_packet(lake,phase='watch'));return
            store=ContextStore(lake.root)
            try:
                pretty(store.status() if args.command=='context-status'
                       else {'candidates':store.review_candidates(),
                             'note':'CANDIDATE lessons never alter risk gates, models, orders or policy'})
            finally:store.close()
            return
        if args.command in ('liquidation-status','liquidate-paper'):
            from .atlas_liquidation import liquidation_status, liquidate_paper_positions
            if args.command=='liquidation-status':
                pretty(liquidation_status(lake.root))
            else:
                pretty(liquidate_paper_positions(lake, fee=args.fee, require_watch_deadline=True,mode=ExecutionMode.SHADOW))
            return
        if args.command=='validate':
            from .atlas_validation import validate_archive,store_report
            result=validate_archive(lake,fee=args.fee,slippage=args.slippage,
                                    resolution=args.resolution,max_symbols=args.top,mode=ExecutionMode.BACKTEST)
            filename=store_report(lake,result,mode=ExecutionMode.BACKTEST)
            pretty({'report_path':str(filename),**result});return
        if args.command=='broker-status':
            from .atlas_broker import broker_status
            pretty(broker_status(lake.root));return
        if args.command=='data-quality-audit':
            from .atlas_data_quality import build_reports
            pretty(build_reports(lake,args.output_dir,probe_symbol=args.probe_symbol));return
        if args.command in ('data-sync-status','data-sync-plan','data-sync-run'):
            from .atlas_data_sync import DataSyncManager
            manager=DataSyncManager(lake)
            resolutions=tuple(x.strip() for x in args.sync_resolutions.split(',') if x.strip()) if args.sync_resolutions else None
            if args.command=='data-sync-status':pretty(manager.status());return
            if args.command=='data-sync-plan':
                pretty(manager.plan(top=args.top,scope=args.sync_scope,warmup_hours=args.sync_hours,target_resolutions=resolutions));return
            pretty(manager.run(top=args.top,scope=args.sync_scope,warmup_hours=args.sync_hours,target_resolutions=resolutions,
                               max_windows=args.max_windows,delay=args.delay,retries=args.retries,
                               backoff_seconds=args.backoff_seconds,workers=args.workers,purpose='cli-data-sync-run'));return
        if args.command=='account-read-status':
            from .wallex_api import account_connection_status
            pretty(account_connection_status(args.package_id));return
        if args.command=='status':pretty(lake.status());return
        if args.command=='forward-report':
            from .atlas_forward import report
            pretty(report(lake.root));return
        if args.command=='contest-readiness':
            from .atlas_readiness import readiness_report
            pretty(readiness_report(lake));return
        if args.command=='audit-v3':
            from .atlas_diagnostics import audit_v3
            pretty(audit_v3(lake));return
        if args.command=='watch':
            from .atlas_watch import run as watch
            pretty(watch(lake,hours=args.hours,top=args.top,mode=ExecutionMode.SHADOW));return
        if args.command=='capture-live':
            from .atlas_stream import capture
            if not lake.symbols('tmn-spot'):lake.discover()
            pretty(capture(lake,minutes=args.minutes,max_markets=min(args.top,24)));return
        if args.command=='agent-cycle':
            from .atlas_agent import cycle
            pretty(cycle(lake,symbol=args.symbol,mode=ExecutionMode.SHADOW));return
        if args.command=='mcp-smoke':
            from .mcp_smoke import run as mcp_check
            pretty(mcp_check());return
        if args.command=='discover':pretty(lake.discover());return
        if args.command=='account-audit':
            from .wallex_api import WallexReadClient
            from hashlib import sha256
            client=WallexReadClient()
            info={'mode':'PRIVATE_ACCOUNT_READ_ONLY','trade_authorization':'UNVERIFIED'}
            try:
                accounts=client.sub_accounts()
                info['subaccounts']=[{'title':r['title'],'type':r['type'],
                                      'isActive':r['isActive'],'isSuspend':r['isSuspend'],
                                      'client_id_sha256_prefix':sha256(str(r.get('clientId','')).encode()).hexdigest()[:14]}
                                     for r in accounts]
            except Exception as e:info['subaccounts_error']=type(e).__name__+': '+str(e)[:120]
            try:
                balances=client.balances_detail()
                info['nonzero_balances']={k:v for k,v in balances.items() if float(v.get('total') or 0)!=0}
            except Exception as e:info['balances_error']=type(e).__name__+': '+str(e)[:120]
            pretty(info);return
        if args.command=='inspect':
            symbols=[args.symbol] if args.symbol else lake.symbols('all-spot')
            pretty({'symbols':symbols[:100], 'total':len(symbols),'data_status':lake.status()})
            return
        if args.command in ('archive-all','run'):
            if args.command=='run' and os.environ.get('WALLEX_API_KEY'):
                from .wallex_api import WallexReadClient
                from hashlib import sha256
                try:
                    client=WallexReadClient()
                    active=[x for x in client.sub_accounts() if x.get('type')=='prop' and x.get('isActive') and not x.get('isSuspend')]
                    balances=client.balances_detail()
                    preflight={'timestamp_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
                       'active_credit_accounts':[{'title':x.get('title'),
                         'account_digest':sha256(str(x.get('clientId')).encode()).hexdigest()[:14]} for x in active],
                       'nonzero_assets':{k:v for k,v in balances.items() if float(v.get('total') or 0)>0},
                       'real_order_permission':'NOT_VERIFIED',
                       'package_market_authorization':'NOT_VERIFIED'}
                    (lake.root/'read_only_account_preflight.json').write_text(json.dumps(preflight,indent=2,ensure_ascii=False),encoding='utf-8')
                    pretty({'private_read_only_preflight':preflight})
                except Exception as e:
                    pretty({'private_read_only_preflight_failed':type(e).__name__,
                      'research_still_runs':'Public market data does not need secret API keys'})
            pretty({'discovery':lake.discover()})
            if args.resolutions=='all' or (args.command=='archive-all' and args.resolutions=='15,60'):
                resolutions=ALL_RESOLUTIONS
            else:resolutions=tuple(x.strip() for x in args.resolutions.split(',') if x.strip())
            # Archive canonical native observations once; derive all other intervals locally.
            network_intervals=tuple(r for r in resolutions if r not in ('5','15','30','180','240','360','480','720','2D','3D'))
            if ('15' in resolutions or '5' in resolutions or '30' in resolutions) and '1' not in network_intervals:
                network_intervals+=('1',)
            if any(r in resolutions for r in ('180','240','360','480','720')) and '60' not in network_intervals:
                network_intervals+=('60',)
            if any(r in resolutions for r in ('2D','3D')) and '1D' not in network_intervals:
                network_intervals+=('1D',)
            pretty({'harvest':lake.harvest(args.scope,args.days,network_intervals,max_markets=args.limit_markets,
                                            delay=args.delay,retries=args.retries,
                                            backoff_seconds=args.backoff_seconds,workers=args.workers)})
            from .atlas_archive import DERIVED
            derived=[r for r in resolutions if r in DERIVED]
            if derived:pretty({'derived_from_real_observations':lake.materialize_derived(derived)})
            if args.command=='archive-all':return
        if args.command in ('benchmark','run'):
            from .atlas_signals import run_benchmark
            try:
                all_,winners=run_benchmark(lake,args.resolution,args.fee,args.slippage)
                folder=lake.root/'research';folder.mkdir(exist_ok=True)
                all_.to_csv(folder/'all_strategy_results.csv',index=False)
                winners.to_csv(folder/'chronological_winners.csv',index=False)
                pretty({'test_market_strategies':len(all_),'preselected':len(winners),
                      'output':str(folder),'warning':'hypothetical fills, no multiple-testing correction; NOT actual orders'})
            except RuntimeError as e:pretty({'benchmark_skipped':str(e)})
            if args.command=='benchmark':return
        if args.command in ('news','run'):
            from .atlas_news import harvest_news
            pretty({'news':harvest_news(lake,hours=min(72,args.days*24))})
            if args.command=='news':return
        if args.command=='finbert':
            from .atlas_news import finbert_score
            pretty(finbert_score(lake));return
        promoted_this_run=False
        if args.command in ('train-deep','run'):
            from .atlas_deep import train_real, promote_champion
            produced=[]
            for model in (['itransformer','patchtst'] if args.model=='both' else [args.model]):
                try:
                    result=train_real(lake,architecture=model,res=args.resolution,epochs=args.epochs)
                    pretty({'deep_train':result})
                    produced.append(result['checkpoint'])
                except (RuntimeError,ImportError,ValueError) as e:
                    pretty({'model':model,'not_trained':str(e)})
            if produced:
                try:
                    pretty({'new_champion':promote_champion(lake,produced)})
                    promoted_this_run=True
                except (RuntimeError,ValueError,TypeError) as e:
                    pretty({'champion_not_promoted':str(e)})
            if args.command=='train-deep':return
        if args.command in ('shadow-cycle','run'):
            from .atlas_shadow import shadow_cycle
            if args.command=='run' and not promoted_this_run:
                pretty({'shadow_not_started':'No new model was promoted in this run; refusing silent fallback to older model'})
            else:
                try:pretty({'shadow':shadow_cycle(lake,top=args.top,fee=args.fee,mode=ExecutionMode.SHADOW)})
                except (RuntimeError,ImportError,ValueError) as e:pretty({'shadow_not_started':str(e)})
    finally:lake.close()

if __name__=='__main__':main()
