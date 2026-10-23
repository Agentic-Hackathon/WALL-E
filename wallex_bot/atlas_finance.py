"""Financial evidence workspace over EXISTING Atlas M8/Shadow/Risk contracts.

Original integration; reuse atlas_m8_evaluation, formal study, DataSync, news,
models, portfolio and depth-sweep ledger. No external trading code copied.
Recorded receipts are never recast as a long historical executable backtest.
Private account evidence stays under the ignored store; no credentials in UI.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import signal
import sqlite3
import threading
import time

from .atlas_deadline import DEADLINE, clock_probe, schedule
from .atlas_liquidation import _save_atomic

DEFAULT_SESSION='research_challengers/milestone8/financial_20261023_v1'
LEGACY_SESSION='research_challengers/milestone8/formal_48h_v1'


def read_json(path, default=None):
    try:return json.loads(Path(path).read_text(encoding='utf-8'))
    except FileNotFoundError:return default


def account_evidence(root):
    """Explicit imported snapshot; never falsely labelled current connectivity."""
    path=Path(root)/'operations/private_account_read.json';p=read_json(path,{})
    fees=p.get('verified_read_fee_rates',{})
    return {'status':'READ_RECEIPT_AVAILABLE_NOT_CURRENT_CONNECTIVITY' if p.get('connection')=='SUCCESS_READ_ONLY' else 'NO_SUCCESSFUL_READ_RECEIPT',
        'balance_tmn':p.get('tmn_available'),'total_tmn':p.get('tmn_total'),'frozen_tmn':p.get('tmn_frozen'),
        'receipt_observed_epoch':p.get('observed_epoch'),
        'legacy_receipt_file_mtime_not_authoritative':path.stat().st_mtime if path.exists() else None,
        'contest_identity':'UNVERIFIED','contest_credit':'UNVERIFIED_NOT_INFERRED_FROM_AMOUNT',
        'api_trade_permission':'UNVERIFIED_NO_PROBING_ORDER','organizer_allowlist':'UNVERIFIED',
        'subaccount_count':len(p.get('subaccounts',[])),'fees':fees,
        'source_sha256':hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None,
        'orders_sent':0,'realized_exchange_pnl':None}


def fee_contract(root,symbols):
    evidence=account_evidence(root)
    if evidence['status']!='READ_RECEIPT_AVAILABLE_NOT_CURRENT_CONNECTIVITY':raise ValueError('REAL_FEE_READ_RECEIPT_REQUIRED')
    rates=[]
    for symbol in symbols:
        value=evidence['fees'].get(symbol,{}).get('takerFeeRate')
        if type(value) not in (int,float) or not 0<=value<.05:raise ValueError('MISSING_VERIFIED_TAKER_FEE')
        rates.append(value)
    if len(set(rates))!=1:raise ValueError('PER_ASSET_FEE_ADAPTER_REQUIRED_NO_AVERAGE_FEE_SUBSTITUTION')
    return {'fee_per_side_assumed':rates[0], 'fee_verified':True,
        'fee_evidence':{'type':'ACCOUNT_TAKER_READ_RECEIPT_PINNED_FOR_SHADOW_ONLY',
            'source_sha256':evidence['source_sha256'],'imported_epoch':time.time(),
            'read_observed_epoch':evidence['receipt_observed_epoch'],'historical_fee_attribution':False}}


def current_session(root):
    root=Path(root).resolve();p=read_json(root/'operations/financial_current_session.json',{})
    relative=p.get('session',DEFAULT_SESSION);folder=(root/relative).resolve()
    if not folder.is_relative_to(root/'research_challengers/milestone8'):raise ValueError('UNSAFE_FINANCIAL_SESSION_PATH')
    return folder


def prepare_shadow(root,symbols=('BTCTMN','ETHTMN'),*,new_session=False):
    from .atlas_intelligence import profile
    from .atlas_study import prepare
    root=Path(root).resolve();folder=current_session(root)
    if new_session:
        folder=root/'research_challengers/milestone8'/('financial_'+str(time.time_ns()))
    if time.time()>=DEADLINE.timestamp():raise ValueError('COMPETITION_HALTED_NO_NEW_SESSION')
    config=profile(tuple(symbols),48,news=True)
    config.update(fee_contract(root,symbols))
    config.update(competition_deadline_epoch=DEADLINE.timestamp(),operator_stop_enabled=True)
    if (folder/'study_contract.json').is_file():
        existing=read_json(folder/'study_contract.json')
        if existing['settings']['symbols']!=list(symbols):raise ValueError('FROZEN_UNIVERSE_CONFLICT')
        # Keep original actual import time/hash; do not mutate a frozen contract.
        config=existing['settings']
    contract=prepare(root,folder,config)
    _save_atomic(root/'operations/financial_current_session.json',{'session':str(folder.relative_to(root)),
        'contract_sha256':contract['contract_sha256']})
    return {'session':str(folder),'contract_sha256':contract['contract_sha256'],'fee':config['fee_per_side_assumed'],
        'fee_source':config['fee_evidence'],'LIVE':'HARD_DISABLED'}


def curve_metrics(rows, initial=5_000_000):
    if not rows:return {'net_pnl_tmn':None,'max_drawdown':None,'equity_curve':[]}
    peak=initial;dd=0
    for row in rows:
        nav=float(row['nav_tmn'])
        if not 0<nav<float('inf'):raise ValueError('INVALID_OBSERVED_NAV')
        peak=max(peak,nav);dd=max(dd,1-nav/peak)
    return {'net_pnl_tmn':rows[-1]['nav_tmn']-initial,'max_drawdown':dd,'equity_curve':rows,
            'valuation':'HYPOTHETICAL_LAST_ACTUAL_RECEIPT_NOT_CURRENT_EXCHANGE_NAV'}


def recorded_summary(directory):
    from .atlas_m8_evaluation import actual_decisions
    rows=actual_decisions(Path(directory))
    curve=[];trades=[];decisions=[]
    for p in rows:
        receipt=p['receipt'];stamp=p['evidence']['decision_time']
        curve.append({'timestamp':stamp,'nav_tmn':receipt['after']['nav_tmn'],'cash_tmn':receipt['after']['cash_tmn']})
        decision={'timestamp':stamp,'symbol':p['evidence']['symbol'],'action':p['intent']['action'],
            'reason':receipt['reason'],'status':receipt['status'],'risk_gate':receipt.get('gate'),
            'intent_id':p['intent']['intent_id'],'fee':receipt.get('fee_per_side_assumed'),
            'hypothetical':True,'actual_exchange_fill':False}
        decisions.append(decision)
        if receipt.get('trade_estimate'):trades.append({**decision,'estimate':receipt['trade_estimate']})
    result={'initial_hypothetical_tmn':5_000_000,**curve_metrics(curve),'decisions':decisions,'trades':trades,
        'trade_count':len(trades),'decision_count':len(decisions),
        'reason_counts':dict(Counter(d['reason'] for d in decisions)),'realized_exchange_pnl':None,
        'orders_sent_to_exchange':0}
    if rows:
        result['positions_at_last_receipt']=rows[-1]['receipt']['after']['positions']
        result['risk_stopped_at_last_receipt']=rows[-1]['receipt']['after']['stopped']
    return result


def backtest(root):
    from .atlas_m8_evaluation import evaluate
    root=Path(root);folder=root/LEGACY_SESSION
    result=evaluate(folder)
    summary=recorded_summary(folder)
    summary.update(mode='BACKTEST',source_session=LEGACY_SESSION,
        scope='CHRONOLOGICAL_REPLAY_OF_CAPTURED_CURRENT_STRATEGY_DECISIONS_ONLY',
        full_historical_financial_backtest_valid=False,
        limitation='MISSING_LONG_HISTORICAL_PIT_BOOKS_NEWS_AND_REGISTERED_FORECASTS; NO_CLOSE_PRICE_FILLS',
        replay_checks=result['replay_checks'],cost_attribution='ORIGINAL_RECEIPT_FEE; CURRENT_ACCOUNT_FEE_NOT_BACKDATED',
        net_pnl_is_real_exchange_profit=False,financial_edge_proven=False)
    _save_atomic(root/'operations/financial_backtest.json',summary)
    return summary


def _clock_worker(folder,stop):
    requests=0;target=folder/'operations/clock_receipt.json'
    try:
        while not stop.is_set():
            clock=clock_probe();requests+=1;_save_atomic(target,clock)
            if stop.wait(15):break
    finally:
        prior=read_json(target,{})
        prior.update(verified=False,supervisor_stopped_epoch=time.time(),clock_requests=requests)
        _save_atomic(target,prior)


def run_shadow(root,*,seconds=120,resume=False,stop=None):
    from .atlas_intelligence import startup_hook
    from .atlas_agentic_cycle import research_cycle
    from .atlas_study import run
    root=Path(root).resolve();folder=current_session(root);stop=stop or threading.Event()
    if not 1<=seconds<=3600:raise ValueError('BOUNDED_SHADOW_RUNTIME_REQUIRED_1_TO_3600S')
    if time.time()>=DEADLINE.timestamp():raise ValueError('COMPETITION_HALTED')
    request=folder/'operator_stop.json'
    if request.exists():
        if not resume:raise ValueError('EXPLICIT_RESUME_REQUIRED_AFTER_STOP')
    if not (folder/'study_contract.json').is_file():raise ValueError('SHADOW_PREPARE_REQUIRED')
    # Acquire BEFORE clock/public I/O. The existing sampler lease is retained;
    # a second wrapper must not revoke the first wrapper's clock on exit.
    guard=sqlite3.connect(folder/'financial_runner_lock.sqlite',timeout=.1)
    try:guard.execute('BEGIN IMMEDIATE')
    except sqlite3.OperationalError:
        guard.close();return {'status':'FINANCIAL_RUNNER_HELD_NO_REQUESTS'}
    worker=threading.Thread(target=_clock_worker,args=(folder,stop),name='financial-shadow-clock',daemon=False)
    result={}
    try:
        if request.exists():request.rename(folder/('operator_stop_consumed_'+str(time.time_ns())+'.json'))
        worker.start()
        result=run(root,folder,max_runtime_seconds=seconds,stop=stop,startup_hook=startup_hook,research_hook=research_cycle)
        return result
    finally:
        try:
            stop.set()
            if worker.ident is not None:worker.join(timeout=15)
            summary=recorded_summary(folder)
            summary.update(mode='SHADOW',session=str(folder),observed_epoch=time.time(),
                process_result=result,stopped=True,requested_runtime_seconds=seconds,
                financial_edge_proven=False,fee_contract=read_json(folder/'study_contract.json',{}).get('settings',{}).get('fee_evidence'))
            _save_atomic(root/'operations/financial_shadow.json',summary)
        finally:guard.rollback();guard.close()


def stop_shadow(root):
    folder=current_session(root)
    if not (folder/'study_contract.json').is_file():raise ValueError('NO_PREPARED_SHADOW_SESSION')
    _save_atomic(folder/'operator_stop.json',{'requested_epoch':time.time(),'reason':'OPERATOR_STOP_NO_FINANCIAL_ACTION'})
    return {'status':'STOP_REQUESTED','automatic_live_orders':False}


def spot_execution_status(root):
    """Read-only, audit-verified actual order records; absence is not no orders."""
    from decimal import Decimal
    from .atlas_spot_exchange import SpotLedger
    orders=[];fees={};ledgers=0
    for path in Path(root).glob('operations/spot_accounts/*/operations/spot_exchange.sqlite'):
        db=sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True);db.row_factory=sqlite3.Row
        try:
            ledger=SpotLedger.__new__(SpotLedger);ledger.db=db;ledger._require_integrity();ledgers+=1
            for r in db.execute('SELECT client_id,symbol,side,state,observed,executed_qty,executed_sum,exchange_snapshot FROM spot_orders ORDER BY rowid'):
                item=dict(r);raw=item.pop('exchange_snapshot')
                if raw:
                    for fill in json.loads(raw)['result']['fills']:
                        asset=fill['feeAsset'];fees[asset]=fees.get(asset,Decimal(0))+Decimal(str(fill['fee']))
                orders.append(item)
        finally:db.close()
    return {'status':'AUDIT_VERIFIED_LOCAL_RECORDS_RECONCILE_EXCHANGE_FOR_CURRENT_STATE' if ledgers else 'NO_LOCAL_REAL_LEDGER_NOT_PROOF_OF_NO_EXCHANGE_ORDERS',
        'orders':orders,'cumulative_fees_by_asset':{k:str(v) for k,v in fees.items()},
        'real_equity_curve':[],'realized_exchange_pnl':None,'mode':'BLOCKED_NO_ARM_IN_CONSOLE',
        'settlement_guaranteed':False}


def status(root):
    root=Path(root).resolve();folder=current_session(root)
    state=recorded_summary(folder) if (folder/'agentic_decisions.sqlite').is_file() else {}
    forward={};dbpath=folder/'forward_observations.sqlite'
    if dbpath.is_file():
        db=sqlite3.connect(dbpath.as_uri()+'?mode=ro',uri=True)
        try:
            tables={r[0] for r in db.execute('SELECT name FROM sqlite_master WHERE type=?',('table',))}
            for table in ('quotes','m6_predictions','m6_outcomes'):
                if table in tables:forward[table]=db.execute('SELECT count(*) FROM '+table).fetchone()[0]
            if 'm6_lease' in tables:
                forward['active_lease']=bool(db.execute('SELECT 1 FROM m6_lease WHERE expires>?',(time.time(),)).fetchone())
            if 'm6_predictions' in tables:
                forward['forecasts']=[json.loads(r[0]) for r in db.execute('SELECT payload FROM m6_predictions ORDER BY decision DESC LIMIT 20')]
        finally:db.close()
    saved=read_json(root/'operations/financial_shadow.json',{})
    if saved.get('session')!=str(folder):saved={}
    return {'backtest':read_json(root/'operations/financial_backtest.json',{}),
        'shadow':{**saved,**state,'forward':forward,
            'session':str(folder),'stop_requested':(folder/'operator_stop.json').is_file()},
        'real':{**account_evidence(root),'execution':spot_execution_status(root)},'deadline':schedule(),'LIVE':'HARD_DISABLED',
        'risk_gate':'UNCHANGED_DETERMINISTIC','observed_epoch':time.time()}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('command',choices=('account-status','backtest','shadow-prepare','shadow-run','shadow-stop','status'))
    p.add_argument('--root',default='atlas_store');p.add_argument('--symbols',default='BTCTMN,ETHTMN')
    p.add_argument('--max-runtime-seconds',type=float,default=120);p.add_argument('--resume',action='store_true')
    p.add_argument('--new-session',action='store_true',help='Explicit new source freeze; old sessions and data are preserved')
    a=p.parse_args();stop=threading.Event()
    for sig in (signal.SIGINT,signal.SIGTERM):signal.signal(sig,lambda *_:stop.set())
    if a.command=='account-status':result=account_evidence(a.root)
    elif a.command=='backtest':result=backtest(a.root)
    elif a.command=='shadow-prepare':result=prepare_shadow(a.root,tuple(a.symbols.split(',')),new_session=a.new_session)
    elif a.command=='shadow-run':result=run_shadow(a.root,seconds=a.max_runtime_seconds,resume=a.resume,stop=stop)
    elif a.command=='shadow-stop':result=stop_shadow(a.root)
    else:result=status(a.root)
    print(json.dumps(result,ensure_ascii=False,default=str))


if __name__=='__main__':main()
