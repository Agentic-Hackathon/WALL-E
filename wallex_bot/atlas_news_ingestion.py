"""Bounded public news GETs with persistent source receipts and exact dedup.

Uses the existing Atlas publisher allowlist and date parsers. No article URLs
are fetched: feed titles are the explicitly recorded analyzable content scope.
"""
from __future__ import annotations
import json
import time
import xml.etree.ElementTree as ET
from datetime import datetime,timezone,timedelta
import requests
from .atlas_news_pipeline import NewsStore,now_utc,aware

def fetch_public(url,*,params=None,retries=1,timeout=(4,8),backoff=.5):
    if not 0<=retries<=3:raise ValueError('retry bound is 0..3')
    started=time.monotonic();last=None
    for attempt in range(retries+1):
        try:
            with requests.get(url,params=params,timeout=timeout,stream=True,
                    headers={'User-Agent':'WallexAtlasResearch/4.0','Accept':'application/rss+xml, application/json, application/xml'}) as response:
                response.raise_for_status();pieces=[];size=0
                for chunk in response.iter_content(65536):
                    size+=len(chunk)
                    if size>3_000_000:raise ValueError('oversized source response')
                    pieces.append(chunk)
                return b''.join(pieces),{'attempts':attempt+1,'latency_seconds':time.monotonic()-started,'error_type':None}
        except (requests.RequestException,ValueError) as exc:
            last=type(exc).__name__
            if attempt<retries:time.sleep(min(backoff*2**attempt,2))
    return None,{'attempts':retries+1,'latency_seconds':time.monotonic()-started,'error_type':last}

def parse_rss(raw):
    from .atlas_news import _rss_date
    root=ET.fromstring(raw);entries=root.findall('.//item') or root.findall('.//{http://www.w3.org/2005/Atom}entry')
    output=[]
    for entry in entries:
        title=entry.findtext('title') or entry.findtext('{http://www.w3.org/2005/Atom}title') or ''
        link=entry.findtext('link') or ''
        if not link:
            element=entry.find('{http://www.w3.org/2005/Atom}link');link=element.get('href','') if element is not None else ''
        pub=_rss_date(entry.findtext('pubDate')) or _rss_date(entry.findtext('{http://www.w3.org/2005/Atom}published')) or _rss_date(entry.findtext('{http://www.w3.org/2005/Atom}updated'))
        output.append({'url':link,'title':title,'published_at':pub,'raw':ET.tostring(entry,encoding='unicode')})
    return output

def _harvest(lake,*,hours=48,queries=None,rss_only=False,retries=1,score_sentiment=True,source_budget=6):
    from .atlas_news import API,RSS_FEEDS,iso_utc
    if not 1<=hours<=72:raise ValueError('news window must be 1..72 hours')
    receipts=[]
    with NewsStore(lake.root) as store:
        before=store.summary();migration=store.migrate_legacy()
        sources=[]
        if not rss_only:
            for query in (queries or ['(bitcoin OR ethereum OR cryptocurrency OR crypto)'])[:3]:
                now=datetime.now(timezone.utc)
                sources.append(('GDELT_DOC_2',API,{'query':query,'mode':'artlist','format':'json','sort':'datedesc','maxrecords':250,
                    'startdatetime':(now-timedelta(hours=hours)).strftime('%Y%m%d%H%M%S'),'enddatetime':now.strftime('%Y%m%d%H%M%S')}))
        # Existing publisher feeds are a dependable fallback even when GDELT
        # returns duplicates rather than genuinely new items.
        sources.extend((name,url,None) for name,url in RSS_FEEDS.items())
        previous_source_start=0.
        for source,url,params in sources[:source_budget]:
            time.sleep(max(0,.4-(time.monotonic()-previous_source_start)));previous_source_start=time.monotonic()
            started=now_utc();raw,transport=fetch_public(url,params=params,retries=retries)
            record={'source':source,'started_at':started,'status':'SUCCESS','new_articles':0,'duplicates':0,'invalid_articles':0,'entries_seen':0,**transport}
            if raw is None:record['status']='FAILED'
            else:
                observed=now_utc()
                try:
                    if source=='GDELT_DOC_2':
                        body=json.loads(raw)
                        if not isinstance(body,dict) or not isinstance(body.get('articles'),list):raise ValueError('invalid GDELT articles list')
                        entries=[{'url':row.get('url',''),'title':row.get('title',''),'published_at':iso_utc(row.get('seendate')),'raw':json.dumps(row,sort_keys=True)} for row in body['articles']]
                    else:entries=parse_rss(raw)
                    record['entries_seen']=len(entries)
                    for row in entries:
                        publication=aware(row['published_at']);obs=aware(observed)
                        if publication is None or publication<obs-timedelta(hours=hours) or publication>obs+timedelta(minutes=5):record['invalid_articles']+=1;continue
                        try:
                            result=store.ingest(**row,source=source,observed_at=observed,
                                publication_kind='PROVIDER_SEEN_TIME_NOT_PUBLICATION' if source=='GDELT_DOC_2' else 'PUBLISHER_TIMESTAMP')
                            record['duplicates' if result['duplicate'] else 'new_articles']+=1
                        except (ValueError,TypeError):record['invalid_articles']+=1
                except (ValueError,TypeError,ET.ParseError) as exc:record['status']='FAILED';record['error_type']=type(exc).__name__
            record['finished_at']=now_utc()
            with store.db:store.db.execute('''INSERT INTO news_source_runs(source,started_at,finished_at,status,attempts,
                new_articles,duplicates,invalid_articles,entries_seen,error_type,latency_seconds) VALUES(?,?,?,?,?,?,?,?,?,?,?)''',
                tuple(record[key] for key in ('source','started_at','finished_at','status','attempts','new_articles','duplicates','invalid_articles','entries_seen','error_type','latency_seconds')))
            receipts.append(record)
        processing=store.process();after=store.summary()
    # After the explicitly requested first download, Watch can process pending
    # English titles using that pinned local model. This never downloads weights
    # during startup and never copies a score into the legacy operational veto.
    from .atlas_news_pipeline import sentiment_score,MODEL_REVISION
    from pathlib import Path
    model_root=Path(lake.root)/'news_models'/'models--ProsusAI--finbert'/'snapshots'/MODEL_REVISION
    scoring=(sentiment_score(lake.root,max_articles=32,device='cpu') if (model_root/'model.safetensors').is_file() else {'status':'SENTIMENT_MODEL_UNAVAILABLE','scored':0}) if score_sentiment else {'status':'SENTIMENT_LICENSE_OR_PROFILE_GUARD','scored':0}
    with NewsStore(lake.root) as store:after=store.summary()
    return {'protocol':'ATLAS_NEWS_INGESTION_V1','before':before,'migration':migration,'after':after,'source_runs':receipts,
            'fetched_articles_count_attempted':sum(r['new_articles'] for r in receipts),
            'duplicates':sum(r['duplicates'] for r in receipts),'processing':processing,'sentiment':scoring,
            'content_scope':'PUBLISHER_FEED_HEADLINE_ONLY','errors':[r for r in receipts if r['status']!='SUCCESS']}


