"""One-command autonomous RESEARCH pipeline. It never submits exchange orders."""
from __future__ import annotations
import argparse,json,sys,datetime,traceback,os
from pathlib import Path
from .atlas_archive import Lake,ALL_RESOLUTIONS


def pretty(value):print(json.dumps(value,ensure_ascii=False,indent=2,default=str))

def main(argv=None):
    p=argparse.ArgumentParser(prog='python -m wallex_bot.atlas_cli',
        description='Wallex Atlas: real-data-only all-market research + ML/DL + news + read-only MCP')
    p.add_argument('command',nargs='?',default='run',choices=['run','discover','archive-all',
        'benchmark','news','finbert','train-deep','shadow-cycle','status','mcp-smoke','inspect','account-audit','agent-cycle','capture-live','watch','audit-v3','forward-report','contest-readiness','context-status','context-preview','context-review'])
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
    p.add_argument('--fee',type=float,default=.001)
    p.add_argument('--slippage',type=float,default=.0005)
    p.add_argument('--top',type=int,default=8)
    args=p.parse_args(argv)
    lake=Lake()
    try:
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
            pretty(watch(lake,hours=args.hours,top=args.top));return
        if args.command=='capture-live':
            from .atlas_stream import capture
            if not lake.symbols('tmn-spot'):lake.discover()
            pretty(capture(lake,minutes=args.minutes,max_markets=min(args.top,24)));return
        if args.command=='agent-cycle':
            from .atlas_agent import cycle
            pretty(cycle(lake,symbol=args.symbol));return
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
            pretty({'harvest':lake.harvest(args.scope,args.days,network_intervals,max_markets=args.limit_markets,delay=args.delay)})
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
                try:pretty({'shadow':shadow_cycle(lake,top=args.top,fee=args.fee)})
                except (RuntimeError,ImportError,ValueError) as e:pretty({'shadow_not_started':str(e)})
    finally:lake.close()

if __name__=='__main__':main()
