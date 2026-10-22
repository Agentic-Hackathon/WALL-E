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
    'RESEARCH_INCIDENT': 0.88,
    'GRAPH_DECISION': 0.70,
    'REVIEW_CANDIDATE': 0.48,
    'WATCH_CYCLE': 0.35,
}
PURPOSE_MATCH = {
    'watch': ('WATCH_CYCLE','RESEARCH_INCIDENT'),
    'agent-cycle': ('GRAPH_DECISION','RESEARCH_INCIDENT'),
    'research': ('RESEARCH_INCIDENT','REVIEW_CANDIDATE'),
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
