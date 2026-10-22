"""Contest evidence gate: reports what is VERIFIED, not a made-up quality score.
Does not access private account, invent observations, or submit orders.
"""
from __future__ import annotations
import datetime as dt
import json
import sqlite3
import time
from pathlib import Path
from .atlas_deep import verified_champion
from .atlas_forward import report as forward_report


def readiness_report(lake):
    now=time.time();root=Path(lake.root)
    report={'generated_at_utc':dt.datetime.now(dt.timezone.utc).isoformat(),
       'assessment':'RESEARCH_ONLY_NOT_VERIFIED_FOR_LIVE_CONTEST_ORDERS',
       'trade_execution_enabled':False,
       'requirements':{'max_contest_hours':72,'minimum_prospective_shadow_hours':48,
                       'spot_only':True,'finish_in_tmn':True},
       'market_data':{},'ai_model':{},'news':{},'prospective_validation':{},
       'technical_debt':[]}
    spot=lake.db.execute("SELECT COUNT(*) FROM assets WHERE json_extract(metadata,'$.is_spot')=1").fetchone()[0]
    report['market_data']['catalog_spot_markets']=spot
    rows=lake.db.execute('''SELECT symbol,MAX(last_ts) FROM chunks
        WHERE resolution='15' AND status='COMPLETE' GROUP BY symbol''').fetchall()
    report['market_data']['symbols_with_verified_15m_history']=len(rows)
    report['market_data']['symbols_with_15m_data_within_45min']=sum(
        0<=now-(ts+900)<=2700 for _,ts in rows if ts is not None)
    report['market_data']['history_rows_total_including_derived_and_overlapping']=lake.status()['candles']
    if not report['market_data']['symbols_with_15m_data_within_45min']:
        report['technical_debt'].append('NO_FRESH_VERIFIED_15M_CANDLES')
    try:
        active=verified_champion(root/'models')
        meta=json.loads(active.with_suffix('.json').read_text(encoding='utf8'))
        hours=meta.get('validation_hours_effective')
        report['ai_model']={'research_champion':active.name,
            'architecture':meta.get('architecture'),
            'training_samples':meta.get('training_samples'),
            'validation_samples':meta.get('validation_samples'),
            'purged_global_split':meta.get('validation_protocol')=='GLOBAL_UTC_PURGED_V1',
            'validation_duration_hours':hours,
            'validated_for_48_hour_trading_performance':False,
            'economic_out_of_sample_evidence':'NOT_ESTABLISHED',
            'news_input_columns_present':False,
            'validation_note':'Pinball loss is not after-fee realized PnL; validation samples are correlated'}
        if not isinstance(hours,(int,float)) or hours<24:
            report['technical_debt'].append('CHAMPION_VALIDATION_SHORTER_THAN_24H')
    except (OSError,ValueError,RuntimeError,KeyError,TypeError) as e:
        report['ai_model']={'champion_status':'NO_VERIFIED_RESEARCH_MODEL',
                            'error_type':type(e).__name__}
        report['technical_debt'].append('NO_VERIFIED_RESEARCH_CHAMPION')
    dbfile=root/'news.sqlite'
    if dbfile.is_file():
        with sqlite3.connect(dbfile) as db:
            num=db.execute('SELECT COUNT(*) FROM articles').fetchone()[0]
        report['news']={'actual_article_receipts':num,
            'model_uses_news_features':False,
            'finding':'Archive exists; current DL feature list does not use news sentiment or text'}
    else:
        report['news']={'actual_article_receipts':0,'model_uses_news_features':False}
    report['prospective_validation']=forward_report(root)
    if report['prospective_validation']['scored']<20:
        report['technical_debt'].append('INSUFFICIENT_PROSPECTIVE_GENUINE_BID_ASK_OUTCOMES')
    # Prospective evidence also needs >=48 hours of observations across time,
    # not merely large sample counts across correlated assets.
    dbpath=root/'forward_observations.sqlite'
    with sqlite3.connect(dbpath) as db:
        t0,t1=db.execute('SELECT MIN(observed_epoch),MAX(observed_epoch) FROM quotes').fetchone()
        receipts=db.execute('SELECT symbol,observed_epoch FROM quotes ORDER BY symbol,observed_epoch').fetchall()
    span_hours=(t1-t0)/3600 if t0 is not None and t1 is not None else 0.0
    report['prospective_validation']['distinct_observation_span_hours']=round(span_hours,3)
    report['prospective_validation']['spans_at_least_48_hours']=span_hours>=48
    # 48h duration ALONE is insufficient: two widely separated snapshots
    # are not a continuous shadow test. Measure per-market receipt coverage.
    import collections
    bysym=collections.defaultdict(list)
    for sym,epoch in receipts:bysym[sym].append(epoch)
    coverage=[]
    for sym,ts in bysym.items():
        last=max(ts);start=last-48*3600
        recent=sorted(t for t in ts if t>=start)
        buckets={int((t-start)//900) for t in recent}
        max_gap=max((b-a for a,b in zip(recent,recent[1:])),default=float('inf'))
        complete=bool(recent and recent[-1]-recent[0]>=47.5*3600
            and len(buckets)>=144 and max_gap<=1800)
        coverage.append({'symbol':sym,'observed_15min_buckets_last_48h':len(buckets),
                         'maximum_observed_gap_minutes':round(max_gap/60,2) if max_gap!=float('inf') else None,
                         'sufficient_prospective_quote_coverage':complete})
    coverage.sort(key=lambda r:r['observed_15min_buckets_last_48h'],reverse=True)
    sufficient=any(row['sufficient_prospective_quote_coverage'] for row in coverage)
    report['prospective_validation']['market_coverage_48h']=coverage[:12]
    report['prospective_validation']['has_sufficient_48h_quote_coverage_for_any_market']=sufficient
    if not sufficient:
        report['technical_debt'].append('NO_CONTINUOUS_48H_FORWARD_SHADOW_EVIDENCE')
    # Operational context memory is a separately auditable component, not a
    # financial backtest or a claim that an LLM is controlling exchange orders.
    from .atlas_context import ContextStore
    from .atlas_skills import menu,tools_for
    cm=ContextStore(root)
    try:
        report['context_engineering']={
            'memory':cm.status(),
            'registered_skill_count':len(menu()),
            'watch_phase_tool_count':len(tools_for('watch')),
            'progressive_local_skills':True,
            'untrusted_news_can_grant_permissions':False,
            'lessons_can_retrain_or_rewrite_automatically':False,
            'context_optimizations_proven_to_improve_pnl':False}
        if not report['context_engineering']['memory']['hash_chain_valid']:
            report['technical_debt'].append('CONTEXT_MEMORY_HASH_CHAIN_INVALID')
    finally:cm.close()
    report['technical_debt'].extend(['TRADING_MARKET_ALLOWLIST_NOT_INDEPENDENTLY_VERIFIED',
                                   'CREDIT_PACKAGE_RESTRICTIONS_NOT_VERIFIED_FOR_LIVE_ORDERS',
                                   'REAL_ORDER_MANAGEMENT_NOT_IMPLEMENTED',
                                   'NO_CONFIRMED_REALIZED_TMN_CONTEST_PNL'])
    out=root/'reports'/'v3_3_contest_readiness.json'
    out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding='utf8')
    return {'output':str(out),**report}
