"""Read-only short-horizon operational evidence audit for Wallex Atlas.

Source note: Stage 8 local receipt databases and RiskGate cost formula; no external
code copied. Prices/forecasts/news are read ONLY from observed Atlas ledgers.
No submission, retrieval, model inference, memory writes or report writes.
"""
from __future__ import annotations
import collections
import datetime as dt
import json
import math
import sqlite3
from pathlib import Path


def _read_connection(path):
    path=Path(path)
    if not path.is_file():
        return None
    # URI read-only + query_only forbid modifying any attached database.
    db=sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True,timeout=2)
    db.execute('PRAGMA query_only=ON')
    return db


def _table(db,name):
    return bool(db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",(name,)).fetchone())


def _rounded(value):
    return round(float(value),8) if value is not None and math.isfinite(value) else None


def shadow_audit(root):
    db=_read_connection(Path(root)/'shadow.sqlite')
    if db is None:return {'status':'NO_SHADOW_DATABASE'}
    try:
        if not _table(db,'events'):return {'status':'NO_SHADOW_EVENTS_TABLE'}
        actions=dict(db.execute('SELECT action,COUNT(*) FROM events GROUP BY action').fetchall())
        rejected=collections.Counter();gates=collections.Counter();sample=[]
        # No free-form error payloads are returned: may contain untrusted content.
        for eid,action,raw in db.execute('SELECT id,action,payload FROM events ORDER BY id'):
            if action not in ('REJECTED','INSUFFICIENT_RISK_ADJUSTED_EDGE','NO_TRUSTED_FORECAST'):
                continue
            try:entry=json.loads(raw)
            except (ValueError,TypeError):rejected['CORRUPT_EVENT_PAYLOAD']+=1;continue
            risk=entry.get('risk_gate',{})
            if isinstance(risk,dict) and isinstance(risk.get('reason'),str):
                gates[risk['reason'][:60]]+=1
            if action=='REJECTED':
                rawerror=entry.get('error')
                if isinstance(rawerror,str) and rawerror:
                    cls=rawerror.split(':',1)[0].strip()
                    rejected[cls if cls.isidentifier() else 'UNCLASSIFIED_ERROR']+=1
                    if len(sample)<12:sample.append({'event_id':eid,'error_type':cls if cls.isidentifier() else 'UNCLASSIFIED_ERROR'})
                else:rejected['NO_ERROR_DETAILS_IN_EVENT']+=1
        return {'status':'READ_ONLY','event_actions':actions,
                'rejected_exception_types':dict(rejected.most_common()),
                'risk_gate_reason_counts':dict(gates.most_common()),
                'rejected_event_sample':sample,
                'note':'Historical rejection strings may not identify root cause; inspect the original event locally without sharing secrets'}
    finally:db.close()


def forward_audit(root):
    db=_read_connection(Path(root)/'forward_observations.sqlite')
    if db is None:return {'status':'NO_FORWARD_DATABASE'}
    try:
        if not all(_table(db,t) for t in ('forecasts','quotes','outcomes')):
            return {'status':'INCOMPLETE_FORWARD_SCHEMA'}
        statuses=dict(db.execute('SELECT status,COUNT(*) FROM forecasts GROUP BY status').fetchall())
        rows=db.execute("""SELECT f.symbol,f.q10,f.q50,f.q90,f.fee_per_side,
                                f.horizon_seconds,orig.observed_epoch,orig.best_bid,orig.best_ask,
                                f.due_epoch,o.actual_mid_log_return,
                                o.observed_ask_to_future_bid_net_log_return,future.observed_epoch
                           FROM forecasts f
                           JOIN quotes orig ON orig.id=f.origin_quote_id
                           LEFT JOIN outcomes o ON o.forecast_id=f.id
                           LEFT JOIN quotes future ON future.id=o.future_quote_id
                           ORDER BY f.symbol,orig.observed_epoch""").fetchall()
        bysym=collections.defaultdict(list)
        for row in rows:bysym[row[0]].append(row)
        output=[]
        for sym,records in sorted(bysym.items()):
            tested=0;passed=0;actual=[];sign_correct=0;net=[];q10cov=0;q90cov=0
            nonoverlap=0;next_allowed=float('-inf')
            horizon_miss=[]
            for sym,q10,q50,q90,fee,horizon,observed,bid,ask,due,actual_ret,net_ret,future_at in records:
                # A threshold diagnostic only, not a trade/portfolio simulation.
                if all(math.isfinite(float(v)) for v in (q10,fee,bid,ask)) and 0<bid<ask and 0<=fee<.05:
                    tested+=1
                    threshold=2*math.log1p(fee)+math.log(ask/bid)+.001
                    passed+=int(q10>threshold)
                if actual_ret is None:continue
                actual.append(abs(actual_ret-q50))
                sign_correct+=int((actual_ret>0)==(q50>0))
                net.append(net_ret)
                q10cov+=int(actual_ret>=q10)
                q90cov+=int(actual_ret<=q90)
                if future_at is not None:horizon_miss.append(future_at-due)
                # Conservative measurement of independent time windows per symbol.
                if observed>=next_allowed:
                    nonoverlap+=1
                    next_allowed=due
            n=len(actual)
            output.append({'symbol':sym,'forecast_count':len(records),'scored_count':n,
                'q10_above_observed_cost_threshold':passed,
                'valid_cost_checks':tested,
                'q10_cost_threshold_is_not_order_approval':True,
                'directional_accuracy_quote_proxy':_rounded(sign_correct/n) if n else None,
                'observed_ask_to_future_bid_net_log_mean':_rounded(sum(net)/n) if n else None,
                'mean_abs_mid_quote_forecast_error':_rounded(sum(actual)/n) if n else None,
                'q10_coverage_quote_proxy':_rounded(q10cov/n) if n else None,
                'q90_coverage_quote_proxy':_rounded(q90cov/n) if n else None,
                'nonoverlapping_scored_windows_upper_count':nonoverlap,
                'median_outcome_arrival_lag_after_due_seconds':_rounded(sorted(horizon_miss)[len(horizon_miss)//2]) if horizon_miss else None})
        return {'status':'READ_ONLY','forecast_statuses':statuses,'symbols':output,
                'caveats':['Quantiles trained close-to-close; evaluated quote-to-quote',
                           'Predictions across assets and adjacent windows are correlated',
                           'No verified fee or actual fills: NOT realized trading PnL',
                           'Cost threshold uses RiskGate fee/spread/safety formula only; ignores other vetoes']}
    finally:db.close()


def news_audit(root):
    db=_read_connection(Path(root)/'news.sqlite')
    if db is None:return {'status':'NO_NEWS_DATABASE'}
    try:
        if not _table(db,'articles'):return {'status':'NO_NEWS_TABLE'}
        count,last,unscored=db.execute("""SELECT COUNT(*),MAX(first_observed_at),
            SUM(CASE WHEN sentiment IS NULL THEN 1 ELSE 0 END) FROM articles""").fetchone()
        return {'status':'READ_ONLY','archived_articles':count,
                'last_first_observed_at_utc':last,'articles_without_sentiment':unscored,
                'note':'Archive count is NOT new articles per watch cycle and news is NOT a DL input'}
    finally:db.close()


def watch_audit(root,tail=40):
    path=Path(root)/'watch_log.jsonl'
    if not path.is_file():return {'status':'NO_WATCH_LOG'}
    recent=collections.deque(maxlen=max(1,min(500,int(tail))))
    with path.open('r',encoding='utf-8') as file:
        for line in file:
            try:recent.append(json.loads(line))
            except ValueError:continue
    rows=list(recent)
    failures=[]; shadow_failures=collections.Counter();news_errors=collections.Counter()
    for row in rows:
        fail=row.get('failed_chunks',0)
        if isinstance(fail,int) and fail>0:
            failures.append({'utc':row.get('utc'),'failed_chunks':fail,
                'downloaded_chunks':row.get('downloaded_chunks')})
        shadow=row.get('shadow',{})
        if isinstance(shadow,dict):
            err=shadow.get('shadow_cycle_failed')
            if isinstance(err,str):shadow_failures[err.split(':')[0]]+=1
        news=row.get('news',{})
        if isinstance(news,dict):
            for issue in news.get('errors',[]):
                if isinstance(issue,dict):news_errors[str(issue.get('error','UNKNOWN')).split(':')[0][:48]]+=1
    return {'status':'READ_ONLY','cycles_checked':len(rows),'recent_download_failure_cycles':failures[-12:],
            'recent_shadow_failure_types':dict(shadow_failures),
            'recent_news_source_error_types':dict(news_errors),
            'note':'Failed chunks are archive harvest requests, not exchange orders; inspect original log for exact incidents'}


def operational_report(root):
    path=Path(root)
    # Intentionally no mkdir, no write, no memory calls, no network.
    return {'mode':'OPERATIONS_READ_ONLY_EXISTING_EVIDENCE','exchange_orders':0,
        'database_mutation':False,'model_or_market_requests':False,
        'watch':watch_audit(path),'shadow':shadow_audit(path),
        'forward':forward_audit(path),'news':news_audit(path),
        'promotion_or_risk_change':False}