def harvest(lake,*,hours=48,queries=None,rss_only=False,retries=1,score_sentiment=True,source_budget=6,min_interval_seconds=0):
    """M8 shared SQLite lease and persistent polling cursor, never key access.

    Legacy explicit research CLI retains its default sentiment behavior. New
    competition-facing startup passes score_sentiment=False until licensed.
    """
    import uuid
    if not 1<=source_budget<=6 or not 0<=min_interval_seconds<=3600:raise ValueError('INVALID_NEWS_SYNC_BUDGET')
    owner=uuid.uuid4().hex
    with NewsStore(lake.root) as store:
        store.db.executescript('''CREATE TABLE IF NOT EXISTS news_sync_lease_v8(name TEXT PRIMARY KEY,owner TEXT,expires REAL);
            CREATE TABLE IF NOT EXISTS news_sync_cursor_v8(name TEXT PRIMARY KEY,finished REAL,result TEXT);''');store.db.commit()
        store.db.execute('BEGIN IMMEDIATE')
        try:
            lease=store.db.execute("SELECT owner,expires FROM news_sync_lease_v8 WHERE name='public-news'").fetchone()
            cursor=store.db.execute("SELECT finished,result FROM news_sync_cursor_v8 WHERE name='public-news'").fetchone()
            if lease and lease[1]>time.time():store.db.rollback();return {'status':'NEWS_LEASE_HELD_NO_DUPLICATE_REQUEST','source_runs':[],'errors':[]}
            if cursor and time.time()-cursor[0]<min_interval_seconds:
                store.db.rollback();return {'status':'NEWS_POLL_INTERVAL_CACHE_HIT','source_runs':[],'errors':[],'last_finished':cursor[0]}
            store.db.execute("INSERT OR REPLACE INTO news_sync_lease_v8 VALUES('public-news',?,?)",(owner,time.time()+300));store.db.commit()
        except Exception:store.db.rollback();raise
    try:
        result=_harvest(lake,hours=hours,queries=queries,rss_only=rss_only,retries=retries,score_sentiment=score_sentiment,source_budget=source_budget)
        with NewsStore(lake.root) as store:
            with store.db:store.db.execute("INSERT OR REPLACE INTO news_sync_cursor_v8 VALUES('public-news',?,?)",(time.time(),json.dumps(result,sort_keys=True)))
        return result
    finally:
        with NewsStore(lake.root) as store:
            with store.db:store.db.execute("DELETE FROM news_sync_lease_v8 WHERE name='public-news' AND owner=?",(owner,))
