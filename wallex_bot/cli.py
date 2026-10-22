"""CLI read-only data, ML backtest, shadow observation, audit verification."""
from __future__ import annotations
import argparse, json, time, hashlib, tempfile, sqlite3, os
from datetime import datetime, timezone
from contextlib import closing
from pathlib import Path
import numpy as np
import pandas as pd
import joblib
from .market import candles,markets,depth,complete_only,ALLOWED_RESOLUTIONS,interval_report,require_resolution
from .strategy import Parameters,decision
from .simulator import backtest,export_result
from .features import make_features,COLUMNS
from .learning import predict
from .audit import AuditStore
from .wallex_api import WallexReadClient,market_authorization

def file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def verified_market(symbol, allowlist_path):
    allowlist = json.loads(Path(allowlist_path).read_text(encoding='utf-8'))['markets']
    if symbol not in allowlist:
        raise ValueError('Symbol is NOT explicitly allowed by organizer allowlist')
    found=[m for m in markets() if m.get('symbol')==symbol]
    if not found or not found[0].get('is_spot') or not found[0].get('is_tmn_based'):
        raise ValueError('Market is not confirmed as spot + TMN; fail closed')
    return found[0]

def cmd_fetch(args):
    # Public historical research; no claim that every Wallex spot market is organizer-approved.
    df=candles(args.symbol,args.resolution,args.start,args.end,resample_from=args.resample_from)
    out=Path(args.output);out.parent.mkdir(parents=True,exist_ok=True)
    df.to_csv(out,index=False)
    proof={'source':'wallex_public_api','symbol':args.symbol,'resolution':args.resolution,
           'requested_start':args.start,'requested_end':args.end,
           'resample_from':args.resample_from,'sha256':file_hash(out),
           'frequency':interval_report(df,args.resolution)}
    Path(str(out)+'.provenance.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'rows':len(df),'output':str(out),'provenance_file':str(out)+'.provenance.json',
                      'sha256':file_hash(out),'frequency':proof['frequency']},indent=2))

def load_verified_recent_csv(csv_path, symbol, resolution, *, max_age_hours=8, max_lookback_days=14):
    """Fail closed: actual Wallex data, complete, recent, source-linked, no interpolation."""
    path=Path(csv_path)
    proof_path=Path(str(path)+'.provenance.json')
    if not path.is_file() or not proof_path.is_file():
        raise RuntimeError('Verified Wallex CSV and provenance are both required. Fetch real data first.')
    proof=json.loads(proof_path.read_text(encoding='utf-8'))
    if not (proof.get('source')=='wallex_public_api' and
            proof.get('sha256')==file_hash(path) and
            proof.get('symbol')==symbol and proof.get('resolution')==resolution):
        raise RuntimeError('Wallex origin, symbol, resolution or SHA-256 check FAILED.')
    frame=pd.read_csv(path)
    require_resolution(frame,resolution)
    end_ts=int(frame.timestamp.iloc[-1])+ALLOWED_RESOLUTIONS[resolution]
    now=int(time.time())
    age=now-end_ts
    if age< -ALLOWED_RESOLUTIONS[resolution] or age>max_age_hours*3600:
        raise RuntimeError(f'Real market dataset stale/future-dated: end age {age/3600:.1f} hours')
    if end_ts-int(frame.timestamp.iloc[0])>max_lookback_days*86400:
        raise RuntimeError('Dataset exceeds short-term 14-day lookback limit.')
    return frame,proof


def cmd_backtest(args):
    df,_=load_verified_recent_csv(args.csv,args.symbol,args.resolution)
    p=Parameters(fee_rate=args.fee,slippage_rate=args.slippage,min_trade_tmn=args.min_notional,
                 horizon=args.horizon)
    target=Path(args.out);target.mkdir(parents=True,exist_ok=True)
    result,trades,curves,model=backtest(df,p,str(target/'decisions.sqlite'),initial_cash=args.cash,
                                        symbol=args.symbol)
    export_result(target,result,trades,curves)
    model_path=target/'ai_model.joblib';joblib.dump(model,model_path)
    manifest={'dataset_path':str(Path(args.csv).resolve()),'dataset_file_sha256':file_hash(args.csv),
              'model_sha256':file_hash(model_path), 'seed':31,'symbol':args.symbol,'resolution':args.resolution,
              'data_origin':'wallex_public_api',
              'strategy':'HGBoost_next_open_future_return_v1','results':result,
              'fee_rate_assumption':args.fee,'slippage_rate_assumption':args.slippage,
              'note':'Real Wallex candles, hypothetical backtest order executions; not executed at exchange.'}
    (target/'manifest.json').write_text(json.dumps(manifest,indent=2,ensure_ascii=False),encoding='utf-8')
    print(json.dumps(result,indent=2,ensure_ascii=False))


