"""Only inspect recorded genuine Wallex research data, model checkpoint metadata,
news receipts and paper ledger. No market prices or mock fills are produced.
"""
from __future__ import annotations
import json, sqlite3, collections, datetime, time
from pathlib import Path
from .atlas_deep import model_metadata_eligible, verified_champion


def audit_v3(lake):
    base=Path(lake.root)
    report={'generated_at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
            'mode':'READ_ONLY_REAL_DATA_AUDIT',
            'archive':lake.status(),
            'observed_candle_chunks':[], 'historical_failure_kinds':[],
            'model_checkpoints':[], 'news':{}, 'shadow':{}, 'warnings':[]}
    records=lake.db.execute('''SELECT symbol,resolution,count(*),sum(rows),max(last_ts)
        FROM chunks WHERE status='COMPLETE' GROUP BY symbol,resolution
        ORDER BY sum(rows) DESC LIMIT 30''').fetchall()
    report['observed_candle_chunks']=[{'symbol':s,'timeframe':r,'chunks':c,'candle_rows':n,
        'latest_observed_bar_open_utc':datetime.datetime.fromtimestamp(ts,datetime.timezone.utc).isoformat() if ts else None}
         for s,r,c,n,ts in records]
    incidents=lake.db.execute('SELECT error,count(*) FROM incidents GROUP BY error ORDER BY count(*) DESC').fetchall()
    buckets=collections.Counter()
    for error,count in incidents:
        if 'spacing' in error or 'resolution' in error:buckets['source_interval_or_gap_validation']+=count
        elif 'no_data' in error:buckets['exchange_no_data']+=count
        elif 'incomplete' in error:buckets['missing_genuine_candle_periods']+=count
        elif 'Timeout' in error or 'Connection' in error:buckets['network']+=count
        else:buckets['other']+=count
    report['historical_failure_kinds']=[{'kind':k,'incidents':v} for k,v in buckets.most_common()]
    for p in sorted((base/'models').glob('*.json')):
        # *.sources.json are genuine provenance ARRAYS, not model config OBJECTS.
        if p.name.endswith('.sources.json') or p.name == 'active_champion.json':
            continue
        try:
            cfg=json.loads(p.read_text(encoding='utf-8'))
            if not isinstance(cfg, dict) or not cfg.get('architecture'):
                report['warnings'].append('Ignored non-model JSON: '+p.name)
                continue
            report['model_checkpoints'].append({'metadata_file':p.name,'architecture':cfg.get('architecture'),
             'protocol':cfg.get('validation_protocol','OLD_PER_SEGMENT_NOT_GLOBALLY_PURGED'),
             'best_epoch':cfg.get('best_epoch'),'validation_pinball':cfg.get('validation_pinball'),
             'training_samples':cfg.get('training_samples'),'validation_samples':cfg.get('validation_samples'),
             'validation_start_ts':cfg.get('validation_start_ts'),'train_last_label_ts':cfg.get('train_last_label_ts'),
             'validation_hours_effective':cfg.get('validation_hours_effective'),
             'train_to_validation_ratio':round(cfg.get('training_samples',0)/max(1,cfg.get('validation_samples',1)),3),
             'eligible_on_sample_balance':model_metadata_eligible(cfg)[0],
             'ineligibility_reasons':model_metadata_eligible(cfg)[1]})
        except (OSError,ValueError,TypeError,KeyError,AttributeError) as e:
            report['warnings'].append('Unreadable model metadata: '+p.name+' ('+type(e).__name__+')')
    newsdb=base/'news.sqlite'
    if newsdb.is_file():
        with sqlite3.connect(newsdb) as db:
            row=db.execute('SELECT count(*),max(first_observed_at) FROM articles').fetchone()
            report['news']={'genuine_articles':row[0],'last_first_observed_utc':row[1]}
    else:report['news']={'genuine_articles':0,'status':'NO_NEWS_ARCHIVE_YET'}
    paperdb=base/'shadow.sqlite'
    if paperdb.is_file():
        with sqlite3.connect(paperdb) as db:
            actions=db.execute('SELECT action,count(*) FROM events GROUP BY action ORDER BY count(*) DESC').fetchall()
            report['shadow']={'audit_events_by_action':dict(actions),
             'open_paper_positions':db.execute('SELECT count(*) FROM positions').fetchone()[0]}
    else:report['shadow']={'status':'NO_PAPER_LEDGER_YET'}
    try:
        report['approved_champion_file']=str(verified_champion(base/'models'))
    except (RuntimeError,OSError,ValueError,TypeError) as e:
        report['approved_champion_file']=None
        report['warnings'].append('No verified active champion: '+str(e)[:150])
    if not report['news'].get('genuine_articles'):
        report['warnings'].append('News features unavailable: no genuinely observed published articles yet')
    if not any(m.get('protocol')=='GLOBAL_UTC_PURGED_V1' for m in report['model_checkpoints']):
        report['warnings'].append('Old DL checkpoints lack market-wide global temporal validation; retrain before new shadow cycle')
    for m in report['model_checkpoints']:
        if m.get('train_to_validation_ratio',0)<2:
            report['warnings'].append('Training/validation imbalance in '+m['metadata_file']+'; not suitable for champion promotion')
    report['warnings'].append('Backtest/Shadow metrics are hypothetical, NOT executed trades or verified contest profit')
    out=base/'reports'/'v3_2_audit.json';out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding='utf-8')
    return {'output':str(out),'archive':report['archive'],
        'failure_kinds':report['historical_failure_kinds'],
        'model_checkpoints':report['model_checkpoints'],
        'news':report['news'],'shadow':report['shadow'],
        'approved_champion_file':report['approved_champion_file'],
        'warnings':report['warnings']}
