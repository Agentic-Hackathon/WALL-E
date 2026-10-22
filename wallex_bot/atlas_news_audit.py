"""Reproducible Milestone 4 reports, price receipt eligibility and paired arms."""
from __future__ import annotations
import csv
import hashlib
import json
import subprocess
from datetime import datetime,timezone
from pathlib import Path
import numpy as np
import pandas as pd
from .atlas_archive import Lake
from .atlas_feature_provenance import annotate_receipts,microstructure_at
from .atlas_feature_registry import REGISTRY,registry_payload,compute_ohlcv_features
from .atlas_feature_audit_v3 import _closed_segment,_feature_rows
from .atlas_news_pipeline import NewsStore,now_utc,canonical,MODEL_ID,MODEL_REVISION,UNDERSTANDING,aware
from .atlas_news_features import registry as news_registry,advisory_packet,join_candle_decisions

def _json(path,value):path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf8')
def _csv(path,rows,columns):
    with path.open('w',encoding='utf8',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=columns,extrasaction='ignore');writer.writeheader();writer.writerows(rows)

def contract_report(lake,asof):
    raw=_closed_segment(lake,'PEPETMN','1',int(aware(asof).timestamp()))
    cmf={'status':'NO_VERIFIED_SOURCE'}
    if raw is not None:
        matrix=compute_ohlcv_features(raw);finite=np.isfinite(matrix.cmf20.to_numpy(dtype=float))
        zero_range=raw.high.eq(raw.low);zero_volume=raw.volume.eq(0)
        cmf={'status':'EXAMINED_REAL_VERIFIED_CANDLES','observed_bars':len(raw),'finite_cmf20':int(finite.sum()),
             'nonfinite_rate':float(1-finite.mean()),'high_equals_low_bars':int(zero_range.sum()),
             'zero_volume_bars':int(zero_volume.sum()),'windows_containing_undefined_clv':int(zero_range.rolling(20).sum().gt(0).sum()),
             'root_cause':'CLV denominator high-low equals zero on observed flat candles; a single NaN invalidates its full rolling CMF20 window. Zero rolling volume can also make CMF undefined.',
             'policy':'V3 values preserved; no price/volume/CLV imputation','latest_cmf20_finite':bool(finite[-1])}
    provenance=[]
    for symbol in ('BTCTMN','ETHTMN','USDTTMN','PEPETMN'):
        raw=_closed_segment(lake,symbol,'15',int(aware(asof).timestamp()))
        if raw is not None:
            data=annotate_receipts(lake,symbol,'15',raw)
            provenance.append({'symbol':symbol,'bars':len(data),'status':str(data.pit_status.iloc[-1]),
                'known_available_bars':int(data.available_at.notna().sum()),
                'candle_close_is_not_receipt':True})
    from .atlas_data_sync import DataSyncManager
    sync=DataSyncManager(lake)
    profiles={symbol:{profile:sync.feature_readiness(symbol,profile,now=aware(asof).timestamp())
              for profile in ('CORE','ADVANCED','NEWS_ENHANCED')} for symbol in ('BTCTMN','ETHTMN','USDTTMN','PEPETMN')}
    return {'protocol':'MILESTONE3_CONTRACT_FIXES_V3_1','generated_at':asof,'per_asset_profiles':profiles,
        'microstructure':[{'name':x.name,'source':x.source,'provenance_required_by_compute':True} for x in REGISTRY if x.family=='microstructure'],
        'timeframe_templates_and_instances':True,'definitions':registry_payload()['feature_count'],
        'cmf20_pepetmn_1m':cmf,'candle_provenance':provenance,
        'actual_book_computation_path':{symbol:microstructure_at(lake.root,symbol,aware(asof).timestamp()) for symbol in ('BTCTMN','ETHTMN')},
        'profiles':{'CORE':'unchanged Champion finite 96-bar context + 55 warmup and freshness',
                    'ADVANCED':'separate research feature set; optional for CORE',
                    'NEWS_ENHANCED':'CORE plus actual news model evidence and source coverage; optional for CORE'},
        'champion_changed':False,'risk_gate_changed':False,'live_execution':'HARD_DISABLED'}