def cmd_short_eval(args):
    """Evaluate the very last 48 or 72 actual hours without leakage."""
    from .walkforward import evaluate
    df,proof=load_verified_recent_csv(args.csv,args.symbol,args.resolution)
    period=ALLOWED_RESOLUTIONS[args.resolution]
    if (args.hours*3600)%period:
        raise ValueError('Requested evaluation horizon does not divide timeframe')
    test_bars=args.hours*3600//period
    initial_train_bars=len(df)-test_bars
    if initial_train_bars<330:
        raise RuntimeError('Not enough REAL preceding candles for model training and held-out test. '
                           'Collect a few more recent days; never fabricate missing samples.')
    report=evaluate(df,args.out,args.symbol,args.resolution,
        fee=args.fee,slippage=args.slippage,initial_train_bars=initial_train_bars,
        test_bars=test_bars,initial_cash=args.cash,horizon=args.horizon,
        min_notional=args.min_notional)
    print(json.dumps({k:v for k,v in report.items() if k!='fold_results'},ensure_ascii=False,indent=2))


def cmd_train_shadow(args):
    """Train a current model on actual, complete Wallex candles for SHADOW-only decisions."""
    from .learning import train_cutoff
    df,_=load_verified_recent_csv(args.csv,args.symbol,args.resolution)
    if len(df)<330:
        raise RuntimeError('At least 330 real, closed candles required')
    model,_,_=train_cutoff(df,len(df),args.horizon)
    out=Path(args.out);out.mkdir(parents=True,exist_ok=True)
    model_path=out/'ai_model.joblib';joblib.dump(model,model_path)
    manifest={'symbol':args.symbol,'resolution':args.resolution,'data_origin':'wallex_public_api',
              'dataset_file_sha256':file_hash(args.csv),
              'model_sha256':file_hash(model_path),'training_bars':len(df),
              'last_training_timestamp':int(df.timestamp.iloc[-1]),'horizon_bars':args.horizon,
              'purpose':'READ_ONLY_SHADOW; NO REAL ORDERS'}
    (out/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(manifest,ensure_ascii=False,indent=2))

