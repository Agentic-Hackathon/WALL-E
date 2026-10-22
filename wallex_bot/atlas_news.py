"""Point-in-time news archive. Never backfill presumed availability before observation."""
from __future__ import annotations
import os, json, time, hashlib, sqlite3, xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from datetime import datetime,timezone,timedelta
from pathlib import Path
import requests

API='https://api.gdeltproject.org/api/v2/doc/doc'

def iso_utc(raw):
    if not raw:return None
    if isinstance(raw,int):return datetime.fromtimestamp(raw,timezone.utc).isoformat()
    s=str(raw).strip()
    for fmt in ('%Y%m%dT%H%M%SZ','%Y%m%d%H%M%S'):
        try:return datetime.strptime(s,fmt).replace(tzinfo=timezone.utc).isoformat()
        except ValueError:pass
    try:
        out=datetime.fromisoformat(s.replace('Z','+00:00'))
        if out.tzinfo is None:return None
        return out.astimezone(timezone.utc).isoformat()
    except ValueError:return None


def _open_db(lake):
    db=sqlite3.connect(Path(lake.root)/'news.sqlite')
    db.execute('''CREATE TABLE IF NOT EXISTS articles (
        article_key TEXT PRIMARY KEY, url TEXT NOT NULL, title TEXT NOT NULL,
        source TEXT NOT NULL, published_at TEXT, first_observed_at TEXT NOT NULL,
        available_at TEXT NOT NULL, original_payload TEXT NOT NULL, sentiment TEXT)''')
    db.commit();return db


# Named publisher feeds, not arbitrary URLs supplied by outside model output.
RSS_FEEDS = {
    'COINDESK_RSS':'https://www.coindesk.com/arc/outboundfeeds/rss/',
    'COINTELEGRAPH_RSS':'https://cointelegraph.com/rss',
    'THEBLOCK_RSS':'https://www.theblock.co/rss.xml',
}

def _rss_date(raw):
    if not raw:return None
    try:
        d=parsedate_to_datetime(raw)
        if d.tzinfo is None:return None
        return d.astimezone(timezone.utc).isoformat()
    except (TypeError, ValueError, IndexError, OverflowError):
        return iso_utc(raw)

def harvest_rss(lake, hours=48):
    """Fallback to genuine, timestamped publisher RSS; never retrospective leakage."""
    if not 1<=hours<=72:raise ValueError('RSS window must be 1..72 hours')
    db=_open_db(lake)
    errors=[];inserted=0;skipped=0;feed_receipts=[]
    try:
        for source,url in RSS_FEEDS.items():
            receipt={'source':source,'entries_seen':0,'accepted':0,'skipped_missing_fields':0,'skipped_old_or_future':0}
            try:
                r=requests.get(url,timeout=(6,12),headers={'User-Agent':'WallexHackathonResearch/3.1'})
                r.raise_for_status()
                if len(r.content)>3_000_000:raise ValueError('Oversize RSS feed; rejected')
                root=ET.fromstring(r.content)
                # Only publishers' actual RSS/Atom article nodes.
                entries=root.findall('.//item')
                if not entries:
                    entries=root.findall('.//{http://www.w3.org/2005/Atom}entry')
                receipt['entries_seen']=len(entries)
                for e in entries:
                    title=(e.findtext('title') or e.findtext('{http://www.w3.org/2005/Atom}title') or '').strip()
                    link=(e.findtext('link') or '').strip()
                    if not link:
                        elt=e.find('{http://www.w3.org/2005/Atom}link')
                        link=(elt.get('href') if elt is not None else '') or ''
                    published=(_rss_date(e.findtext('pubDate')) or
                         _rss_date(e.findtext('{http://www.w3.org/2005/Atom}published')) or
                         _rss_date(e.findtext('{http://www.w3.org/2005/Atom}updated')))
                    now=datetime.now(timezone.utc)
                    if not title or not link.startswith('https://') or not published:
                        skipped+=1;receipt['skipped_missing_fields']+=1;continue
                    dt=datetime.fromisoformat(published)
                    # Reject future-dated or old publications rather than inventing a timestamp.
                    if dt>now+timedelta(minutes=5) or now-dt>timedelta(hours=hours):
                        skipped+=1;receipt['skipped_old_or_future']+=1;continue
                    seen_at=now.isoformat()
                    available=max(published,seen_at)
                    article_key=hashlib.sha256(link.encode('utf8')).hexdigest()
                    original=json.dumps({'url':link,'title':title,'publication':published,
                        'source_feed':url},sort_keys=True,ensure_ascii=False)
                    with db:
                        cursor=db.execute("INSERT OR IGNORE INTO articles "
                            "(article_key,url,title,source,published_at,first_observed_at, "
                            "available_at,original_payload) VALUES (?,?,?,?,?,?,?,?)",
                            (article_key,link,title,source,published,seen_at,available,original))
                        inserted+=cursor.rowcount
                        receipt['accepted']+=1
            except (requests.RequestException,ValueError,ET.ParseError) as e:
                errors.append({'source':source,'error_type':type(e).__name__})
                receipt['error_type']=type(e).__name__
            finally:
                feed_receipts.append(receipt)
    finally:db.close()
    return {'rss_inserted_articles':inserted,'rss_skipped':skipped,
            'rss_sources_total':len(RSS_FEEDS),'rss_errors':errors,
            'feed_receipts':feed_receipts,
            'leakage_control':'Article available from first successful observed_at, never retroactively'}


