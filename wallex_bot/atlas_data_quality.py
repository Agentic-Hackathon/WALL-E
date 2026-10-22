"""Read-only coverage, integrity and PIT reporting for genuine Wallex evidence.

Source note: Wallex public UDF documentation, accessed 2026-10-22, documents
GET /v1/udf/history with symbol, resolution, from and to.  It is used only as
an API contract reference; actual archive status is calculated from SHA-pinned
local receipts and never inferred from documentation.
"""
from __future__ import annotations

import csv
import hashlib
import json
import sqlite3
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import requests

from . import market
from .atlas_archive import ALL_RESOLUTIONS, DERIVED, NATIVE, period_seconds


CSV_FIELDS = (
    'symbol','market_type','quote_asset','resolution','native_or_derived',
    'source_resolution','first_available','first_archived','last_archived',
    'expected_bars','verified_bars','missing_bars','coverage_percent',
    'observed_window_coverage_percent','latest_age_minutes','source_status',
    'hash_status','gap_count','failure_reason','first_observed_available_at',
    'coverage_window_start','coverage_window_end','order_book_snapshot_count',
    'microstructure_status','ask_to_future_bid_status'
)


def _utc(ts: int | float | None):
    if ts is None:
        return None
    return datetime.fromtimestamp(int(ts), timezone.utc).isoformat().replace('+00:00','Z')


def _atomic_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp=path.with_name(path.name+'.partial')
    try:
        temp.write_text(json.dumps(value,ensure_ascii=False,indent=2,sort_keys=True,default=str),encoding='utf-8')
        temp.replace(path)
    finally:
        temp.unlink(missing_ok=True)