def cmd_shadow(args):
    authorization=market_authorization(args.symbol,args.allowlist,args.package_id)
    if not authorization['all_passed']:
        raise RuntimeError('Market does not pass all contest/spot/TMN/credit-package checks: '+str(authorization))
    metadata=verified_market(args.symbol,args.allowlist)
    p=Parameters(fee_rate=args.fee,slippage_rate=args.slippage,
                 min_trade_tmn=args.min_notional,horizon=args.horizon)
    # Only a model trained on authenticated Wallex candles may observe a real market.
    model_path=Path(args.model)
    manifest_path=model_path.parent/'manifest.json'
    if not manifest_path.exists():raise RuntimeError('Model manifest missing; cannot verify market provenance')
    model_info=json.loads(manifest_path.read_text(encoding='utf-8'))
    if model_info.get('symbol')!=args.symbol or model_info.get('resolution')!=args.resolution:
        raise RuntimeError('Model symbol or timeframe differs from live shadow market')
    if model_info.get('data_origin')!='wallex_public_api':
        raise RuntimeError('Model is not trained on verified Wallex observations')
    if model_info.get('model_sha256')!=file_hash(model_path):
        raise RuntimeError('Model checksum differs from manifest')
    model=joblib.load(args.model)  # NEVER load untrusted joblib files.
    now=int(time.time())
    df=candles(args.symbol,args.resolution,now-ALLOWED_RESOLUTIONS[args.resolution]*max(120,args.history),now,resample_from=args.resample_from)
    df=complete_only(df,args.resolution,now)
    if len(df)<38:raise RuntimeError('Insufficient closed candles to form features')
    latest=make_features(df)
    k=len(df)-1;timestamp=int(df.timestamp.iloc[k])
    log=AuditStore(args.audit)
    key=f'last_seen:{args.symbol}:{args.resolution}'
    if log.recall(key)==timestamp:
        print('No new CLOSED candle: skipped duplicate signal')
        log.close();return
    pred=predict(model,latest,k)
    ob=depth(args.symbol)
    ask=min(float(a['price']) for a in ob['ask'] if float(a['quantity'])>0)
    bid=max(float(b['price']) for b in ob['bid'] if float(b['quantity'])>0)
    spread=(ask-bid)/((ask+bid)/2)
    if not 0<bid<=ask:
        raise RuntimeError('Invalid bid/ask; no signal allowed')
    # SHADOW OBSERVATION ONLY: zero inventory assumed, no paper fills or private balances.
    action,reason,notional=decision(pred,args.cash,0.,ask,args.cash,args.cash,p)
    if spread>args.max_spread:
        action,reason,notional='HOLD','spread_too_wide',0.
    observation={'symbol':args.symbol,'is_spot':True,'is_tmn_based':True,'package_id':args.package_id,
                 'market_close_ts':timestamp,'observed_ts':now,
                 'predicted_log_return':None if not np.isfinite(pred) else pred,
                 'bid_tmn':bid,'ask_tmn':ask,'spread':spread,'model_sha256':file_hash(args.model),
                 'action':action,'reason':reason,'hypothetical_buy_notional_tmn':notional,
                 'mode':'SHADOW_ONLY_NO_ORDERS_NO_FILLS'}
    log.record('SHADOW_SIGNAL',observation,str(now));log.remember(key,timestamp);log.close()
    print(json.dumps(observation,indent=2,ensure_ascii=False))

def cmd_live_scout(args):
    """Real-only REST market/order-book samples, not a trading engine."""
    from .live_scout import capture_once
    if not (1 <= args.cycles <= 1000) or not (15 <= args.interval_seconds <= 3600):
        raise ValueError('Cycles 1..1000 and interval 15..3600 seconds required')
    symbols = [part.strip().upper() for part in args.symbols.split(',')]
    try:
        for i in range(args.cycles):
            report = capture_once(symbols,args.allowlist,args.package_id,args.audit,
                                  args.notional,args.fee,args.max_spread_bps)
            print(json.dumps({'cycle':i+1,**report},ensure_ascii=False,indent=2),flush=True)
            if i < args.cycles-1:
                time.sleep(args.interval_seconds)
    except KeyboardInterrupt:
        print(json.dumps({'stopped_by_user':True,'audit_path':args.audit,
                          'records_persisted':True,'trades_executed':False},ensure_ascii=False))


def cmd_live_scout_report(args):
    from .live_scout import report_scout
    print(json.dumps(report_scout(args.audit,forward_minutes=args.forward_minutes,
                                  tolerance_minutes=args.tolerance_minutes),ensure_ascii=False,indent=2))


def cmd_verify(args):
    store=AuditStore(args.audit)
    valid,n=store.verify()
    store.close()
    print(json.dumps({'hash_chain_valid':valid,'events':n},indent=2))
    if not valid:raise SystemExit(1)