def harvest_news(lake,queries=None,hours=48):
    if not 1<=hours<=72:raise ValueError('news harvest 1..72h')
    queries=queries or ['(bitcoin OR ethereum OR cryptocurrency OR crypto)']
    db=_open_db(lake); got=0;skipped=0;failures=[]
    try:
        for q in queries:
            now=datetime.now(timezone.utc)
            begin=now-timedelta(hours=hours)
            params={'query':q,'mode':'artlist','format':'json','sort':'datedesc','maxrecords':250,
                    'startdatetime':begin.strftime('%Y%m%d%H%M%S'),
                    'enddatetime':now.strftime('%Y%m%d%H%M%S')}
            try:
                response=requests.get(API,params=params,timeout=(5,12),headers={'User-Agent':'WallexHackathonResearch/3.0'})
                response.raise_for_status();body=response.json()
                if not isinstance(body,dict) or not isinstance(body.get('articles'),list):
                    raise ValueError('Invalid GDELT articles response')
                observed=datetime.now(timezone.utc).isoformat()
                for row in body['articles']:
                    url=str(row.get('url',''));title=str(row.get('title',''))
                    if not url.startswith('http') or not title:skipped+=1;continue
                    publication=iso_utc(row.get('seendate'))
                    if not publication:skipped+=1;continue
                    # Conservative availability: first time OUR pipeline saw the article.
                    # Historical backfill NEVER becomes a historical feature retroactively.
                    available=max(publication,observed)
                    key=hashlib.sha256(url.encode('utf-8')).hexdigest()
                    raw=json.dumps(row,ensure_ascii=False,sort_keys=True)
                    db.execute('INSERT OR IGNORE INTO articles(article_key,url,title,source,published_at,first_observed_at,available_at,original_payload) VALUES(?,?,?,?,?,?,?,?)',
                              (key,url,title,'GDELT_DOC_2',publication,observed,available,raw))
                    got+=1
                db.commit()
            except (requests.RequestException,ValueError) as exc:
                failures.append({'query':q,'error':type(exc).__name__+': '+str(exc)[:180]})
    finally:db.close()
    rss={'rss_skipped':'not needed'}
    if got==0:
        rss=harvest_rss(lake,hours=hours)
    return {'fetched_articles_count_attempted':got,'skipped':skipped,'errors':failures,
            'rss_fallback':rss,
            'point_in_time_rule':'event is available no earlier than first_observed_at'}


def news_known_at(lake,asof_iso,query_token=None):
    cutoff=iso_utc(asof_iso)
    if cutoff is None:raise ValueError('Need offset-aware asof time')
    db=_open_db(lake)
    try:
        rows=db.execute('SELECT title,url,published_at,first_observed_at,available_at,sentiment FROM articles WHERE available_at<=? ORDER BY available_at DESC LIMIT 500',(cutoff,)).fetchall()
    finally:db.close()
    if query_token:rows=[x for x in rows if query_token.lower() in x[0].lower()]
    return [{'title':x[0],'url':x[1],'published_at':x[2],'observed_at':x[3],
             'available_at':x[4],'sentiment':json.loads(x[5]) if x[5] else None} for x in rows]


def finbert_score(lake,max_articles=250):
    # Optional transformer inference; WEIGHTS LICENSE must be reviewed before competition/commercial use.
    try:from transformers import pipeline
    except ImportError as e:raise RuntimeError('Install transformers and torch for FinBERT scoring') from e
    db=_open_db(lake)
    try:
        rows=db.execute('SELECT article_key,title FROM articles WHERE sentiment IS NULL LIMIT ?', (int(max_articles),)).fetchall()
        if not rows:return {'scored':0}
        pipe=pipeline('text-classification',model='ProsusAI/finbert',top_k=None,
                      device=0 if __import__('torch').cuda.is_available() else -1)
        for k,title in rows:
            pred=pipe(title,truncation=True,max_length=256)
            if pred and isinstance(pred[0],list):pred=pred[0]
            with db:db.execute('UPDATE articles SET sentiment=? WHERE article_key=?',
                               (json.dumps(pred),k))
        return {'scored':len(rows),'model':'ProsusAI/finbert',
                'warning':'Text sentiment != validated trading forecast; review model-weight license.'}
    finally:db.close()
