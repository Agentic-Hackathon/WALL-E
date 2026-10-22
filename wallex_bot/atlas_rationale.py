"""Stage 7 — advisory-only LLM rationale with cryptographic, read-only replay cache.

Conceptual provenance: TradingAgents (TauricResearch/TradingAgents,
commit e8f5503e9b86d5c2710b0c76b1f686703968c9df, Apache-2.0),
see third_party/SOURCES.md. Entire implementation independently written;
NO external code has been copied. This is NEVER a trading policy or risk gate.

The LLM sees bounded structured facts, not news text, tools, secrets or API keys.
No synthetic market data, market sentiment or fills are created on failure.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
import os
import re
import sqlite3
import urllib.error
import urllib.request
from pathlib import Path

from .atlas_mode import ExecutionMode,require_mode

PROTOCOL = 'ATLAS_LLM_ADVISORY_ONLY_V1'
GENERATION_INSTRUCTION = (
    'You are a read-only explanation assistant for a spot TMN cryptocurrency '
    'research/shadow system. Write at most three short sentences in Persian. '
    'Only explain the GIVEN structured observations and hard-coded risk vetoes. '
    'Do not assert a trade has been executed. Do not infer news impact from '
    'article counts. Do not invent prices, expected returns, fills, facts or fees. '
    'Never recommend bypassing risk rules or issuing orders. '
    'The decision and risk gate are immutable and outside your control.'
)


def canonical(obj):
    return json.dumps(obj,sort_keys=True,ensure_ascii=False,allow_nan=False,separators=(',',':'))


def sha(raw):
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()


def _num(obj):
    try:
        if isinstance(obj,bool) or obj is None:return None
        x=float(obj)
        return round(x,10) if math.isfinite(x) else None
    except (TypeError,ValueError,OverflowError):return None


def _safe_code(text,limit=70):
    if not isinstance(text,str):return None
    text=text[:limit]
    return text if len(text)<=limit and re.fullmatch(r'[A-Za-z0-9_\-\.]{1,70}',text) else None


def _safe_model(text):
    return (text if isinstance(text,str) and re.fullmatch(r'[A-Za-z0-9._:/-]{1,100}',text)
            else None)


def structured_evidence(state):
    """A narrow, deterministic copy of facts already in the trusted graph.

    Never forward a news headline, URL, tool instruction, account information,
    opaque user text or arbitrary state key to an LLM.
    """
    symbol=_safe_code(state.get('symbol'))
    if not symbol or not symbol.endswith('TMN'):
        raise ValueError('Only a validated spot TMN symbol may be explained')
    prediction=state.get('prediction') or {}
    quantiles=prediction.get('quantile_log_returns') or {}
    observations=state.get('observations') or {}
    book=observations.get('book') or {}
    technical=state.get('technical') or {}
    news=state.get('news') or {}
    codes=state.get('veto_reasons') or []
    # Only deterministic machine-readable veto codes enter the prompt.
    if not isinstance(codes,(tuple,list)):raise ValueError('Risk veto reasons must be structured')
    veto=sorted(set(x for x in (_safe_code(c) for c in codes[:32]) if x is not None))
    # Price and exact account holdings are intentionally NOT sent to any language model.
    evidence={
        'protocol':PROTOCOL,
        'symbol':symbol,
        'model_sha256':(prediction.get('model_sha256')
                        if re.fullmatch(r'[0-9a-f]{64}',str(prediction.get('model_sha256','')))
                        else None),
        'model_quantile_log_returns':{k:_num(quantiles.get(k)) for k in ('q10','q50','q90')},
        'observed_spread_bps':_num(book.get('spread_bps')),
        'observed_book_depth_sufficient':(book.get('hypothetical_full_roundtrip_depth_available')
            if isinstance(book.get('hypothetical_full_roundtrip_depth_available'),bool) else None),
        'indicator_strategy':_safe_code(technical.get('selected_strategy')),
        'indicator_signal':(technical.get('current_signal')
            if isinstance(technical.get('current_signal'),bool) else None),
        'known_news_count':(int(news['known_articles'])
            if isinstance(news.get('known_articles'),int) and 0<=news['known_articles']<=100000 else None),
        'negative_news_veto_count':min(10,len(news.get('strong_negative_urls') or [])),
        'risk_veto_codes':veto,
        'trade_execution':'SHADOW_ONLY_NO_REAL_ORDERS',
        'fee_verification':'UNVERIFIED',
    }
    return evidence


class RationaleCache:
    """Immutable SHA-keyed evidence-to-rationale receipts, unrelated to risk/order DB."""
    def __init__(self,root,*,read_only=False,mode=ExecutionMode.SHADOW):
        require_mode(mode,permitted=(ExecutionMode.SHADOW,),operation='RationaleCache')
        self.path=Path(root)/'rationale_cache.sqlite'
        self.read_only=read_only
        if read_only:
            self.db=(sqlite3.connect(self.path.as_uri()+'?mode=ro',uri=True)
                     if self.path.exists() else None)
            if self.db:self.db.execute('PRAGMA query_only=ON')
            return
        self.path.parent.mkdir(parents=True,exist_ok=True)
        self.db=sqlite3.connect(self.path,timeout=30)
        self.db.execute('PRAGMA busy_timeout=30000')
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('''CREATE TABLE IF NOT EXISTS rationale_receipts(
            prompt_sha256 TEXT PRIMARY KEY,
            prompt_json TEXT NOT NULL,
            provider TEXT NOT NULL,
            model TEXT NOT NULL,
            rationale_text TEXT NOT NULL,
            rationale_sha256 TEXT NOT NULL,
            observed_at_utc TEXT NOT NULL
        )''')
        self.db.commit()

    def get(self,key,prompt_json):
        if not self.db:return None
        row=self.db.execute('SELECT prompt_json,provider,model,rationale_text,rationale_sha256 '
                            'FROM rationale_receipts WHERE prompt_sha256=?',(key,)).fetchone()
        if row is None:return None
        stored,p,m,explanation,h=row
        if stored!=prompt_json or sha(stored)!=key or sha(explanation)!=h:
            raise RuntimeError('Rationale cache integrity failure; reject tampered receipt')
        return {'status':'CACHED_LLM_OUTPUT','provider':p,'model':m,'text':explanation,
                'prompt_sha256':key,'rationale_sha256':h,'authority':'ADVISORY_ONLY'}

    def put(self,key,prompt_json,provider,model,response):
        if self.read_only:raise RuntimeError('Read-only rationale cache cannot write')
        if not isinstance(response,str) or not response.strip() or len(response)>2500:
            raise ValueError('Invalid actual LLM response')
        if sha(prompt_json)!=key:raise ValueError('Invalid evidence/prompt digest')
        if _safe_model(model) is None:
            raise ValueError('Invalid local model name')
        text=response.strip()
        digest=sha(text)
        with self.db:
            self.db.execute('''INSERT OR IGNORE INTO rationale_receipts
                (prompt_sha256,prompt_json,provider,model,rationale_text,rationale_sha256,observed_at_utc)
                VALUES(?,?,?,?,?,?,?)''',(key,prompt_json,provider,model,text,digest,
                dt.datetime.now(dt.timezone.utc).isoformat()))
        receipt=self.get(key,prompt_json)
        return {**receipt,'status':'RECORDED_LLM_OUTPUT'} if receipt['rationale_sha256']==digest else receipt

    def close(self):
        if self.db is not None:self.db.close()


def _ollama_local(prompt):
    """The ONLY LLM transport. Fixed loopback, no proxy or redirects."""
    base='http://127.0.0.1:11434'
    class _NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self,req,fp,code,msg,headers,newurl):
            raise ConnectionError('Local LLM redirect refused')
    # Ignore proxy variables: structured observations must never leave loopback.
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),_NoRedirect())
    requested=os.environ.get('ATLAS_LLM_MODEL','').strip()
    if requested:
        model=_safe_model(requested)
        if model is None:raise ValueError('Unsafe local model name')
    else:
        with opener.open(base+'/api/tags',timeout=2) as response:
            if response.status!=200:raise ConnectionError('Ollama model inventory unavailable')
            inventory=json.loads(response.read(32768).decode('utf8'))
        options=[_safe_model(x.get('name')) for x in inventory.get('models',[]) if isinstance(x,dict)]
        candidates=[s for s in options if s and 'embed' not in s.lower()]
        if not candidates:raise RuntimeError('No suitable locally installed Ollama chat model')
        model=sorted(candidates)[0]
    request=urllib.request.Request(base+'/api/generate',data=canonical({
        'model':model,'prompt':prompt,'stream':False,
        'options':{'temperature':0,'num_predict':250}
    }).encode('utf8'),headers={'Content-Type':'application/json'},method='POST')
    with opener.open(request,timeout=12) as resp:
        if resp.status!=200:raise ConnectionError('Local Ollama response failure')
        payload=json.loads(resp.read(40000).decode('utf8'))
    text=payload.get('response')
    if not isinstance(text,str) or not text.strip():raise RuntimeError('Local LLM returned no explanation')
    if len(text)>2500:raise RuntimeError('Local LLM explanation too long')
    return model,text


def explain_for_state(root,state,*,provider=None):
    """Generate/cache explanation. Never takes or returns actionable order fields.

    A missing Ollama instance is explicitly reported, never impersonated using a
    fabricated 'LLM' rationale. No order tool can be reached from this module.
    """
    evidence=structured_evidence(state)
    selected=(provider if provider is not None else os.environ.get('ATLAS_LLM_PROVIDER','auto')).strip().lower()
    # An explicit model selection must never reuse another model's cached text.
    model_tag=os.environ.get('ATLAS_LLM_MODEL','').strip()
    prompt_json=canonical({'instruction':GENERATION_INSTRUCTION,'evidence':evidence,
                           'requested_provider':selected,'requested_model':model_tag or 'AUTO_LOCAL_DISCOVERY'})
    key=sha(prompt_json)
    if selected not in ('auto','ollama','disabled'):
        return {'status':'LLM_PROVIDER_NOT_PERMITTED','prompt_sha256':key,'authority':'ADVISORY_ONLY'}
    cache=RationaleCache(root,read_only=(selected=='disabled'))
    try:
        cached=cache.get(key,prompt_json)
        if cached is not None:return cached
        if selected=='disabled':
            return {'status':'LLM_DISABLED','prompt_sha256':key,'authority':'ADVISORY_ONLY'}
        try:
            model,response=_ollama_local(prompt_json)
        except (OSError,TimeoutError,ValueError,RuntimeError,ConnectionError,
                urllib.error.URLError,json.JSONDecodeError) as exc:
            return {'status':'LOCAL_LLM_UNAVAILABLE','reason_code':type(exc).__name__,
                    'prompt_sha256':key,'authority':'ADVISORY_ONLY'}
        return cache.put(key,prompt_json,'LOCAL_OLLAMA',model,response)
    finally:cache.close()


def rationale_status(root):
    """No database mutation, model inference, API call or order operation."""
    cache=RationaleCache(root,read_only=True)
    try:
        if cache.db is None:
            return {'mode':'READ_ONLY','receipts':0,'receipt_integrity':'NO_DATABASE',
                    'provider_configuration':os.environ.get('ATLAS_LLM_PROVIDER','auto'),
                    'order_authority':'NONE'}
        rows=cache.db.execute('SELECT prompt_sha256,prompt_json,rationale_text,rationale_sha256 '
                              'FROM rationale_receipts').fetchall()
        intact=all(sha(js)==key and sha(txt)==h for key,js,txt,h in rows)
        return {'mode':'READ_ONLY','receipts':len(rows),
                'receipt_integrity':'VALID' if intact else 'INVALID',
                'provider_configuration':os.environ.get('ATLAS_LLM_PROVIDER','auto'),
                'order_authority':'NONE'}
    finally:cache.close()