def cmd_replay(args):
    """Byte-for-byte audit event-hash reproduction on the same immutable input."""
    source=Path(args.run)
    manifest=json.loads((source/'manifest.json').read_text(encoding='utf-8'))
    csv_path=Path(args.csv) if args.csv else Path(manifest.get('dataset_path', manifest.get('evaluation_dataset_path','')))
    if manifest.get('evaluation_mode') == 'separated_real_segments':
        csv_path=Path(args.csv) if args.csv else source/manifest['evaluation_dataset_path']
        if file_hash(csv_path) != manifest['dataset_file_sha256']:
            raise RuntimeError('Segment evaluation dataset checksum mismatch')
        if file_hash(source/manifest['training_segment_path']) != manifest['training_segment_sha256']:
            raise RuntimeError('Training segment checksum mismatch')
        model_path=source/'ai_model.joblib'
        if file_hash(model_path) != manifest['model_sha256']:
            raise RuntimeError('Fixed model checksum mismatch')
        origin=AuditStore(source/'decisions.sqlite')
        ok,_=origin.verify()
        origin.close()
        if not ok: raise RuntimeError('Original segment evaluation audit corrupted')
        with closing(sqlite3.connect(source/'decisions.sqlite')) as db:
            begin=db.execute("SELECT payload FROM events WHERE kind='RUN_START' ORDER BY id LIMIT 1").fetchone()
            original_hashes=[r[0] for r in db.execute('SELECT event_hash FROM events ORDER BY id')]
        if not begin: raise RuntimeError('RUN_START missing')
        header=json.loads(begin[0])
        p=Parameters(**header['params'])
        model=joblib.load(model_path) # load only trusted local model whose SHA matches the manifest
        with tempfile.TemporaryDirectory(prefix='wallex_segment_replay_') as td:
            result,_,_,_=backtest(pd.read_csv(csv_path),p,Path(td)/'decisions.sqlite',
                                 initial_cash=header['initial_cash'],symbol=header['symbol'],
                                 model=model,start_index=header['start'],end_index=header['end'])
            with closing(sqlite3.connect(Path(td)/'decisions.sqlite')) as db:
                replay_hashes=[r[0] for r in db.execute('SELECT event_hash FROM events ORDER BY id')]
        identical=original_hashes==replay_hashes and result==manifest['results']
        print(json.dumps({'exact_decision_event_replay':identical,'original_events':len(original_hashes),
                          'replayed_events':len(replay_hashes),'matched_financial_metrics':result==manifest['results']},indent=2))
        if not identical:raise SystemExit(1)
        return
    if file_hash(csv_path)!=manifest['dataset_file_sha256']:
        raise RuntimeError('Dataset differs from archived training/evaluation input')
    origin=AuditStore(source/'decisions.sqlite')
    if not origin.verify()[0]:
        raise RuntimeError('Original audit DB hash chain INVALID')
    # Recorded config is more authoritative than subsequently edited docs.
    with closing(sqlite3.connect(source/'decisions.sqlite')) as db:
        begin=db.execute("SELECT payload FROM events WHERE kind='RUN_START' ORDER BY id LIMIT 1").fetchone()
        original_hashes=[r[0] for r in db.execute('SELECT event_hash FROM events ORDER BY id')]
    origin.close()
    if not begin:raise RuntimeError('Missing RUN_START metadata')
    header=json.loads(begin[0]); p=Parameters(**header['params'])
    with tempfile.TemporaryDirectory(prefix='wallex_replay_') as td:
        result,_,_,_=backtest(pd.read_csv(csv_path),p,Path(td)/'decisions.sqlite',
                                 initial_cash=header['initial_cash'],symbol=header['symbol'],
                                 start_index=header['start'],end_index=header['end'])
        with closing(sqlite3.connect(Path(td)/'decisions.sqlite')) as db:
            compare=[r[0] for r in db.execute('SELECT event_hash FROM events ORDER BY id')]
    same=original_hashes==compare and result==manifest['results']
    print(json.dumps({'exact_decision_event_replay':same,'original_events':len(original_hashes),
                      'replayed_events':len(compare),'matched_financial_metrics':result==manifest['results']},indent=2))
    if not same:raise SystemExit(1)

def cmd_inspect(args):
    df=pd.read_csv(args.csv)
    report=interval_report(df,args.resolution)
    print(json.dumps(report,indent=2))
    if report['has_finer_than_requested']:raise SystemExit(2)

def cmd_account_read(args):
    api=WallexReadClient()
    if args.what=='balances':result=api.balances_detail()
    elif args.what=='subaccounts':result=api.sub_accounts()
    elif args.what=='package':
        if args.package_id is None:raise ValueError('Provide --package-id for package read')
        result=api.package_details(args.package_id)
    print(json.dumps(result,indent=2,ensure_ascii=False))

def cmd_market_check(args):
    result=market_authorization(args.symbol,args.allowlist,args.package_id)
    print(json.dumps(result,indent=2,ensure_ascii=False))
    if not result['all_passed']:raise SystemExit(2)