def preliminary_ablation(lake,store,symbols,asof):
    """Generate both arms from identical receipt-eligible sample IDs and labels.

    A fixed ridge probe is allowed only with enough independent UTC spans.
    No epoch selection, transformers, trading rule or promotion occurs here.
    """
    from .atlas_signals import features
    from .atlas_deep import COLS
    samples=[];candidate_counts={};now=int(aware(asof).timestamp())
    for symbol in symbols:
        raw=_closed_segment(lake,symbol,'15',now)
        if raw is None:continue
        stamped=annotate_receipts(lake,symbol,'15',raw)
        # News scored today cannot be used at the earlier candle's decision time.
        eligible=np.flatnonzero(stamped.available_at.notna().to_numpy() &
            (stamped.available_at.to_numpy()<=stamped.candle_close_at.to_numpy()))
        candidate_counts[symbol]={'closed_bars':len(raw),'receipt_eligible_historical_decisions':len(eligible)}
        if not len(eligible):continue
        tech=features(raw)[COLS]
        for idx in eligible:
            if idx<151 or idx+3>=len(raw):continue
            stamp=int(stamped.candle_close_at.iloc[idx]);cut=datetime.fromtimestamp(stamp,timezone.utc).isoformat()
            news=store.features_at(symbol,cut)
            if not news['ready']:continue
            values=np.array(list(news['features'].values()),dtype=float);price=tech.iloc[idx].to_numpy(dtype=float)
            if not np.isfinite(price).all() or not np.isfinite(values).all():continue
            samples.append({'id':f'{symbol}:{stamp}','decision':stamp,'label_end':int(raw.timestamp.iloc[idx+3])+900,
                'price':price,'news':values,'y':float(np.log(raw.close.iloc[idx+3]/raw.close.iloc[idx]))})
    samples.sort(key=lambda x:(x['decision'],x['id']))
    span=(samples[-1]['decision']-samples[0]['decision'])/3600 if samples else 0
    common={'common_samples':len(samples),'common_sample_ids_sha256':hashlib.sha256(canonical([x['id'] for x in samples]).encode()).hexdigest(),
            'span_hours':span,'candidate_counts':candidate_counts,'economic_improvement_claim':False}
    if len(samples)<1280 or span<96:
        return [{**common,'arm':arm,'status':'INSUFFICIENT_PIT_NEWS_VALIDATION',
                 'reason':'Requires >=1280 shared receipt/news-eligible samples over >=96h before fixed train/validation/independent-test comparison',
                 'train_samples':0,'validation_samples':0,'test_samples':0,'mae':None,'calibration_slope':None}
                for arm in ('PRICE_TECH_ONLY','PRICE_TECH_NEWS')]
    cutoff1=samples[int(.6*len(samples))]['decision'];cutoff2=samples[int(.8*len(samples))]['decision']
    train=[x for x in samples if x['label_end']<cutoff1];val=[x for x in samples if cutoff1<=x['decision'] and x['label_end']<cutoff2];test=[x for x in samples if x['decision']>=cutoff2]
    if len(train)<512 or len(val)<128 or len(test)<128:
        return [{**common,'arm':arm,'status':'INSUFFICIENT_PIT_NEWS_VALIDATION','reason':'purged temporal split too small'} for arm in ('PRICE_TECH_ONLY','PRICE_TECH_NEWS')]
    from sklearn.linear_model import Ridge
    from sklearn.preprocessing import StandardScaler
    result=[]
    for arm in ('PRICE_TECH_ONLY','PRICE_TECH_NEWS'):
        get=lambda part:np.stack([x['price'] if arm=='PRICE_TECH_ONLY' else np.concatenate([x['price'],x['news']]) for x in part])
        scale=StandardScaler().fit(get(train));model=Ridge(alpha=1).fit(scale.transform(get(train)),[x['y'] for x in train])
        predictions=model.predict(scale.transform(get(test)));truth=np.array([x['y'] for x in test]);variance=float(np.var(predictions))
        result.append({**common,'arm':arm,'status':'FIXED_RIDGE_INDEPENDENT_TEST','train_samples':len(train),'validation_samples':len(val),'test_samples':len(test),
            'mae':float(np.mean(abs(predictions-truth))),'calibration_slope':float(np.cov(predictions,truth,ddof=0)[0,1]/variance) if variance>0 else None,
            'reason':'Ridge alpha=1 fixed in advance; scaler fitted on train only; no model promotion'})
    return result

