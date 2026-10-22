"""Real news receipts, incremental understanding and advisory PIT features.

Independent Atlas implementation; reuses existing publisher/GDELT adapters and
FinMem concept, not external code. All text is untrusted data. No trading tools.
Legacy articles remain unchanged; new evidence lives in additive versioned tables.
"""
from __future__ import annotations
import hashlib
import html
import json
import math
import re
import sqlite3
import time
import unicodedata
from datetime import datetime,timezone,timedelta
from pathlib import Path
from urllib.parse import urlsplit,urlunsplit,parse_qsl,urlencode

PROTOCOL='ATLAS_NEWS_PIT_V1'
UNDERSTANDING='ATLAS_NEWS_RULE_LINKING_V1'
MODEL_ID='ProsusAI/finbert'
MODEL_REVISION='0bc2ac10dda6929bcb1f77ccc43c7ec5c424f031'
SAFE_WEIGHTS_SHA256='e5897858ff819aad7629b96ce521ae5477952d03634ef5dd30ed2d76357a9f00'
WINDOWS=(1,3,6,24)

def now_utc():return datetime.now(timezone.utc).isoformat()
def digest(text):return hashlib.sha256(text.encode('utf8')).hexdigest()
def canonical(obj):return json.dumps(obj,sort_keys=True,ensure_ascii=False,allow_nan=False,separators=(',',':'))
def aware(raw):
    from .atlas_news import iso_utc
    value=iso_utc(raw)
    return datetime.fromisoformat(value) if value else None
def cutoff_time(value):
    value=aware(value)
    if value is None or value>datetime.now(timezone.utc)+timedelta(seconds=1):
        raise ValueError('nonfuture aware decision cutoff required')
    return value

def valid_score(payload,content_hash):
    if not isinstance(payload,dict) or payload.get('input_sha256')!=content_hash:return False
    values=payload.get('probabilities',{})
    if set(values)!={'positive','negative','neutral'}:return False
    if not all(type(x) in (float,int) and math.isfinite(x) and 0<=x<=1 for x in values.values()):return False
    return (abs(sum(values.values())-1)<1e-5 and
            payload.get('artifact_sha256',{}).get('model.safetensors')==SAFE_WEIGHTS_SHA256 and
            abs(payload.get('signed_score',float('inf'))-(values['positive']-values['negative']))<1e-7 and
            abs(payload.get('confidence',float('inf'))-max(values.values()))<1e-7)

def normalize_content(title):
    return re.sub(r'\s+',' ',unicodedata.normalize('NFKC',html.unescape(title))).strip()
def canonical_url(url):
    parts=urlsplit(url)
    if parts.scheme not in ('http','https') or not parts.hostname or parts.username or parts.password:
        raise ValueError('public article URL required')
    query=[(k,v) for k,v in parse_qsl(parts.query) if not k.lower().startswith('utm_') and k.lower() not in ('fbclid','gclid')]
    return urlunsplit((parts.scheme.lower(),parts.netloc.lower(),parts.path.rstrip('/'),urlencode(sorted(query)),''))

def language_of(text):
    if not text.strip():return 'unknown',0.0,'EMPTY_TEXT'
    try:
        from langdetect import detect_langs,DetectorFactory
        DetectorFactory.seed=0
        choices=detect_langs(text)
        best=choices[0]
        return (best.lang,float(best.prob),'langdetect:seed=0') if best.prob>=.85 else ('unknown',float(best.prob),'LOW_CONFIDENCE')
    except Exception:return 'unknown',0.0,'LANGUAGE_DETECTOR_UNAVAILABLE'