def _sha256(path: Path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _table(db, name):
    return bool(db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",(name,)).fetchone())


def _gap_runs(stamps: np.ndarray, step: int):
    if len(stamps)<2:return 0
    return int(np.sum(np.diff(stamps)>step))


def _verified_rows(root: Path, db):
    """Return real candle timestamps only after file hash and OHLC validation."""
    values=defaultdict(lambda:{'stamps':set(),'files':0,'valid_files':0,'invalid':[]})
    rows=db.execute('''SELECT symbol,resolution,filename,sha256 FROM chunks
                     WHERE status='COMPLETE' ORDER BY symbol,resolution,begin,filename''').fetchall()
    for symbol,resolution,filename,digest in rows:
        entry=values[(symbol,resolution)]
        entry['files']+=1
        path=root/filename
        try:
            if not path.is_file() or _sha256(path)!=digest:
                raise RuntimeError('SHA256_MISMATCH_OR_MISSING_FILE')
            frame=market.normalize(pd.read_csv(path))
            step=period_seconds(resolution)
            stamps=frame.timestamp.to_numpy(dtype='int64')
            if (stamps%step).any() or (np.diff(stamps)!=step).any():
                raise RuntimeError('INVALID_CHUNK_GRID')
            entry['stamps'].update(int(x) for x in stamps)
            entry['valid_files']+=1
        except Exception as exc:
            entry['invalid'].append(f'{type(exc).__name__}: {str(exc)[:120]}')
    return values


def _latest_failures(db):
    rows=defaultdict(list)
    if _table(db,'incidents'):
        for symbol,resolution,created,error in db.execute('''SELECT symbol,resolution,created_at,error
                                                             FROM incidents ORDER BY id DESC'''):
            key=(symbol,resolution)
            if len(rows[key])<3:
                rows[key].append({'created_at':created,'reason':error})
    return rows


def _progress_rows(db):
    answer={}
    if _table(db,'download_progress'):
        for row in db.execute('''SELECT symbol,resolution,status,attempts,last_error,updated_at
                                 FROM download_progress'''):
            answer[(row[0],row[1])]={
                'status':row[2],'attempts':row[3],'last_error':row[4],'updated_at':row[5]}
    return answer


def _availability_rows(db):
    answer=defaultdict(list)
    if _table(db,'chunk_observations'):
        for symbol,resolution,retrieved,available,source_resolution in db.execute(
                '''SELECT symbol,resolution,retrieved_at,available_at,source_resolution
                   FROM chunk_observations ORDER BY id'''):
            answer[(symbol,resolution)].append({'retrieved_at':retrieved,'available_at':available,
                                                'source_resolution':source_resolution})
    return answer


def _row_for(asset, resolution, verified, failures, progress, availability, now, order_books):
    symbol=asset['symbol']
    source_resolution=DERIVED.get(resolution,(resolution,1))[0]
    origin='DERIVED' if resolution in DERIVED else 'NATIVE'
    record=verified.get((symbol,resolution),{})
    stamps=np.array(sorted(record.get('stamps',set())),dtype='int64')
    bad=record.get('invalid',[])
    available=availability.get((symbol,resolution),[])
    error_items=failures.get((symbol,resolution),[])
    source_failures=failures.get((symbol,source_resolution),[]) if origin=='DERIVED' else []
    latest_progress=progress.get((symbol,resolution))
    first=last=None
    expected=observed=missing=gaps=None
    observed_pct=None
    age=None
    if len(stamps):
        step=period_seconds(resolution)
        first,last=int(stamps[0]),int(stamps[-1])
        expected=(last-first)//step+1
        observed=len(stamps)
        missing=expected-observed
        gaps=_gap_runs(stamps,step)
        observed_pct=round(100*observed/expected,6) if expected else None
        age=round(max(0.0,now-(last+step))/60,6)
    if bad:
        status='ARCHIVE_INTEGRITY_FAILURE'
        hash_status='FAILED'
    elif len(stamps):
        status='ARCHIVED_VERIFIED_CONTIGUOUS' if missing==0 else 'ARCHIVED_VERIFIED_WITH_GAPS'
        hash_status='VERIFIED'
    elif origin=='DERIVED' and verified.get((symbol,source_resolution),{}).get('stamps'):
        status='DERIVATION_NOT_MATERIALIZED'
        hash_status='NOT_APPLICABLE'
    elif error_items or source_failures or (latest_progress and latest_progress['status'] not in ('CACHED_VALID','SAVED')):
        status='PUBLIC_SOURCE_UNAVAILABLE_OR_INCOMPLETE'
        hash_status='NOT_AVAILABLE'
    else:
        status='NOT_ARCHIVED_NOT_PROBED'
        hash_status='NOT_AVAILABLE'
    reason=[]
    if bad:reason.extend(bad[:2])
    if error_items:reason.extend(x['reason'] for x in error_items[:2])
    if source_failures and origin=='DERIVED':reason.append('SOURCE_'+source_resolution+': '+source_failures[0]['reason'])
    if latest_progress and latest_progress.get('last_error'):reason.append(latest_progress['last_error'])
    if not reason and status=='NOT_ARCHIVED_NOT_PROBED':
        reason.append('No verified archive chunk or recorded public probe for this catalog/resolution pair.')
    if status=='DERIVATION_NOT_MATERIALIZED':
        reason.append('Verified source exists; derived target has not been materialized from complete source buckets.')
    meta=asset['metadata']
    book=order_books.get(symbol,{'snapshots':0,'outcomes':0})
    market_type='SPOT' if meta.get('is_spot') is True else 'NON_SPOT_OR_UNKNOWN'
    return {
        'symbol':symbol,'market_type':market_type,'quote_asset':meta.get('quote_asset') or 'UNKNOWN',
        'resolution':resolution,'native_or_derived':origin,'source_resolution':source_resolution,
        # The UDF endpoint does not provide a verifiable market-history lower bound.
        'first_available':'UNKNOWN_UNPROVEN_BY_PUBLIC_API',
        'first_archived':_utc(first),'last_archived':_utc(last),
        'expected_bars':expected,'verified_bars':observed,'missing_bars':missing,
        'coverage_percent':'UNKNOWN',
        'observed_window_coverage_percent':observed_pct,'latest_age_minutes':age,
        'source_status':status,'hash_status':hash_status,'gap_count':gaps,
        'failure_reason':' | '.join(str(x)[:280] for x in reason) if reason else None,
        'first_observed_available_at':available[0]['available_at'] if available else None,
        'coverage_window_start':_utc(first),'coverage_window_end':_utc((last+period_seconds(resolution)) if last is not None else None),
        'order_book_snapshot_count':book['snapshots'],
        'microstructure_status':'REAL_RECEIPTS_AVAILABLE' if book['snapshots'] else 'NO_HISTORICAL_ORDER_BOOK_RECEIPTS',
        'ask_to_future_bid_status':'TIME_MATCHED_REAL_QUOTE_OUTCOMES_AVAILABLE' if book['outcomes'] else 'NO_TIME_MATCHED_REAL_FUTURE_BID_OUTCOME'
    }


def _order_book_summary(root: Path):
    path=root/'forward_observations.sqlite'
    base={'database_present':path.is_file(),'historical_order_book_available':False,
          'microstructure_feature_status':'INSUFFICIENT_OR_NOT_AUDITED','ask_to_future_bid_status':'INSUFFICIENT_OR_NOT_AUDITED'}
    if not path.is_file():return base
    try:
        db=sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True,timeout=2)
        try:
            tables={x[0] for x in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            base['tables']=sorted(tables)
            if 'quotes' in tables:
                row=db.execute('SELECT COUNT(*),MIN(observed_epoch),MAX(observed_epoch),COUNT(DISTINCT symbol) FROM quotes').fetchone()
                base.update({'real_snapshot_rows':row[0],'first_observed_at':row[1],
                             'last_observed_at':row[2],'symbols_with_snapshots':row[3],
                             'historical_order_book_available':bool(row[0]),
                             'microstructure_feature_status':'REAL_RECEIPTS_AVAILABLE_FOR_RECORDED_SYMBOLS_ONLY' if row[0] else 'INSUFFICIENT',
                             'ask_to_future_bid_status':'REQUIRES_TIME_MATCHED_LATER_REAL_RECEIPTS'})
            return base
        finally:db.close()
    except Exception as exc:
        base['read_error']=f'{type(exc).__name__}: {str(exc)[:160]}'
        return base


def _order_book_by_symbol(root: Path):
    path=root/'forward_observations.sqlite'
    result=defaultdict(lambda:{'snapshots':0,'outcomes':0})
    if not path.is_file():return result
    try:
        db=sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True,timeout=2)
        try:
            for symbol,count in db.execute('SELECT symbol,COUNT(*) FROM quotes GROUP BY symbol'):
                result[symbol]['snapshots']=count
            for symbol,count in db.execute('''SELECT f.symbol,COUNT(*) FROM outcomes o
                                               JOIN forecasts f ON f.id=o.forecast_id GROUP BY f.symbol'''):
                result[symbol]['outcomes']=count
        finally:db.close()
    except sqlite3.Error:
        pass
    return result


def probe_public_timeframes(symbol: str, *, delay_seconds=.15):
    """Make a bounded, public, no-authentication API contract observation.

    This does not claim support for all catalog markets or establish the first
    historical candle. It records exactly what the provider returned for one
    named symbol at local receipt time, including silent-grid incompatibility.
    """
    if not isinstance(symbol,str) or not symbol.isalnum() or symbol!=symbol.upper():
        raise ValueError('probe symbol must be an uppercase alphanumeric market symbol')
    tested=tuple(dict.fromkeys(('1','15','60','180','240','360','480','720','1D','2D','3D')))
    now=int(time.time())
    probes=[]
    for resolution in tested:
        seconds=market.ALLOWED_RESOLUTIONS.get(resolution)
        if seconds is None:
            # 180/360 are documented values, but deliberately not archive-supported
            # until a genuine returned grid verifies them.
            seconds={'180':10800,'360':21600}[resolution]
        span=max(12*3600, min(30*86400,seconds*4))
        received=datetime.now(timezone.utc).isoformat()
        try:
            response=requests.get(market.HOST+'/v1/udf/history',params={
                'symbol':symbol,'resolution':resolution,'from':now-span,'to':now},timeout=(5,20))
            body=response.json()
            stamps=body.get('t') if isinstance(body,dict) else None
            grid=None
            if isinstance(stamps,list) and len(stamps)>=2:
                values=np.array(stamps,dtype='int64')
                spacing=np.diff(values)
                grid={'returned_rows':len(values),'first_timestamp':int(values[0]),'last_timestamp':int(values[-1]),
                      'modal_spacing_seconds':int(pd.Series(spacing).mode().iloc[0]),
                      'matches_requested_grid':bool(np.all(spacing==seconds) and not (values%seconds).any())}
            elif isinstance(stamps,list):
                grid={'returned_rows':len(stamps),'matches_requested_grid':'INSUFFICIENT_ROWS_TO_INFER'}
            probes.append({'resolution':resolution,'requested_seconds':seconds,'received_at_utc':received,
                           'http_status':response.status_code,'provider_status':body.get('s') if isinstance(body,dict) else None,
                           'response_keys':sorted(body) if isinstance(body,dict) else None,'grid':grid})
        except Exception as exc:
            probes.append({'resolution':resolution,'requested_seconds':seconds,'received_at_utc':received,
                           'error':f'{type(exc).__name__}: {str(exc)[:180]}'})
        time.sleep(delay_seconds)
    return {'symbol':symbol,'scope':'ONE_SYMBOL_BOUNDED_PUBLIC_CONTRACT_PROBE_NOT_CATALOG_WIDE',
            'endpoint':'GET https://api.wallex.ir/v1/udf/history','probes':probes}


def probe_history_window_limits(symbol: str, *, delay_seconds=.15):
    """Bounded empirical request-window check; does not infer an exact provider cap."""
    if not isinstance(symbol,str) or not symbol.isalnum() or symbol!=symbol.upper():
        raise ValueError('probe symbol must be an uppercase alphanumeric market symbol')
    windows=(('1',12*3600),('1',24*3600),('1',48*3600),('60',365*86400),('1D',365*86400))
    now=int(time.time());samples=[]
    for resolution,span in windows:
        received=datetime.now(timezone.utc).isoformat()
        try:
            response=requests.get(market.HOST+'/v1/udf/history',params={
                'symbol':symbol,'resolution':resolution,'from':now-span,'to':now},timeout=(5,30))
            body=response.json(); stamps=body.get('t') if isinstance(body,dict) else None
            samples.append({'resolution':resolution,'requested_span_seconds':span,'received_at_utc':received,
                            'http_status':response.status_code,'provider_status':body.get('s') if isinstance(body,dict) else None,
                            'returned_rows':len(stamps) if isinstance(stamps,list) else None,
                            'first_timestamp':stamps[0] if isinstance(stamps,list) and stamps else None,
                            'last_timestamp':stamps[-1] if isinstance(stamps,list) and stamps else None})
        except Exception as exc:
            samples.append({'resolution':resolution,'requested_span_seconds':span,'received_at_utc':received,
                            'error':f'{type(exc).__name__}: {str(exc)[:180]}'})
        time.sleep(delay_seconds)
    return {'symbol':symbol,'scope':'ONE_SYMBOL_BOUNDED_WINDOW_PROBE_NOT_A_PROVIDER_LIMIT_PROOF',
            'documented_pagination_parameters':None,
            'interpretation':'A rejected wider interval is recorded as an observed response, not claimed as an exact maximum-candle limit.',
            'samples':samples}


def build_reports(lake, output_dir='reports', probe_symbol=None):
    """Create requested reports from the complete discovered catalog without network I/O.

    The report deliberately distinguishes a complete *audit matrix* from a
    complete *historical archive*. A missing or unprobed row is kept in CSV.
    """
    root=Path(lake.root)
    output=Path(output_dir)
    now=time.time()
    assets=[]
    for symbol,raw in lake.db.execute('SELECT symbol,metadata FROM assets ORDER BY symbol'):
        try:
            meta=json.loads(raw)
            if isinstance(meta,dict):assets.append({'symbol':symbol,'metadata':meta})
        except json.JSONDecodeError:
            assets.append({'symbol':symbol,'metadata':{}})
    verified=_verified_rows(root,lake.db)
    failures=_latest_failures(lake.db)
    progress=_progress_rows(lake.db)
    availability=_availability_rows(lake.db)
    order_books=_order_book_by_symbol(root)
    rows=[_row_for(asset,resolution,verified,failures,progress,availability,now,order_books)
          for asset in assets for resolution in ALL_RESOLUTIONS]
    output.mkdir(parents=True,exist_ok=True)
    csv_path=output/'data_coverage.csv'
    with csv_path.open('w',newline='',encoding='utf-8') as handle:
        writer=csv.DictWriter(handle,fieldnames=CSV_FIELDS,extrasaction='ignore')
        writer.writeheader();writer.writerows(rows)
    by_resolution={}
    for resolution in ALL_RESOLUTIONS:
        subset=[r for r in rows if r['resolution']==resolution]
        statuses=Counter(r['source_status'] for r in subset)
        verified_subset=[r for r in subset if r['hash_status']=='VERIFIED']
        by_resolution[resolution]={
            'rows':len(subset),'source_resolution':DERIVED.get(resolution,(resolution,1))[0],
            'native_or_derived':'DERIVED' if resolution in DERIVED else 'NATIVE',
            'statuses':dict(statuses),'verified_rows':len(verified_subset),
            'contiguous_rows':sum(r['source_status']=='ARCHIVED_VERIFIED_CONTIGUOUS' for r in subset),
            'gapped_rows':sum(r['source_status']=='ARCHIVED_VERIFIED_WITH_GAPS' for r in subset),
            'observed_window_verified_bars':sum(r['verified_bars'] or 0 for r in verified_subset),
            'overall_historical_coverage':'UNKNOWN_UNPROVEN_HISTORY_START'}
    incidents=[]
    for (symbol,resolution),items in sorted(failures.items()):
        for item in items:
            incidents.append({'symbol':symbol,'resolution':resolution,**item})
    progress_list=[]
    if _table(lake.db,'download_progress'):
        names=[x[1] for x in lake.db.execute('PRAGMA table_info(download_progress)')]
        for values in lake.db.execute('SELECT * FROM download_progress ORDER BY updated_at,symbol,resolution,begin'):
            progress_list.append(dict(zip(names,values)))
    observation_stats={
        'chunk_observation_records':sum(len(x) for x in availability.values()),
        'legacy_chunks_without_separate_receipt_availability_provenance':sum(
            1 for _ in lake.db.execute('SELECT 1 FROM chunks WHERE status="COMPLETE"'))-
            sum(len(x) for x in availability.values()),
        'rule':'A historical candle timestamp is never proof it was available then; only local receipt/available_at is PIT evidence.'
    }
    timeframe={
        'generated_at_utc':datetime.now(timezone.utc).isoformat(),
        'adapter_native_resolutions':list(NATIVE),'derived_resolutions':DERIVED,
        'all_supported_archive_resolutions':list(ALL_RESOLUTIONS),
        'public_udf_endpoint':'GET https://api.wallex.ir/v1/udf/history',
        'public_documentation_observed_utc':'2026-10-22',
        'documented_udf_resolution_values':['1','60','180','360','720','1D'],
        'rule':'Only returned timestamps matching the requested source grid are accepted; incomplete derived buckets are dropped.',
        'per_resolution':by_resolution
    }
    if probe_symbol:
        timeframe['actual_public_api_probe']=probe_public_timeframes(probe_symbol)
        timeframe['actual_public_window_probe']=probe_history_window_limits(probe_symbol)
    summary={
        'generated_at_utc':datetime.now(timezone.utc).isoformat(),
        'catalog_assets':len(assets),'catalog_resolution_rows':len(rows),
        'scope':'All discovered catalog markets; trade eligibility is intentionally not inferred.',
        'historical_coverage':'UNKNOWN_UNPROVEN_API_HISTORY_START',
        'coverage_definition':'observed_window_coverage_percent is computed only between first and last verified archived candle; it is not whole-history coverage.',
        'by_resolution':by_resolution,
        'source_statuses':dict(Counter(r['source_status'] for r in rows)),
        'hash_statuses':dict(Counter(r['hash_status'] for r in rows)),
        'remaining_gaps':sum((r['missing_bars'] or 0) for r in rows),
        'recorded_incidents':len(incidents),
        'order_book_audit':_order_book_summary(root)
    }
    pit={
        'generated_at_utc':datetime.now(timezone.utc).isoformat(),
        'candles':observation_stats,
        'closed_candle_rule':'Rows are accepted only when candle_open_timestamp + resolution <= local request time.',
        'derived_rule':'A target OHLCV bucket is created only if every source candle in that epoch-aligned bucket is present and valid.',
        'gap_rule':'No missing interval is forward-filled, interpolated or synthesized.',
        'limitation':'Existing legacy chunks preserve observed_at but do not retroactively prove availability at each historical decision time.'
    }
    progress_report={
        'generated_at_utc':datetime.now(timezone.utc).isoformat(),
        'progress_rows':progress_list,
        'counts_by_status':dict(Counter(x['status'] for x in progress_list)),
        'resume_rule':'A valid matching chunk is cached; failed/queued windows retain their key and can be retried without replacing accepted evidence.',
        'conflicts_retained':lake.db.execute('SELECT count(*) FROM archive_conflicts').fetchone()[0] if _table(lake.db,'archive_conflicts') else 0
    }
    _atomic_json(output/'data_coverage_summary.json',summary)
    _atomic_json(output/'data_download_incidents.json',{'generated_at_utc':datetime.now(timezone.utc).isoformat(),'incidents':incidents})
    _atomic_json(output/'timeframe_integrity.json',timeframe)
    _atomic_json(output/'pit_data_quality.json',pit)
    _atomic_json(output/'download_progress.json',progress_report)
    return {'coverage_csv':str(csv_path),'rows':len(rows),'assets':len(assets),'summary':summary,
            'output_dir':str(output.resolve())}