def cmd_remote_mcp(args):
    from .mcp_client import remote_mcp_tools
    url=args.url or os.environ.get('WALLEX_MCP_URL','')
    if not url:raise ValueError('Organizer MCP endpoint URL not provided; do not guess')
    print(json.dumps(remote_mcp_tools(url),indent=2,ensure_ascii=False))

def cmd_walkforward(args):
    from .walkforward import evaluate
    if not args.csv:
        raise ValueError('Provide a real OHLCV --csv downloaded from Wallex')
    frame,_=load_verified_recent_csv(args.csv,args.symbol,args.resolution)
    report=evaluate(frame,args.out,args.symbol,args.resolution,
        fee=args.fee,slippage=args.slippage,initial_train_bars=args.initial_train_bars,
        test_bars=args.test_bars,initial_cash=args.cash,horizon=args.horizon,
        min_notional=args.min_notional)
    print(json.dumps({k:v for k,v in report.items() if k!='fold_results'},ensure_ascii=False,indent=2))

def cmd_account_summary(args):
    """Small, safe inventory read; hide client IDs in public logs."""
    from decimal import Decimal
    api=WallexReadClient()
    full=api.balances_detail()
    nonzero={}
    for asset,item in full.items():
        try:
            amount=Decimal(str(item.get('total','0')))
            frozen=Decimal(str(item.get('freeze','0')))
        except Exception:
            raise RuntimeError('Unexpected account balance format; refusing misleading summary')
        if amount or frozen:
            nonzero[asset]={'total':str(amount),'available':item.get('available'),
                            'freeze':str(frozen)}
    print(json.dumps({'assets_reported':len(full),'nonzero_assets':nonzero,
         'note':'Balances belong to the account selected by your API key; confirm it is the contest prop account.'},
         ensure_ascii=False,indent=2))