def link_assets(text):
    """High precision curated names; ordinary PUMP/PEPE/BTC words aren't identity proof."""
    mapping={'BTCTMN':('bitcoin','بیت کوین','بیت‌کوین'), 'ETHTMN':('ethereum','ether','اتریوم'),
             'USDTTMN':('tether','تتر'), 'DOGETMN':('dogecoin','دوج کوین'),
             'BNBTMN':('binance coin',), 'SOLTMN':('solana',),'XRPTMN':('ripple',)}
    matches=[]
    for symbol,names in mapping.items():
        terms=[term for term in names if re.search(r'(?<!\w)'+re.escape(term)+r'(?!\w)',text,re.I)]
        ticker=symbol[:-3]
        if re.search(r'\$'+re.escape(ticker)+r'\b',text,re.I):terms.append('$'+ticker)
        # Standalone ticker needs domain context, not an ordinary English word.
        if ticker in ('BTC','ETH','USDT','BNB','XRP') and re.search(r'\b'+ticker+r'\b',text) and re.search(r'crypto|token|coin|stablecoin|blockchain|ETF',text,re.I):terms.append('TICKER_WITH_CRYPTO_CONTEXT')
        if terms:matches.append({'symbol':symbol,'reason':'EXPLICIT_NAME_OR_QUALIFIED_TICKER','terms':terms,'ambiguity':'POSSIBLE_ENTITY_MENTION_NOT_PRICE_IMPACT'})
    general=bool(re.search(r'\b(?:crypto(?:currency)?|blockchain|digital assets|stablecoins|market)\b',text,re.I))
    return matches,('ASSET_SPECIFIC' if matches else 'MARKET_GENERAL' if general else 'UNLINKED')

def understand(text):
    lang,confidence,method=language_of(text);links,scope=link_assets(text)
    event='GENERAL';importance=.25
    for name,pattern,weight in [('SECURITY',r'\bhack|exploit|breach|هک',.9),('REGULATION',r'\bSEC\b|regulat|lawsuit|قانون',.8),
        ('EXCHANGE',r'\blist(?:ing)?\b|delist|exchange',.65),('ETF',r'\bETF\b',.7),('NETWORK',r'upgrade|mainnet|fork',.6)]:
        if re.search(pattern,text,re.I):event=name;importance=weight;break
    return {'language':lang,'language_confidence':confidence,'language_method':method,'links':links,'scope':scope,
            'event_type':event,'importance':importance,'importance_authority':'DETERMINISTIC_RESEARCH_HEURISTIC',
            'version':UNDERSTANDING,'text_trust':'UNTRUSTED_DATA_NO_TOOL_OR_ORDER_AUTHORITY'}

