"""Stage 10: read-only economic edge and timing audit on GENUINE archived receipts.

No market data is manufactured, fetched, adjusted or inserted. No risk-policy
mutation, model promotion, hypothetical fills, account writes or trade calls.
Source: Wallex Atlas locally recorded forward/Shadow receipt schemas.
"""
from __future__ import annotations
import collections
import math
import statistics
import json
from pathlib import Path
from .atlas_operational import _read_connection, _table

# Only source-code-known RuntimeError literals are classified. Raw messages,
# symbols and arbitrary JSON content are never echoed from historical events.
_ERROR_RULES = (
    ('Latest genuine candle is stale', 'STALE_GENUINE_CANDLE'),
    ('Insufficient genuine contiguous context', 'INSUFFICIENT_CONTIGUOUS_HISTORY'),
    ('Recent real indicators missing', 'NONFINITE_INDICATOR_FEATURES'),
    ('Uncalibrated/inconsistent quantile predictions', 'INVALID_OR_CROSSED_QUANTILES'),
    ('Cannot mark equity: real bid observations missing', 'MISSING_OBSERVED_BID_FOR_HELD_ASSET'),
    ('Persistent paper audit corrupted', 'INVALID_SHADOW_AUDIT_CHAIN'),
    ('No approved explicit champion', 'MISSING_APPROVED_CHAMPION'),
    ('Champion checkpoint has changed', 'CHAMPION_FILE_CHANGED'),
    ('Champion provenance mismatch', 'CHAMPION_PROVENANCE_MISMATCH'),
    ('Insufficient balanced genuine windows', 'INSUFFICIENT_BALANCED_TRAINING_WINDOWS'),
    ('No usable continuous genuine market segments', 'NO_CONTIGUOUS_MARKET_SEGMENTS'),
    ('Paper trade must own its atomic SQLite transaction', 'ATOMIC_TRANSACTION_CONFLICT'),
)


def classify_recorded_error(value):
    if not isinstance(value, str):
        return 'ERROR_NOT_RECORDED'
    exception = value.split(':', 1)[0].strip()
    if exception in ('ReadTimeout', 'ConnectionError', 'ConnectTimeout'):
        return 'NETWORK_' + exception.upper()
    if exception != 'RuntimeError':
        return 'OTHER_RECORDED_EXCEPTION' if exception else 'ERROR_NOT_RECORDED'
    for prefix, label in _ERROR_RULES:
        if prefix in value:
            return label
    return 'RUNTIME_ERROR_UNCLASSIFIED_FROM_STORED_EVIDENCE'


def _safe_number(value):
    try:
        number=float(value)
        return number if math.isfinite(number) else None
    except (TypeError,ValueError,OverflowError):
        return None


def _median(seq):
    finite = [n for x in seq if (n := _safe_number(x)) is not None]
    return round(statistics.median(finite), 6) if finite else None


def _range(seq):
    finite = [n for x in seq if (n := _safe_number(x)) is not None]
    if not finite:
        return {'min': None, 'median': None, 'max': None}
    return {'min': round(min(finite), 6), 'median': round(statistics.median(finite), 6), 'max': round(max(finite), 6)}


def read_shadow_errors(root):
    db = _read_connection(Path(root)/'shadow.sqlite')
    if db is None:
        return {'status': 'NO_EXISTING_SHADOW_LEDGER'}
    try:
        if not _table(db, 'events'):
            return {'status': 'NO_EVENTS_TABLE'}
        grouped = collections.Counter()
        recent_ids = collections.defaultdict(list)
        for event_id, action, payload in db.execute('SELECT id,action,payload FROM events WHERE action=? ORDER BY id', ('REJECTED',)):
            try:
                item = json.loads(payload)
                label = classify_recorded_error(item.get('error') if isinstance(item,dict) else None)
            except (ValueError, TypeError):
                label = 'INVALID_EVENT_PAYLOAD'
            grouped[label] += 1
            if len(recent_ids[label]) < 5:
                recent_ids[label].append(event_id)
        return {'status':'READ_ONLY','classified_rejections':dict(sorted(grouped.items())),
                'event_ids_for_local_private_investigation':dict(sorted(recent_ids.items())),
                'unclassified_is_not_necessarily_a_single_root_cause': True,
                'free_text_error_messages_exposed': False}
    finally:
        db.close()