def cmd_fetch_history(args):
    from .research_data import fetch_research_history,write_research_history,write_segmented_history
    if not 5 <= args.days <= 14:
        raise ValueError('Short-horizon competition mode: --days must be 5..14 (recent data only)')
    seconds=ALLOWED_RESOLUTIONS[args.resolution]
    cache_path=Path(str(args.output)+'.parts')
    state_file=cache_path/'state.json'
    # Resume a pinned absolute time window rather than advancing the 30-day
    # window every time the command is rerun 15 minutes later.
    if state_file.exists() and args.start is None and args.end is None:
        pinned=json.loads(state_file.read_text(encoding='utf-8'))
        if (pinned.get('symbol')!=args.symbol or pinned.get('resolution')!=args.resolution or
            pinned.get('resample_from')!=args.resample_from or
            pinned.get('chunk_hours')!=args.chunk_hours):
            raise RuntimeError('Existing cache uses different settings; choose a different --output')
        begin,end=int(pinned['begin']),int(pinned['end'])
        if end-begin!=args.days*86400:
            raise RuntimeError('Existing pinned cache --days differs; choose a different --output')
    else:
        end=int(args.end) if args.end is not None else int(time.time())
        end=(end//seconds)*seconds
        begin=int(args.start) if args.start is not None else end-args.days*86400
    if args.start is not None and begin%seconds:
        raise ValueError('Explicit --start must be a UTC timeframe boundary')
    df,chunks=fetch_research_history(args.symbol,args.resolution,begin,end,
                     resample_from=args.resample_from,chunk_hours=args.chunk_hours,
                     cache_dir=cache_path,allow_gaps=args.allow_gaps)
    if args.allow_gaps:
        out=write_segmented_history(df,chunks,args.output,args.symbol,args.resolution,
                                    begin,end,args.resample_from)
    else:
        out=write_research_history(df,chunks,args.output,args.symbol,args.resolution,
                                   begin,end,args.resample_from)
    print(json.dumps(out,ensure_ascii=False,indent=2))


def cmd_training_audit(args):
    """Compare simple challengers using exclusively earlier archived real candles."""
    from .challenger_audit import write_training_audit
    report, path = write_training_audit(args.run, args.out, args.fold_bars,
                                        args.folds, args.horizon)
    print(json.dumps({'output':str(path), 'mode':report['mode'],
        'train_segment_bars':report['train_segment_bars'],
        'horizon_bars':report['horizon_bars'],
        'fold_results':report['fold_results'],
        'limitations':report['limitations']}, ensure_ascii=False, indent=2))


def cmd_diagnose_run(args):
    """Read a verified actual replay; never connect to exchange or change orders."""
    from .diagnostics import write_report
    report, output=write_report(args.run,args.out)
    print(json.dumps({'output':str(output),
        'diagnosis':report['diagnosis'],
        'decision_count':report['decision_count'],
        'reason_counts':report['reason_counts'],
        'entry_threshold_log_return':report['assumptions']['entry_threshold_log_return'],
        'entry_threshold_crossings':report['entry_threshold_crossings'],
        'forecast_log_return_quantiles':report['forecast_log_return_quantiles'],
        'forecast_skill_on_observed_real_future':report['forecast_skill_on_observed_real_future'],
        'note':'EVIDENCE-ONLY report; no trades or synthetic observations.'},
        ensure_ascii=False,indent=2,allow_nan=False))

def cmd_segment_eval(args):
    from .segmented_eval import evaluate_segments
    result=evaluate_segments(args.catalog,args.symbol,args.resolution,args.hours,
                             args.out,args.fee,args.slippage,args.cash,args.horizon,args.min_notional)
    print(json.dumps(result,ensure_ascii=False,indent=2))


def cmd_history_status(args):
    """Offline resumable-download progress; never reads credentials."""
    cache=Path(str(args.output)+'.parts')
    state=cache/'state.json'
    if not state.exists():
        raise RuntimeError('No resume state for this output. Run fetch-history first.')
    p=json.loads(state.read_text(encoding='utf-8'))
    step=int(p['chunk_hours'])*3600
    ranges=[(s,min(int(p['end']),s+step)) for s in range(int(p['begin']),int(p['end']),step)]
    completed=sum((cache/f'chunk_{s}_{e}.csv').exists() and
                  (cache/f'chunk_{s}_{e}.csv.json').exists() for s,e in ranges)
    last_failure=cache/'last_failure.json'
    failure=json.loads(last_failure.read_text(encoding='utf-8')) if last_failure.exists() else None
    print(json.dumps({'symbol':p['symbol'],'resolution':p['resolution'],
         'window_start_utc':datetime.fromtimestamp(p['begin'],timezone.utc).isoformat(),
         'window_end_utc':datetime.fromtimestamp(p['end'],timezone.utc).isoformat(),
         'completed_chunks':completed,'total_chunks':len(ranges),
         'final_dataset_ready':Path(args.output).exists() and Path(str(args.output)+'.provenance.json').exists(),
         'segment_catalog_ready':Path(str(args.output)+'.segments.json').is_file(),
         'last_failure':failure,'note':'Status only; no network requests or trades.'},
         ensure_ascii=False,indent=2))

def cmd_mcp_smoke(args):
    from .mcp_smoke import run
    print(json.dumps(run(),ensure_ascii=False,indent=2))


def main(argv=None):
    parser=argparse.ArgumentParser(description='Wallex AI safe starter: read-only / backtest / shadow only')
    subs=parser.add_subparsers(dest='cmd',required=True)
    fetch=subs.add_parser('fetch');fetch.add_argument('--symbol',required=True)
    fetch.add_argument('--resolution',default='15',choices=ALLOWED_RESOLUTIONS)
    fetch.add_argument('--start',required=True,type=int);fetch.add_argument('--end',required=True,type=int)
    fetch.add_argument('--output',required=True)
    fetch.add_argument('--resample-from',choices=ALLOWED_RESOLUTIONS,default=None,
                       help='Explicit resampling ONLY if API actually returned source timeframe')
    fetch.set_defaults(func=cmd_fetch)
    bt=subs.add_parser('backtest');bt.add_argument('--csv',required=True);bt.add_argument('--out',required=True)
    bt.add_argument('--symbol',required=True);bt.add_argument('--resolution',choices=ALLOWED_RESOLUTIONS,required=True);bt.add_argument('--cash',type=float,default=5000000)
    bt.add_argument('--fee',type=float,required=True,help='per side actual fee RATE, not percent')
    bt.add_argument('--slippage',type=float,default=.0005);bt.add_argument('--min-notional',type=float,default=0)
    bt.add_argument('--horizon',type=int,default=3);bt.set_defaults(func=cmd_backtest)
    sh=subs.add_parser('shadow-once');sh.add_argument('--symbol',required=True)
    sh.add_argument('--resolution',default='15',choices=ALLOWED_RESOLUTIONS)
    sh.add_argument('--allowlist',required=True);sh.add_argument('--package-id',type=int,required=True)
    sh.add_argument('--model',required=True)
    sh.add_argument('--audit',default='shadow.sqlite');sh.add_argument('--history',type=int,default=150)
    sh.add_argument('--cash',type=float,default=5_000_000)
    sh.add_argument('--fee',type=float,required=True);sh.add_argument('--slippage',type=float,default=.0005)
    sh.add_argument('--min-notional',type=float,default=0);sh.add_argument('--horizon',type=int,default=3)
    sh.add_argument('--max-spread',type=float,default=.004)
    sh.add_argument('--resample-from',choices=ALLOWED_RESOLUTIONS,default=None)
    sh.set_defaults(func=cmd_shadow)
    verify=subs.add_parser('verify');verify.add_argument('--audit',required=True);verify.set_defaults(func=cmd_verify)
    replay=subs.add_parser('replay');replay.add_argument('--run',required=True)
    replay.add_argument('--csv',help='Override archived input path when moved to another machine')
    replay.set_defaults(func=cmd_replay)
    inspect=subs.add_parser('inspect-csv');inspect.add_argument('--csv',required=True)
    inspect.add_argument('--resolution',required=True,choices=ALLOWED_RESOLUTIONS)
    inspect.set_defaults(func=cmd_inspect)
    account=subs.add_parser('account-read');account.add_argument('--what',required=True,
                   choices=['balances','subaccounts','package'])
    account.add_argument('--package-id',type=int)
    account.set_defaults(func=cmd_account_read)
    check=subs.add_parser('market-check');check.add_argument('--symbol',required=True)
    check.add_argument('--allowlist',required=True)
    check.add_argument('--package-id',required=True,type=int)
    check.set_defaults(func=cmd_market_check)
    mp=subs.add_parser('mcp-remote-check');mp.add_argument('--url',default=None)
    mp.set_defaults(func=cmd_remote_mcp)
    acsum=subs.add_parser('account-summary',help='show nonzero balances only, without client IDs')
    acsum.set_defaults(func=cmd_account_summary)
    hist=subs.add_parser('fetch-history',help='download contiguous real Wallex history in UTC chunks')
    hist.add_argument('--symbol',required=True)
    hist.add_argument('--resolution',choices=ALLOWED_RESOLUTIONS,default='15')
    hist.add_argument('--days',type=int,default=7)
    hist.add_argument('--start',type=int)
    hist.add_argument('--end',type=int)
    hist.add_argument('--chunk-hours',type=int,default=3)
    hist.add_argument('--resample-from',choices=ALLOWED_RESOLUTIONS,default='1')
    hist.add_argument('--output',required=True)
    hist.add_argument('--allow-gaps',action='store_true',
                      help='Continue after unavailable real candles, output separate verified continuous segments; no filling')
    hist.set_defaults(func=cmd_fetch_history)
    dg=subs.add_parser('diagnose-run',help='explain audited genuine segment-eval decisions, 0-trade causes, and held-out forecast skill; offline')
    dg.add_argument('--run',required=True)
    dg.add_argument('--out')
    dg.set_defaults(func=cmd_diagnose_run)
    scout=subs.add_parser('live-scout',help='Collect REAL Wallex spot/TMN books from organizer-approved markets; public read-only research; NO trades')
    scout.add_argument('--symbols',required=True,help='Comma-separated list, e.g. BTCTMN,ETHTMN; all must be organizer-approved')
    scout.add_argument('--allowlist',required=True)
    scout.add_argument('--package-id',required=True,type=int)
    scout.add_argument('--audit',default='runs/live_scout.sqlite')
    scout.add_argument('--notional',type=float,default=250000.0,help='TMN hypothetical display-book sweep budget; NOT an order')
    scout.add_argument('--fee',required=True,type=float,help='Per-side fee rate assumption, not percent')
    scout.add_argument('--max-spread-bps',type=float,default=100.0)
    scout.add_argument('--cycles',type=int,default=1)
    scout.add_argument('--interval-seconds',type=int,default=300)
    scout.set_defaults(func=cmd_live_scout)
    scoutrep=subs.add_parser('live-scout-report',help='Verify and summarize only genuinely observed saved exchange order books')
    scoutrep.add_argument('--audit',required=True)
    scoutrep.add_argument('--forward-minutes',type=int,default=45)
    scoutrep.add_argument('--tolerance-minutes',type=int,default=6)
    scoutrep.set_defaults(func=cmd_live_scout_report)
    ta=subs.add_parser('training-audit',help='compare models ONLY on genuine archived earlier training candles; no orders, no new test evaluation')
    ta.add_argument('--run',required=True)
    ta.add_argument('--out')
    ta.add_argument('--fold-bars',type=int,default=72)
    ta.add_argument('--folds',type=int,default=2)
    ta.add_argument('--horizon',type=int,default=3)
    ta.set_defaults(func=cmd_training_audit)
    segr=subs.add_parser('segment-eval',help='train on earlier genuine segment, OOS test only within latest genuine segment')
    segr.add_argument('--catalog',required=True)
    segr.add_argument('--symbol',required=True)
    segr.add_argument('--resolution',required=True,choices=ALLOWED_RESOLUTIONS)
    segr.add_argument('--hours',type=int,choices=[12,24,36,48,72],default=24)
    segr.add_argument('--fee',type=float,required=True)
    segr.add_argument('--slippage',type=float,default=0.0005)
    segr.add_argument('--out',required=True)
    segr.add_argument('--cash',type=float,default=5000000)
    segr.add_argument('--horizon',type=int,default=3)
    segr.add_argument('--min-notional',type=float,default=0)
    segr.set_defaults(func=cmd_segment_eval)
    hs=subs.add_parser('history-status',help='inspect saved historical download checkpoint without network')
    hs.add_argument('--output',required=True)
    hs.set_defaults(func=cmd_history_status)
    wf=subs.add_parser('walkforward',help='expanding-window out-of-sample evaluation on verified real data')
    wf.add_argument('--csv',required=True);wf.add_argument('--symbol',required=True)
    wf.add_argument('--resolution',choices=ALLOWED_RESOLUTIONS,required=True)
    wf.add_argument('--out',required=True);wf.add_argument('--fee',type=float,required=True)
    wf.add_argument('--slippage',type=float,default=.0005)
    wf.add_argument('--initial-train-bars',type=int,default=330)
    wf.add_argument('--test-bars',type=int,default=96)
    wf.add_argument('--cash',type=float,default=5000000)
    wf.add_argument('--horizon',type=int,default=3)
    wf.add_argument('--min-notional',type=float,default=0)
    wf.set_defaults(func=cmd_walkforward)
    se=subs.add_parser('short-eval',help='hold out the latest 48/72 REAL hours; no synthesized market data')
    se.add_argument('--csv',required=True);se.add_argument('--symbol',required=True)
    se.add_argument('--resolution',required=True,choices=ALLOWED_RESOLUTIONS)
    se.add_argument('--hours',type=int,choices=[48,72],default=48)
    se.add_argument('--fee',type=float,required=True);se.add_argument('--slippage',type=float,default=.0005)
    se.add_argument('--out',required=True);se.add_argument('--cash',type=float,default=5000000)
    se.add_argument('--horizon',type=int,default=3);se.add_argument('--min-notional',type=float,default=0)
    se.set_defaults(func=cmd_short_eval)
    tr=subs.add_parser('train-shadow',help='train current SHADOW-only AI model on verified Wallex data')
    tr.add_argument('--csv',required=True);tr.add_argument('--symbol',required=True)
    tr.add_argument('--resolution',required=True,choices=ALLOWED_RESOLUTIONS)
    tr.add_argument('--horizon',type=int,default=3);tr.add_argument('--out',required=True)
    tr.set_defaults(func=cmd_train_shadow)
    smoke=subs.add_parser('mcp-smoke',help='stdio MCP client handshake and tools/list')
    smoke.set_defaults(func=cmd_mcp_smoke)
    args=parser.parse_args(argv);args.func(args)

if __name__=='__main__':main()