def build_reports(root,output_dir='reports',symbols=('BTCTMN','ETHTMN','USDTTMN','PEPETMN'),record_memory=False):
    out=Path(output_dir);out.mkdir(parents=True,exist_ok=True);asof=now_utc()
    with NewsStore(root) as store:
        migration=store.migrate_legacy();processing=store.process();summary=store.summary()
        legacy=store.db.execute("SELECT count(*),sum(sentiment IS NOT NULL) FROM articles").fetchone() if store.db.execute("SELECT 1 FROM sqlite_master WHERE name='articles'").fetchone() else (0,0)
        runs=[dict(row) for row in store.db.execute('SELECT * FROM news_source_runs ORDER BY id')]
        health=[]
        from .atlas_news import RSS_FEEDS
        for source in ('GDELT_DOC_2',*RSS_FEEDS):
            entries=[x for x in runs if x['source']==source];success=sum(x['status']=='SUCCESS' for x in entries)
            health.append({'source':source,'polls':len(entries),'successes':success,'success_rate':success/len(entries) if entries else None,
                'requests_attempted':sum(x['attempts'] for x in entries),'new_articles':sum(x['new_articles'] for x in entries),
                'duplicates':sum(x['duplicates'] for x in entries),'timeouts':sum(x['error_type']=='ReadTimeout' for x in entries),
                'latest_status':entries[-1]['status'] if entries else 'NEVER_POLLED','latest_error':entries[-1]['error_type'] if entries else None})
        models=[]
        for started,finished,payload in store.db.execute('SELECT started_at,finished_at,payload_json FROM news_model_runs ORDER BY id'):
            models.append({**json.loads(payload),'started_at':started,
                           'elapsed_seconds':(aware(finished)-aware(started)).total_seconds()})
        documents=[dict(x) for x in store.db.execute('SELECT * FROM news_documents ORDER BY article_id')]
        coverage=[];linking=[];languages={};tampered=[]
        for doc in documents:
            analysis=store.db.execute('SELECT * FROM news_understanding WHERE article_id=? AND version=?',(doc['article_id'],UNDERSTANDING)).fetchone()
            info=json.loads(analysis['payload_json']) if analysis else {};language=info.get('language','unknown');languages[language]=languages.get(language,0)+1
            score=store.db.execute("SELECT * FROM news_sentiment WHERE article_id=? ORDER BY (status='SCORED') DESC,processed_at DESC LIMIT 1",(doc['article_id'],)).fetchone()
            payload=json.loads(score['payload_json']) if score else {};coverage.append({'article_id':doc['article_id'],'source':doc['source'],'detected_language':language,
                'processing_status':score['status'] if score else 'LANGUAGE_UNSUPPORTED' if language!='en' else 'PENDING_SENTIMENT',
                'confidence':payload.get('confidence'),'sentiment_label':payload.get('label'),'model_version':score['model_version'] if score else None,
                'processed_at':score['processed_at'] if score else None,'available_at':doc['available_at'],'content_sha256':doc['content_sha256']})
            for link in info.get('links',[]) or [{'symbol':None,'reason':info.get('scope','UNPROCESSED'),'ambiguity':'UNLINKED'}]:
                linking.append({'article_id':doc['article_id'],'symbol':link['symbol'],'scope':info.get('scope'),'reason':link['reason'],'ambiguity':link['ambiguity'],'event_type':info.get('event_type'),'importance':info.get('importance'),'version':UNDERSTANDING})
            from .atlas_news_pipeline import digest,normalize_content
            if digest(normalize_content(doc['title']).casefold())!=doc['content_sha256']:tampered.append(doc['article_id'])
        packets=[advisory_packet(root,symbol,asof,record_memory=record_memory) for symbol in symbols]
        _json(out/'news_source_health.json',{'captured_at':asof,'sources':health,'runs':runs,'history_before_instrumentation':'UNKNOWN_NOT_INFERRED','languages':languages,'content_scope':'HEADLINE_ONLY'})
        _json(out/'news_ingestion_summary.json',{'captured_at':asof,'legacy_untouched':{'articles':legacy[0],'scored':legacy[1] or 0},
            'after':summary,'migration_this_run':migration,'processing_this_run':processing,'model_runs':models,
            'before_investigation':{'articles':97,'scored':0,'observed_at':'2026-10-22 prior to Milestone 4 changes'},
            'diagnosis':{'dependencies_installed':True,'initial_pinned_finbert_weights_cached':False,
                'prior_finbert_called_automatically':False,'prior_persistent_error_tracking':False,
                'historical_exact_cause':'UNPROVEN_NO_HISTORICAL_PROCESSING_RECEIPTS',
                'verified_initial_attempt':'SENTIMENT_MODEL_UNAVAILABLE/LocalEntryNotFoundError'}})
        _csv(out/'news_sentiment_coverage.csv',coverage,['article_id','source','detected_language','processing_status','confidence','sentiment_label','model_version','processed_at','available_at','content_sha256'])
        _csv(out/'news_asset_linking_audit.csv',linking,['article_id','symbol','scope','reason','ambiguity','event_type','importance','version'])
        invalid=[d['article_id'] for d in documents if d['available_at'] is None or aware(d['available_at'])<max(aware(d['published_at']),aware(d['first_observed_at']))]
        _json(out/'news_pit_audit.json',{'captured_at':asof,'articles':len(documents),'invalid_availability_ids':invalid,
            'content_integrity_failures':tampered,'rule':'available=max(published,first_observed); linked/scored output requires processed_at<=cutoff',
            'same_day_download_never_assumed_available_yesterday':True,
            'earliest_available':min((d['available_at'] for d in documents if d['available_at']),default=None),
            'latest_available':max((d['available_at'] for d in documents if d['available_at']),default=None),
            'source_polling_coverage_24h':store.source_state(asof,24),
            'source_publication_time_warning':'GDELT seendate is provider observation, not proven publisher time',
            'accuracy':'NO_GROUND_TRUTH_LABELS_ACCURACY_NOT_ESTIMATED'})
        _json(out/'news_feature_registry.json',news_registry())
        from .atlas_context import ContextStore
        context=ContextStore(root,read_only=True)
        try:memory={'integrity':context.verify(),'recorded_news_refs':store.db.execute('SELECT COUNT(*) FROM news_memory_refs').fetchone()[0],
                    'ranked_news_events':sum(x['kind']=='NEWS_EVIDENCE' for x in context.ranked(purpose='research',limit=40))}
        finally:context.close()
        _json(out/'news_agent_evidence_audit.json',{'captured_at':asof,'packets':packets,'memory':memory,
            'authority':'ADVISORY_ONLY','new_sentiment_connected_to_risk_veto':False})
        lake=Lake(root)
        try:
            fixes=contract_report(lake,asof);ablation=preliminary_ablation(lake,store,symbols,asof)
        finally:lake.close()
        repository=Path(__file__).resolve().parents[1];protected={}
        for filename in ('atlas_risk.py','atlas_deep.py','atlas_signals.py','atlas_broker.py'):
            relative='wallex_bot/'+filename
            baseline=subprocess.check_output(['git','show','368a262:'+relative],cwd=repository)
            working=(repository/relative).read_bytes()
            protected[relative]={'unchanged_from_368a262':baseline.replace(b'\r\n',b'\n')==working.replace(b'\r\n',b'\n'),
                'comparison':'Git content normalized for Windows CRLF only',
                'baseline_sha256':hashlib.sha256(baseline).hexdigest(),'working_bytes_sha256':hashlib.sha256(working).hexdigest()}
        active=Path(root)/'models'/'active_champion.json'
        champion={'status':'NO_MANIFEST'}
        if active.is_file():
            selection=json.loads(active.read_text(encoding='utf8'));checkpoint=active.parent/selection['selected_checkpoint']
            champion={'selected_checkpoint':selection['selected_checkpoint'],
                'expected_sha256':selection['checkpoint_sha256'],
                'actual_sha256':hashlib.sha256(checkpoint.read_bytes()).hexdigest(),
                'manifest_sha256':hashlib.sha256(active.read_bytes()).hexdigest()}
            champion['checkpoint_matches_manifest']=champion['expected_sha256']==champion['actual_sha256']
        fixes['protected_source_evidence']=protected;fixes['champion_verification']=champion
        _json(out/'milestone3_contract_fixes.json',fixes)
        ablation_export=[{**x,'candidate_counts':canonical(x['candidate_counts'])} for x in ablation]
        _csv(out/'news_model_ablation.csv',ablation_export,['arm','status','common_samples','common_sample_ids_sha256','span_hours','train_samples','validation_samples','test_samples','mae','calibration_slope','reason','economic_improvement_claim','candidate_counts'])
    return {'captured_at':asof,**summary,'news_features':news_registry()['feature_count'],
        'valid_news_feature_values':{p['symbol']:sum(v is not None for v in p['research_features']['features'].values()) for p in packets},
        'ablation_status':ablation[0]['status'],'output_dir':str(out)}
