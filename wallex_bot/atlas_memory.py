"""Stage 6: point-in-time, evidence-only FinMem-inspired memory retrieval.

Sources (concept ONLY; independently authored, no code copied):
  FinMem, Yu et al., arXiv:2311.13743, AAAI Symposium 2024;
  https://github.com/pipiku915/FinMem-LLM-StockTrading
  audited SOURCES.md: be814aa47970de9bf2fdd6a1d5a60ae5cf361b46, MIT.

The original FinMem paper uses layered recency/relevancy/importance ranking.
Atlas uses a deliberately simpler DOCUMENTED *product* of deterministic bounded
scores, not an official FinMem implementation. No embeddings, price prediction,
LLM output ranking or automatic execution authority are introduced.
"""
from __future__ import annotations

import datetime as dt
import math
import re

# Stable, deterministic configuration; not learned or optimized on strategy PnL.
PROTOCOL = 'ATLAS_PIT_MEMORY_RETRIEVAL_V1'
HALF_LIFE_HOURS = 24.0
CANDIDATE_CAP = 2000
KIND_IMPORTANCE = {
    'NEWS_EVIDENCE': 0.55,
    'RESEARCH_INCIDENT': 0.88,
    'GRAPH_DECISION': 0.70,
    'REVIEW_CANDIDATE': 0.48,
    'WATCH_CYCLE': 0.35,
}
PURPOSE_MATCH = {
    'watch': ('WATCH_CYCLE','RESEARCH_INCIDENT'),
    'agent-cycle': ('GRAPH_DECISION','RESEARCH_INCIDENT','NEWS_EVIDENCE'),
    'research': ('RESEARCH_INCIDENT','REVIEW_CANDIDATE','NEWS_EVIDENCE'),
    'audit': ('REVIEW_CANDIDATE','RESEARCH_INCIDENT'),
}
SYMBOL_PATTERN = re.compile(r'^[A-Z0-9]{2,24}$')


def utc_time(value=None):
    """Refuse naive/future as-of timestamps; never query future availability."""
    if value is None:
        return dt.datetime.now(dt.timezone.utc)
    if isinstance(value, str):
        try:
            value=dt.datetime.fromisoformat(value.replace('Z','+00:00'))
        except (ValueError,TypeError) as exc:
            raise ValueError('Invalid ISO-8601 as_of_utc') from exc
    if not isinstance(value,dt.datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError('PIT retrieval requires an aware datetime')
    value=value.astimezone(dt.timezone.utc)
    if value>dt.datetime.now(dt.timezone.utc)+dt.timedelta(seconds=1):
        raise ValueError('Cannot retrieve operational memory with a future as_of')
    return value


def _number(value):
    if type(value) not in (float,int) or not math.isfinite(float(value)):
        return None
    return float(value)


def importance(kind,payload):
    """Bounded metadata importance; headlines/LLM text never influence scoring."""
    score=KIND_IMPORTANCE.get(kind,0.1)
    for name,scale,maximum in (
        ('failed_chunks',0.025,0.14),
        ('veto_count',0.04,0.14),
        ('error_count',0.025,0.12),
        ('paper_abs_pnl_tmn',0.0000001,0.12),
        ('paper_drawdown_pct',0.018,0.12),
    ):
        n=_number(payload.get(name))
        if n is not None and n>0:score+=min(maximum,n*scale)
    actions=payload.get('shadow_actions')
    if isinstance(actions,list):
        codes={x for x in actions if isinstance(x,str) and
               re.fullmatch(r'[A-Z][A-Z_]{1,47}',x)}
        if codes.intersection({'REJECTED','RISK_VETO','BLOCKED','CIRCUIT_BREAKER'}):
            score+=0.1
    return round(min(1.0,max(0.05,score)),6)


def relevance(kind,payload,*,symbol=None,purpose='watch'):
    if purpose not in PURPOSE_MATCH:raise ValueError('Unsupported memory purpose')
    if symbol is not None and (not isinstance(symbol,str) or not SYMBOL_PATTERN.fullmatch(symbol)):
        raise ValueError('Invalid uppercase symbol filter')
    result=0.6 if kind in PURPOSE_MATCH[purpose] else 0.35
    event_symbol=payload.get('symbol')
    # Only an exact structured symbol field counts, never arbitrary headlines or URLs.
    if symbol is not None:
        if isinstance(event_symbol,str) and SYMBOL_PATTERN.fullmatch(event_symbol):
            result*=1.0 if event_symbol==symbol else 0.20
        else:result*=0.65
    return round(result,6)


def score_event(event,*,as_of_utc, symbol=None, purpose='watch'):
    """Return None if not observable by cutoff; score = recency * importance * relevance."""
    cutoff=utc_time(as_of_utc)
    observed=utc_time(event['observed_at_utc'])
    age=(cutoff-observed).total_seconds()
    if age<0:return None
    hours=age/3600
    layer='HOT' if hours<=6 else 'WARM' if hours<=72 else 'COLD'
    recency=math.exp(-math.log(2)*hours/HALF_LIFE_HOURS)
    imp=importance(event['kind'],event['payload'])
    rel=relevance(event['kind'],event['payload'],symbol=symbol,purpose=purpose)
    return {'score':round(recency*imp*rel,12), 'layer':layer,
            'factors':{'recency':round(recency,8),'importance':imp,'relevance':rel},
            'age_hours':round(hours,5)}


def compact_metadata(event):
    """No raw source descriptions, news text, model instructions or credentials."""
    p=event['payload']
    out={}
    for k in ('cycles_completed','downloaded_chunks','failed_chunks','veto_count',
              'error_count','observed_markets','recorded_news'):
        n=_number(p.get(k))
        if n is not None and n>=0:out[k]=int(n)
    symbol=p.get('symbol')
    if isinstance(symbol,str) and SYMBOL_PATTERN.fullmatch(symbol):out['symbol']=symbol
    for name in ('article_id','processing_version','model_version','available_at','analysis_available_at'):
        value=p.get(name)
        if isinstance(value,str) and re.fullmatch(r'[A-Za-z0-9_@:/+.\-]{1,128}',value):out[name]=value
    e=p.get('error_type')
    if isinstance(e,str) and re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,63}',e):out['error_type']=e
    actions=p.get('shadow_actions')
    if isinstance(actions,list):
        out['shadow_action_codes']=[a for a in actions[:12] if isinstance(a,str) and
                                    re.fullmatch(r'[A-Z][A-Z_]{1,47}',a)]
    return out


