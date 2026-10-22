"""Versioned research-only news feature definitions and candle-cutoff join."""
import hashlib
from pathlib import Path
from .atlas_news_pipeline import WINDOWS,PROTOCOL

def registry():
    specs=[]
    for hours in WINDOWS:
        specs.extend([
            {'name':f'news_count_{hours}h','window_hours':hours,'formula':f'count distinct relevant article_id with available_at in (cutoff-{hours}h,cutoff] and linking processed<=cutoff'},
            {'name':f'news_sentiment_{hours}h','window_hours':hours,'formula':f'sum(confidence*exp(-age/{hours}h)*(Ppositive-Pnegative))/sum(weights); model processed<=cutoff'}])
    specs.extend({'name':name,'window_hours':24,'formula':formula} for name,formula in [
        ('news_source_count_24h','count distinct observed publisher/source IDs, not a proof of editorial independence'),
        ('news_importance_24h','max versioned rule importance among relevant events'),
        ('news_age_hours','hours since latest relevant available_at'),
        ('news_sentiment_momentum','weighted sentiment 1h minus weighted sentiment 6h'),
        ('news_intensity_1h_vs_24h','24*count1h/count24h; undefined when denominator=0'),
        ('news_missing_mask','1 when any defined feature unavailable; 0 otherwise')])
    for spec in specs:spec.update(recipe_version=PROTOCOL,source='news.sqlite immutable receipts + timestamped model estimates',
        missing_policy='None; zero counts only under observed complete source coverage',
        availability_policy='published, first_observed, linking_processed and model_processed all <= decision cutoff',
        supported_languages_for_sentiment=['en'],authority='CHALLENGER_AND_ADVISORY_ONLY')
    return {'recipe_version':PROTOCOL,'feature_count':len(specs),'definitions':specs,
        'implementation_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'champion_input_changed':False,'normalization_fit':'TRAIN_ONLY_IF_INDEPENDENT_VALIDATION_AVAILABLE'}

def join_candle_decisions(store,symbol,candles,*,period=900):
    """Features keyed by actual candle close; callers must separately verify price receipts."""
    from datetime import datetime,timezone
    rows=[]
    for stamp in candles.timestamp:
        decision=int(stamp)+period
        result=store.features_at(symbol,datetime.fromtimestamp(decision,timezone.utc).isoformat())
        rows.append({'candle_open':int(stamp),'candle_close':decision,'decision_at':decision,**result})
    return rows

def advisory_packet(root,symbol,asof,*,record_memory=False,mode='SHADOW'):
    from .atlas_news_pipeline import NewsStore
    with NewsStore(root) as store:
        evidence=store.evidence_at(symbol,asof,limit=20)
        features=store.features_at(symbol,asof)
        memory=store.record_memory(symbol,asof,mode) if record_memory else None
    return {'symbol':symbol,'cutoff':asof,'authority':'ADVISORY_ONLY','evidence':evidence,
            'research_features':features,'memory_receipt':memory,'external_text_sent_to_tools':False,
            'summary':{'related_articles':len(evidence),'scored_articles':sum(x['sentiment'] is not None for x in evidence)}}