def read_cost_and_timing(root):
    db = _read_connection(Path(root)/'forward_observations.sqlite')
    if db is None:
        return {'status':'NO_EXISTING_FORWARD_LEDGER'}
    try:
        if not all(_table(db, t) for t in ('quotes', 'forecasts', 'outcomes')):
            return {'status':'INCOMPLETE_FORWARD_SCHEMA'}
        data = db.execute('''
            SELECT f.symbol,f.feature_end_ts,f.q10,f.q50,f.q90,f.fee_per_side,
                   f.due_epoch,f.horizon_seconds,f.status,
                   orig.observed_epoch,orig.best_bid,orig.best_ask,
                   o.actual_mid_log_return,future.observed_epoch
            FROM forecasts f JOIN quotes orig ON orig.id=f.origin_quote_id
            LEFT JOIN outcomes o ON o.forecast_id=f.id
            LEFT JOIN quotes future ON future.id=o.future_quote_id
            ORDER BY f.symbol,orig.observed_epoch,f.id''').fetchall()
        grouped=collections.defaultdict(list)
        for record in data:
            grouped[record[0]].append(record)
        output=[]
        total_checks=0
        for sym, rows in sorted(grouped.items()):
            all_gaps=[];fee_bps=[];spread_bps=[];threshold_bps=[];q10_bps=[];q50_bps=[]
            from_feature_age=[];arrival_lags=[];valid=0;scored=0
            q10_pass=q50_pass=q90_pass=0
            nonoverlap=0;next_due=-math.inf
            stale_feature=0
            for (_,feature_ts,q10,q50,q90,fee,due,horizon,status,epoch,bid,ask,actual,future_epoch) in rows:
                if _safe_number(feature_ts) is not None and _safe_number(epoch) is not None:
                    feature_age=float(epoch)-float(feature_ts)
                    from_feature_age.append(feature_age/60)
                    if feature_age>float(horizon): stale_feature += 1
                if _safe_number(future_epoch) is not None and _safe_number(due) is not None:
                    arrival_lags.append((float(future_epoch)-float(due))/60)
                if actual is not None and future_epoch is not None:
                    scored+=1
                    if _safe_number(epoch) is not None and _safe_number(due) is not None and float(epoch)>=next_due:
                        nonoverlap += 1
                        next_due=float(due)
                try:
                    nums=[float(v) for v in (q10,q50,q90,fee,bid,ask)]
                except (TypeError,ValueError,OverflowError): continue
                if not all(map(math.isfinite,nums)): continue
                if not (0 < bid < ask and 0 <= fee < 0.05 and q10<=q50<=q90): continue
                edge=2*math.log1p(fee)+math.log(ask/bid)+0.001
                valid +=1
                total_checks+=1
                threshold_bps.append(edge*10000)
                fee_bps.append(2*math.log1p(fee)*10000)
                spread_bps.append(math.log(ask/bid)*10000)
                q10_bps.append(q10*10000)
                q50_bps.append(q50*10000)
                all_gaps.append((q10-edge)*10000)
                q10_pass+=int(q10>edge)
                q50_pass+=int(q50>edge)
                q90_pass+=int(q90>edge)
            output.append({
                'symbol':sym,'forecasts':len(rows),'scored_with_later_actual_quote':scored,
                'valid_fee_and_book_checks':valid,
                'q10_exceeds_assumed_cost_count':q10_pass,
                'q50_exceeds_assumed_cost_count_diagnostic_only':q50_pass,
                'q90_exceeds_assumed_cost_count_diagnostic_only':q90_pass,
                'q10_minus_cost_log_bps':_range(all_gaps),
                'q10_forecast_log_bps':_range(q10_bps),
                'q50_forecast_log_bps':_range(q50_bps),
                'total_cost_log_bps':_range(threshold_bps),
                'assumed_roundtrip_fee_log_bps':_median(fee_bps),
                'observed_spread_log_bps':_range(spread_bps),
                'policy_safety_log_bps':10,
                'quote_received_after_feature_timestamp_minutes':_range(from_feature_age),
                'feature_age_exceeds_full_prediction_horizon_count':stale_feature,
                'future_quote_arrives_after_due_minutes':_range(arrival_lags),
                'nonoverlapping_scored_horizons_upper_bound':nonoverlap,
            })
        return {'status':'READ_ONLY','total_forecasts':len(data),
                'total_valid_cost_checks':total_checks,'symbols':output,
                'time_anchor_warning':'Model trained on close[t+h]/close[t] with feature timestamp at candle t; forward observation due uses origin-quote time plus horizon, not original feature timestamp.',
                'target_warning':'Forward outcomes are observed quote-mid returns, not training candle-close returns; timing differences and selection effects prevent calibrated OOS performance claims.',
                'fee_warning':'Fees recorded are research assumptions; depth is top-of-book evidence, not executable fill confirmation.',
                'q50_and_q90_counts_do_not_authorize_trading':True,
                'receipt_hash_chains_not_reverified_by_this_report':True,
                'policy_safety_constant_is_current_source_value_log_return':0.001}
    finally:
        db.close()


def edge_triage_report(root):
    return {'mode':'EXISTING_RECEIPTS_READ_ONLY_EDGE_TRIAGE',
            'network_or_model_requests':False,'order_submission':False,
            'writes_or_permission_changes':False,
            'shadow_errors':read_shadow_errors(root),
            'forecast_cost_and_timing':read_cost_and_timing(root),
            'risk_gate_policy_unchanged':True}