def rank_rows(rows,*,as_of_utc=None,symbol=None,purpose='watch',limit=12):
    """Pure deterministic ranker over verified, *already persisted* operational events."""
    cutoff=utc_time(as_of_utc)
    if not isinstance(limit,int) or not 1<=limit<=40:raise ValueError('Memory selection limit must be 1..40')
    if purpose not in PURPOSE_MATCH:raise ValueError('Unknown memory purpose')
    result=[]
    for e in rows:
        value=score_event(e,as_of_utc=cutoff,symbol=symbol,purpose=purpose)
        if value is None:continue
        result.append({'observed_at_utc':e['observed_at_utc'],'kind':e['kind'],
                       'event_hash':e['event_hash'],'source_sha256':e['source_sha256'],
                       'metrics':compact_metadata(e),**value})
    result.sort(key=lambda item:(-item['score'],
                   -dt.datetime.fromisoformat(item['observed_at_utc'].replace('Z','+00:00')).timestamp(),
                   item['event_hash']))
    return result[:limit]


class ResearchMemory:
    """M6 additive layers in the existing ContextStore, not a replacement.

    FinMem-inspired deterministic factors reuse score_event. Event creation,
    observation AND availability must precede retrieval cutoff. No lesson can
    mutate a model or risk policy. References only; no headline instructions.
    """
    TYPES=frozenset({'RECENT_MARKET_CONTEXT','NEWS_EVENT','PAST_FORECAST','MATURED_FORECAST_OUTCOME',
        'DECISION_RISK_VETO','RESEARCH_LESSON','STRATEGY_PERFORMANCE_EVIDENCE'})
    def __init__(self,root,mode='SHADOW'):
        from .atlas_context import ContextStore
        from .atlas_mode import ExecutionMode
        self.store=ContextStore(root,mode=mode);self.db=self.store.db
        if self.store.mode is ExecutionMode.SHADOW:
            self.db.execute('''CREATE TABLE IF NOT EXISTS research_memory_v6(
                seq INTEGER PRIMARY KEY, event_id TEXT UNIQUE NOT NULL,symbol TEXT NOT NULL,
                observed REAL NOT NULL, available REAL NOT NULL, created REAL NOT NULL,
                memory_type TEXT NOT NULL,importance REAL NOT NULL,source_hash TEXT NOT NULL,
                evaluation_status TEXT NOT NULL,payload TEXT NOT NULL,previous_hash TEXT NOT NULL,event_hash TEXT NOT NULL)''')
            self.db.commit()
    def exists(self):
        return self.db is not None and self.db.execute("SELECT 1 FROM sqlite_master WHERE name='research_memory_v6'").fetchone() is not None
    def record(self,event_id,symbol,observed,available,memory_type,source_hash,payload,evaluation_status='OBSERVED_EVIDENCE_ONLY'):
        import time,json
        from .atlas_context import _clean,_json,_sha
        self.store._require_writable('ResearchMemory.record')
        if memory_type not in self.TYPES or not SYMBOL_PATTERN.fullmatch(symbol) or not re.fullmatch('[0-9a-f]{64}',source_hash):raise ValueError('INVALID_MEMORY_CONTRACT')
        created=time.time();observed=float(observed);available=float(available)
        if not all(math.isfinite(x) for x in (observed,available)) or observed>created or available<observed or available>created:raise ValueError('INVALID_MEMORY_AVAILABILITY')
        message=_json(_clean(payload));imp=importance('GRAPH_DECISION' if memory_type=='DECISION_RISK_VETO' else 'NEWS_EVIDENCE',{})
        self.db.execute('BEGIN IMMEDIATE')
        try:
            existing=self.db.execute('SELECT source_hash,payload,event_hash FROM research_memory_v6 WHERE event_id=?',(event_id,)).fetchone()
            if existing:
                if existing[:2]!=(source_hash,message):raise ValueError('MEMORY_IDEMPOTENCY_CONFLICT')
                self.db.commit();return existing[2]
            if not self.verify():raise RuntimeError('RESEARCH_MEMORY_CHAIN_INVALID')
            prev=self.db.execute('SELECT event_hash FROM research_memory_v6 ORDER BY seq DESC LIMIT 1').fetchone()
            previous=prev[0] if prev else 'GENESIS'
            fields=[event_id,symbol,observed,available,created,memory_type,imp,source_hash,evaluation_status,message,previous]
            sha=_sha(_json(fields))
            self.db.execute('INSERT INTO research_memory_v6(event_id,symbol,observed,available,created,memory_type,importance,source_hash,evaluation_status,payload,previous_hash,event_hash) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',(*fields,sha))
            self.db.commit();return sha
        except Exception:self.db.rollback();raise
    def verify(self):
        from .atlas_context import _sha,_json
        if not self.exists():return True
        previous='GENESIS'
        for row in self.db.execute('SELECT event_id,symbol,observed,available,created,memory_type,importance,source_hash,evaluation_status,payload,previous_hash,event_hash FROM research_memory_v6 ORDER BY seq'):
            if row[-2]!=previous or _sha(_json(list(row[:-1])))!=row[-1]:return False
            previous=row[-1]
        return True
    def retrieve(self,symbol,asof,limit=12):
        import json
        cutoff=utc_time(asof);epoch=cutoff.timestamp()
        if not 1<=limit<=40:raise ValueError('BOUNDED_MEMORY_QUERY_REQUIRED')
        if not self.exists():return []
        if not self.verify():raise RuntimeError('RESEARCH_MEMORY_CHAIN_INVALID')
        rows=self.db.execute('SELECT event_id,symbol,observed,available,created,memory_type,importance,source_hash,evaluation_status,payload,event_hash FROM research_memory_v6 WHERE observed<=? AND available<=? AND created<=? ORDER BY seq DESC LIMIT 2000',(epoch,epoch,epoch)).fetchall()
        result=[]
        for key,sym,obs,avail,created,kind,imp,source,status,payload,sha in rows:
            event={'observed_at_utc':dt.datetime.fromtimestamp(created,dt.timezone.utc).isoformat(),'kind':'GRAPH_DECISION','payload':{'symbol':sym}}
            score=score_event(event,as_of_utc=cutoff,symbol=symbol,purpose='research')
            result.append({'event_id':key,'symbol':sym,'observation_time':obs,'availability_time':avail,'created_at':created,
                'memory_type':kind,'importance':imp,'recency':score['factors']['recency'],'relevance':score['factors']['relevance'],
                'source_hash':source,'evaluation_status':status,'event_hash':sha,'payload':json.loads(payload),
                'score':imp*score['factors']['recency']*score['factors']['relevance']})
        return sorted(result,key=lambda r:(-r['score'],r['event_id']))[:limit]
    def status(self):
        return {'chain_valid':self.verify(),'layers':dict(self.db.execute('SELECT memory_type,count(*) FROM research_memory_v6 GROUP BY memory_type')) if self.exists() else {},
            'authority':'EVIDENCE_ONLY_NO_RISK_OR_MODEL_MUTATION','time_policy':'observation AND availability AND actual creation <= cutoff'}
    def close(self):self.store.close()