class NewsStore:
    def __init__(self,root):
        self.root=Path(root);self.root.mkdir(parents=True,exist_ok=True)
        self.db=sqlite3.connect(self.root/'news.sqlite',timeout=30);self.db.row_factory=sqlite3.Row
        self.db.execute('PRAGMA journal_mode=WAL');self.db.execute('PRAGMA busy_timeout=30000')
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS news_documents(
          article_id TEXT PRIMARY KEY,canonical_url TEXT NOT NULL,title TEXT NOT NULL,source TEXT NOT NULL,
          published_at TEXT,first_observed_at TEXT NOT NULL,available_at TEXT,ingested_at TEXT NOT NULL,
          content_sha256 TEXT NOT NULL UNIQUE,raw_sha256 TEXT NOT NULL,pit_status TEXT NOT NULL,
          publication_kind TEXT NOT NULL,protocol TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS news_receipts(
          id INTEGER PRIMARY KEY,article_id TEXT NOT NULL,source TEXT NOT NULL,url TEXT NOT NULL,
          observed_at TEXT NOT NULL,raw_sha256 TEXT NOT NULL,legacy_key TEXT UNIQUE,
          UNIQUE(article_id,source,url,raw_sha256));
        CREATE TABLE IF NOT EXISTS news_understanding(
          article_id TEXT NOT NULL,version TEXT NOT NULL,processed_at TEXT NOT NULL,payload_json TEXT NOT NULL,
          PRIMARY KEY(article_id,version));
        CREATE TABLE IF NOT EXISTS news_sentiment(
          article_id TEXT NOT NULL,model_version TEXT NOT NULL,processed_at TEXT NOT NULL,
          status TEXT NOT NULL,payload_json TEXT NOT NULL,PRIMARY KEY(article_id,model_version,status));
        CREATE TABLE IF NOT EXISTS news_source_runs(
          id INTEGER PRIMARY KEY,source TEXT NOT NULL,started_at TEXT NOT NULL,finished_at TEXT NOT NULL,
          status TEXT NOT NULL,attempts INTEGER NOT NULL,new_articles INTEGER NOT NULL,duplicates INTEGER NOT NULL,
          invalid_articles INTEGER NOT NULL,entries_seen INTEGER NOT NULL,error_type TEXT,latency_seconds REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS news_model_runs(
          id INTEGER PRIMARY KEY,started_at TEXT NOT NULL,finished_at TEXT NOT NULL,payload_json TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS news_memory_refs(article_id TEXT PRIMARY KEY,event_hash TEXT NOT NULL,recorded_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS news_raw_payloads(sha256 TEXT PRIMARY KEY,payload TEXT NOT NULL);
        CREATE VIEW IF NOT EXISTS news_article_status AS
          SELECT d.*,json_extract(u.payload_json,'$.language') AS detected_language,
            COALESCE((SELECT s.status FROM news_sentiment s WHERE s.article_id=d.article_id
                ORDER BY (s.status='SCORED') DESC,s.processed_at DESC LIMIT 1),
              CASE WHEN u.article_id IS NULL THEN 'PENDING_UNDERSTANDING'
                WHEN json_extract(u.payload_json,'$.language')!='en' THEN 'LANGUAGE_UNSUPPORTED'
                ELSE 'PENDING_SENTIMENT' END) AS processing_status,
            (SELECT s.model_version FROM news_sentiment s WHERE s.article_id=d.article_id
                ORDER BY (s.status='SCORED') DESC,s.processed_at DESC LIMIT 1) AS model_version
          FROM news_documents d LEFT JOIN news_understanding u
            ON d.article_id=u.article_id AND u.version='ATLAS_NEWS_RULE_LINKING_V1';
        CREATE INDEX IF NOT EXISTS news_available ON news_documents(available_at);
        ''');self.db.commit()
    def __enter__(self):return self
    def __exit__(self,*_):self.close()
    def close(self):self.db.close()

    def ingest(self,*,url,title,source,published_at,observed_at,raw,legacy_key=None,publication_kind='PUBLISHER_TIMESTAMP'):
        """Insert immutable real headline evidence. Caller must supply actual source data."""
        title=normalize_content(title)
        if not title or len(title)>4000:raise ValueError('missing/oversized source title')
        url=canonical_url(url);published=aware(published_at);observed=aware(observed_at)
        if observed is None or observed>datetime.now(timezone.utc)+timedelta(minutes=5):raise ValueError('invalid actual receipt time')
        valid=published is not None and published<=observed+timedelta(minutes=5)
        available=max(published,observed).isoformat() if valid else None
        content=digest(title.casefold());raw_hash=digest(raw);article_id=digest(url)
        existing=self.db.execute('SELECT article_id FROM news_documents WHERE content_sha256=?',(content,)).fetchone()
        duplicate=existing is not None
        if existing:article_id=existing[0]
        elif self.db.execute('SELECT 1 FROM news_documents WHERE article_id=?',(article_id,)).fetchone():
            # A publisher edit at the same URL is another immutable version.
            article_id=digest(url+'|'+content)
        with self.db:
            self.db.execute('INSERT OR IGNORE INTO news_raw_payloads VALUES(?,?)',(raw_hash,raw))
            inserted=self.db.execute('''INSERT OR IGNORE INTO news_documents VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                (article_id,url,title,source,published.isoformat() if published else None,observed.isoformat(),available,now_utc(),
                 content,raw_hash,'VALID_LOCAL_RECEIPT' if valid else 'INVALID_PUBLICATION_TIMESTAMP',publication_kind,PROTOCOL))
            # A parallel ingestion may have won the UNIQUE content constraint
            # after the initial lookup. Always link the receipt to the committed
            # canonical document, never to a non-existent candidate ID.
            accepted=self.db.execute('SELECT article_id FROM news_documents WHERE content_sha256=?',(content,)).fetchone()
            if accepted is None:raise ValueError('conflicting immutable article identity')
            article_id=accepted[0];duplicate=inserted.rowcount==0
            self.db.execute('''INSERT OR IGNORE INTO news_receipts(article_id,source,url,observed_at,raw_sha256,legacy_key)
                VALUES(?,?,?,?,?,?)''',(article_id,source,url,observed.isoformat(),raw_hash,legacy_key))
        return {'article_id':article_id,'duplicate':duplicate,'pit_valid':valid}

    def migrate_legacy(self):
        if not self.db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='articles'").fetchone():return {'migrated':0,'duplicates':0,'invalid':0}
        # Capture raw legacy evidence additively, even after a schema upgrade;
        # the legacy table and its sentiment column are never rewritten.
        for row in self.db.execute('SELECT original_payload FROM articles').fetchall():
            with self.db:self.db.execute('INSERT OR IGNORE INTO news_raw_payloads VALUES(?,?)',(digest(row[0]),row[0]))
        rows=self.db.execute('''SELECT * FROM articles WHERE article_key NOT IN
            (SELECT legacy_key FROM news_receipts WHERE legacy_key IS NOT NULL)''').fetchall()
        counts={'migrated':0,'duplicates':0,'invalid':0}
        for row in rows:
            try:
                result=self.ingest(url=row['url'],title=row['title'],source=row['source'],published_at=row['published_at'],
                    observed_at=row['first_observed_at'],raw=row['original_payload'],legacy_key=row['article_key'],
                    publication_kind='PROVIDER_SEEN_TIME_NOT_PUBLICATION' if row['source']=='GDELT_DOC_2' else 'PUBLISHER_TIMESTAMP')
                counts['duplicates' if result['duplicate'] else 'migrated']+=1
            except (ValueError,TypeError):counts['invalid']+=1
        return counts

    def process(self,limit=500):
        rows=self.db.execute('''SELECT d.article_id,d.title FROM news_documents d LEFT JOIN news_understanding u
            ON d.article_id=u.article_id AND u.version=? WHERE u.article_id IS NULL ORDER BY d.first_observed_at LIMIT ?''',(UNDERSTANDING,int(limit))).fetchall()
        for row in rows:
            result=understand(row['title'])
            with self.db:self.db.execute('INSERT OR IGNORE INTO news_understanding VALUES(?,?,?,?)',
                (row['article_id'],UNDERSTANDING,now_utc(),canonical(result)))
        return {'processed':len(rows),'version':UNDERSTANDING}

    def evidence_at(self,symbol,asof,limit=100):
        if not re.fullmatch(r'[A-Z0-9]{2,24}TMN',symbol):raise ValueError('validated TMN asset required')
        instant=cutoff_time(asof);cutoff=instant.isoformat();result=[]
        rows=self.db.execute('''SELECT d.*,u.payload_json,u.processed_at AS linked_at FROM news_documents d
            JOIN news_understanding u ON d.article_id=u.article_id AND u.version=?
            WHERE d.available_at IS NOT NULL AND julianday(d.available_at)<=julianday(?)
              AND julianday(u.processed_at)<=julianday(?) ORDER BY d.available_at DESC''',(UNDERSTANDING,cutoff,cutoff)).fetchall()
        for row in rows:
            if digest(normalize_content(row['title']).casefold())!=row['content_sha256']:continue
            raw=self.db.execute('SELECT payload FROM news_raw_payloads WHERE sha256=?',(row['raw_sha256'],)).fetchone()
            if raw is None or digest(raw[0])!=row['raw_sha256']:continue
            publication=aware(row['published_at']);observed=aware(row['first_observed_at']);available=aware(row['available_at'])
            if (publication is None or observed is None or available is None or available<max(publication,observed)
                    or available>instant or aware(row['linked_at'])>instant):continue
            info=json.loads(row['payload_json']);matches=[x for x in info['links'] if x['symbol']==symbol]
            if not matches and info['scope']!='MARKET_GENERAL':continue
            scores=self.db.execute('''SELECT * FROM news_sentiment WHERE article_id=? AND status='SCORED'
                AND julianday(processed_at)<=julianday(?) ORDER BY processed_at DESC LIMIT 1''',(row['article_id'],cutoff)).fetchone()
            if scores and (aware(scores['processed_at'])>instant or not valid_score(json.loads(scores['payload_json']),row['content_sha256'])):scores=None
            receipt_sources=self.db.execute('''SELECT DISTINCT source FROM news_receipts WHERE article_id=?
                AND julianday(observed_at)<=julianday(?)''',(row['article_id'],cutoff)).fetchall()
            result.append({'article_id':row['article_id'],'content_sha256':row['content_sha256'],
                'source':row['source'],'sources':[x[0] for x in receipt_sources],
                'published_at':row['published_at'],'first_observed_at':row['first_observed_at'],
                'available_at':row['available_at'],'linked_at':row['linked_at'],
                'analysis_available_at':max(row['available_at'],row['linked_at'],scores['processed_at'] if scores else row['linked_at']),
                'sentiment':json.loads(scores['payload_json']) if scores else None,
                'model_version':scores['model_version'] if scores else None,
                'processing_version':UNDERSTANDING,'link_reasons':matches,'scope':info['scope'],
                'language':info['language'],'event_type':info['event_type'],'importance':info['importance'],
                'authority':'ADVISORY_MODEL_ESTIMATE_NO_ORDER_AUTHORITY'})
            if len(result)>=limit:break
        return result

    def source_state(self,cutoff,hours):
        """Coverage requires actual successful polling throughout the requested interval."""
        cut=cutoff_time(cutoff);start=cut-timedelta(hours=hours)
        rows=self.db.execute('''SELECT source,finished_at,status FROM news_source_runs
            WHERE julianday(finished_at)<=julianday(?) ORDER BY finished_at''',(cut.isoformat(),)).fetchall()
        latest={}
        for row in rows:latest[row['source']]=row
        healthy=[s for s,r in latest.items() if r['status']=='SUCCESS' and (cut-aware(r['finished_at'])).total_seconds()<=1800]
        covered=False
        for source in healthy:
            times=[aware(r['finished_at']) for r in rows if r['source']==source and r['status']=='SUCCESS']
            before=[t for t in times if t<=start]
            points=([max(before)] if before else [])+[t for t in times if t>start]+[cut]
            if before and all((b-a).total_seconds()<=1800 for a,b in zip(points,points[1:])):covered=True
        return {'healthy_sources':healthy,'coverage_complete':covered,
                'status':'SOURCE_UNAVAILABLE' if not healthy else 'COVERED' if covered else 'INSUFFICIENT_PIT_HISTORY'}

    def features_at(self,symbol,asof):
        cutoff=cutoff_time(asof);evidence=self.evidence_at(symbol,cutoff.isoformat(),limit=10000);features={};statuses={}
        for hours in WINDOWS:
            coverage=self.source_state(cutoff.isoformat(),hours);statuses[str(hours)]=coverage
            recent=[x for x in evidence if aware(x['available_at'])>cutoff-timedelta(hours=hours)]
            scored=[x for x in recent if x['sentiment'] is not None]
            features[f'news_count_{hours}h']=len(recent) if recent or coverage['coverage_complete'] else None
            weights=[x['sentiment']['confidence']*math.exp(-(cutoff-aware(x['available_at'])).total_seconds()/(hours*3600)) for x in scored]
            features[f'news_sentiment_{hours}h']=(sum(w*x['sentiment']['signed_score'] for w,x in zip(weights,scored))/sum(weights)) if weights and sum(weights)>0 else None
        recent=[x for x in evidence if aware(x['available_at'])>cutoff-timedelta(hours=24)]
        features['news_source_count_24h']=len({s for x in recent for s in x['sources']}) if recent else None
        features['news_importance_24h']=max((x['importance'] for x in recent),default=None)
        features['news_age_hours']=min(((cutoff-aware(x['available_at'])).total_seconds()/3600 for x in recent),default=None)
        a=features['news_sentiment_1h'];b=features['news_sentiment_6h'];features['news_sentiment_momentum']=a-b if a is not None and b is not None else None
        a=features['news_count_1h'];b=features['news_count_24h'];features['news_intensity_1h_vs_24h']=24*a/b if a is not None and b else None
        features['news_missing_mask']=int(any(v is None for v in features.values()) or
                                          any(not x['coverage_complete'] for x in statuses.values()))
        state=statuses['24']['status'];ready=state=='COVERED' and features['news_missing_mask']==0
        if state=='COVERED' and not recent:state='NO_NEW_RELEVANT_NEWS'
        return {'symbol':symbol,'cutoff':cutoff.isoformat(),'recipe_version':PROTOCOL,'features':features,
                'status':state,'ready':ready,'source_windows':statuses,'article_ids':[x['article_id'] for x in recent],
                'authority':'CHALLENGER_RESEARCH_AND_ADVISORY_ONLY'}

    def record_memory(self,symbol,asof,mode):
        from .atlas_context import ContextStore
        from .atlas_mode import ExecutionMode,require_mode
        require_mode(mode,permitted=(ExecutionMode.SHADOW,),operation='news.memory')
        evidence=self.evidence_at(symbol,asof,limit=20);recorded=0
        context=ContextStore(self.root,mode=mode)
        try:
            if not context.verify()['hash_chain_valid']:raise RuntimeError('context integrity failure')
            for item in evidence:
                if self.db.execute('SELECT 1 FROM news_memory_refs WHERE article_id=?',(item['article_id'],)).fetchone():continue
                event=context.record('NEWS_EVIDENCE',item['article_id'],{'symbol':symbol,'article_id':item['article_id'],
                    'available_at':item['available_at'],'analysis_available_at':item['analysis_available_at'],
                    'processing_version':item['processing_version'],'model_version':item['model_version'],
                    'sentiment_confidence':item['sentiment']['confidence'] if item['sentiment'] else None,
                    'sentiment_signed_score':item['sentiment']['signed_score'] if item['sentiment'] else None,
                    'authority':'ADVISORY_ONLY'},source_digest=item['content_sha256'])
                with self.db:self.db.execute('INSERT OR IGNORE INTO news_memory_refs VALUES(?,?,?)',(item['article_id'],event,now_utc()))
                recorded+=1
        finally:context.close()
        return {'recorded':recorded,'bounded_limit':20,'raw_news_text_in_memory':False}

    def summary(self):
        total=self.db.execute('SELECT COUNT(*) FROM news_documents').fetchone()[0]
        return {'articles':total,'receipts':self.db.execute('SELECT COUNT(*) FROM news_receipts').fetchone()[0],
            'understood':self.db.execute('SELECT COUNT(*) FROM news_understanding').fetchone()[0],
            'scored':self.db.execute("SELECT COUNT(DISTINCT article_id) FROM news_sentiment WHERE status='SCORED'").fetchone()[0],
            'pit_valid':self.db.execute('SELECT COUNT(*) FROM news_documents WHERE available_at IS NOT NULL').fetchone()[0],
            'protocol':PROTOCOL}


def sentiment_score(root,*,max_articles=250,batch_size=8,device='cpu',allow_download=False,model_path=None):
    """Pinned English FinBERT, batched and cached; failure never creates a score.

    The model card specifies CC-BY-NC-SA-4.0. Use here is local research only;
    no opinion about contest/commercial permission is inferred.
    """
    if not 1<=max_articles<=2000 or not 1<=batch_size<=64 or device not in ('cpu','cuda'):raise ValueError('invalid scoring controls')
    started=now_utc();version=MODEL_ID+'@'+MODEL_REVISION;report={'model_version':version,'model_license':'CC-BY-NC-SA-4.0',
        'authority':'RESEARCH_MODEL_ESTIMATE_ONLY','scored':0,'cached':0,'unsupported_language':0,'device':device}
    with NewsStore(root) as store:
        store.migrate_legacy();store.process()
        rows=store.db.execute('''SELECT d.article_id,d.title,u.payload_json FROM news_documents d JOIN news_understanding u
            ON d.article_id=u.article_id AND u.version=? ORDER BY d.first_observed_at''',(UNDERSTANDING,)).fetchall()
        pending=[]
        for row in rows:
            if json.loads(row['payload_json'])['language']!='en':report['unsupported_language']+=1;continue
            cached=store.db.execute("SELECT payload_json FROM news_sentiment WHERE article_id=? AND model_version=? AND status='SCORED'",(row['article_id'],version)).fetchone()
            if cached:
                if valid_score(json.loads(cached[0]),digest(normalize_content(row['title']).casefold())):report['cached']+=1
                else:report['invalid_cache']=report.get('invalid_cache',0)+1
            elif len(pending)<max_articles:pending.append(row)
        def save_failure(status,error_type):
            report.update(status=status,error_type=error_type)
            for row in pending:
                store.db.execute('INSERT OR IGNORE INTO news_sentiment VALUES(?,?,?,?,?)',
                    (row['article_id'],version,now_utc(),status,canonical({'error_type':error_type,'no_score_created':True})))
        if not pending:report['status']='CACHE_INTEGRITY_FAILURE' if report.get('invalid_cache') else 'NO_PENDING_ENGLISH_ARTICLES'
        else:
            try:
                import torch
                from transformers import AutoTokenizer,AutoModelForSequenceClassification
                from huggingface_hub import snapshot_download
                location=model_path or snapshot_download(MODEL_ID,revision=MODEL_REVISION,
                    cache_dir=str(Path(root)/'news_models'),local_files_only=not allow_download,
                    allow_patterns=['config.json','tokenizer_config.json','special_tokens_map.json','vocab.txt','model.safetensors','README.md'],token=False)
                manifest={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in Path(location).iterdir() if p.is_file()}
                if manifest.get('model.safetensors')!=SAFE_WEIGHTS_SHA256:raise ValueError('pinned safe model weights missing or hash mismatch')
                tokenizer=AutoTokenizer.from_pretrained(location,local_files_only=True,trust_remote_code=False)
                model=AutoModelForSequenceClassification.from_pretrained(location,local_files_only=True,trust_remote_code=False,use_safetensors=True)
                if device=='cuda' and not torch.cuda.is_available():report['device']='cpu'
                model=model.to(report['device']).eval();labels={int(k):str(v).lower() for k,v in model.config.id2label.items()}
                if set(labels.values())!={'positive','negative','neutral'}:raise ValueError('unsupported sentiment label contract')
                report['artifact_sha256']=manifest
                for start in range(0,len(pending),batch_size):
                    batch=pending[start:start+batch_size];inputs=tokenizer([r['title'] for r in batch],padding=True,truncation=True,max_length=256,return_tensors='pt').to(report['device'])
                    try:
                        with torch.inference_mode():probs=model(**inputs).logits.softmax(-1).cpu().tolist()
                    except torch.OutOfMemoryError:
                        model=model.to('cpu');report['device']='cpu'
                        with torch.inference_mode():probs=model(**inputs.to('cpu')).logits.softmax(-1).cpu().tolist()
                    for row,scores in zip(batch,probs):
                        values={labels[i]:float(v) for i,v in enumerate(scores)}
                        if not all(math.isfinite(x) and 0<=x<=1 for x in values.values()):raise ValueError('nonfinite sentiment score')
                        payload={'probabilities':values,'confidence':max(values.values()),'label':max(values,key=values.get),
                            'signed_score':values['positive']-values['negative'],'model_version':version,
                            'artifact_sha256':manifest,'input_sha256':digest(normalize_content(row['title']).casefold()),
                            'language':'en','authority':'MODEL_ESTIMATE_NOT_VERIFIED_FACT'}
                        with store.db:store.db.execute('INSERT OR IGNORE INTO news_sentiment VALUES(?,?,?,?,?)',
                            (row['article_id'],version,now_utc(),'SCORED',canonical(payload)))
                        report['scored']+=1
                report['status']='COMPLETED'
            except Exception as exc:save_failure('SENTIMENT_MODEL_UNAVAILABLE',type(exc).__name__)
        report['finished_at']=now_utc()
        with store.db:store.db.execute('INSERT INTO news_model_runs(started_at,finished_at,payload_json) VALUES(?,?,?)',
            (started,report['finished_at'],canonical(report)))
    return report
