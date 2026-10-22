"""Persistent, real-quote-only PAPER ledger; never places Wallex orders.
Hypothetical execution assumptions are distinguished from observed market data.
Stage 2 source note: risk-first broker separation is independently implemented
from the conceptual literature registered in third_party/SOURCES.md; no external code copied.
"""
from __future__ import annotations
import json,sqlite3,time,hashlib
from dataclasses import asdict
from pathlib import Path
from datetime import datetime,timezone
from . import market
from .atlas_deep import predict_latest, verified_champion
from .live_scout import measure_book
from .atlas_forward import ForwardLedger
from .atlas_risk import RiskGate
from .atlas_broker import ShadowBroker, OrderIntent
from .atlas_mode import ExecutionMode,require_mode


def now():return datetime.now(timezone.utc).isoformat()

class PaperAccount:
    def __init__(self,lake,starting_tmn=5_000_000,mode=ExecutionMode.SHADOW):
        require_mode(mode,permitted=(ExecutionMode.SHADOW,),operation='PaperAccount')
        self.risk=RiskGate()
        self.db=sqlite3.connect(Path(lake.root)/'shadow.sqlite',timeout=20)
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS kv(key TEXT PRIMARY KEY,value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS positions(symbol TEXT PRIMARY KEY,quantity REAL NOT NULL,entry_cost REAL NOT NULL,
                entry_price REAL NOT NULL,entry_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY, observed_at TEXT NOT NULL, symbol TEXT NOT NULL,
                action TEXT NOT NULL, payload TEXT NOT NULL, prev_hash TEXT NOT NULL, hash TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS broker_intents(
                client_order_id TEXT PRIMARY KEY, symbol TEXT NOT NULL,
                fingerprint TEXT NOT NULL, action TEXT NOT NULL);
        ''');self.db.commit()
        with self.db:
            self.db.execute('INSERT OR IGNORE INTO kv VALUES(?,?)',('cash_tmn',str(starting_tmn)))
            self.db.execute('INSERT OR IGNORE INTO kv VALUES(?,?)',('starting_tmn',str(starting_tmn)))
            self.db.execute('INSERT OR IGNORE INTO kv VALUES(?,?)',('high_water_tmn',str(starting_tmn)))
            self.db.execute('INSERT OR IGNORE INTO kv VALUES(?,?)',('stopped','0'))

    def get(self,name):return self.db.execute('SELECT value FROM kv WHERE key=?',(name,)).fetchone()[0]
    def _set(self,key,value):self.db.execute('INSERT OR REPLACE INTO kv VALUES(?,?)',(key,str(value)))
    def log(self,sym,action,payload):
        at=now();prev=self.db.execute('SELECT hash FROM events ORDER BY id DESC LIMIT 1').fetchone()
        previous=prev[0] if prev else 'GENESIS'; encoded=json.dumps(payload,sort_keys=True,ensure_ascii=False,allow_nan=False)
        digest=hashlib.sha256((previous+'|'+at+'|'+sym+'|'+action+'|'+encoded).encode()).hexdigest()
        self.db.execute('INSERT INTO events(observed_at,symbol,action,payload,prev_hash,hash) VALUES(?,?,?,?,?,?)',
                        (at,sym,action,encoded,previous,digest))

    def verify(self):
        prev='GENESIS'
        for at,sym,action,payload,p,h in self.db.execute('SELECT observed_at,symbol,action,payload,prev_hash,hash FROM events ORDER BY id'):
            if p!=prev or hashlib.sha256((p+'|'+at+'|'+sym+'|'+action+'|'+payload).encode()).hexdigest()!=h:return False
            prev=h
        return True

    def trade(self,symbol,decision,book,fee=.001,*,client_order_id=None,expected_side='AUTO',purpose='STRATEGY'):
        """Atomic shadow mutation and idempotency, gated by existing RiskGate.

        Repeated client_order_id with IDENTICAL evidence returns the same result
        without any extra cash mutation, position or audit event. Reusing the ID
        with different book, forecast or side fails closed.
        """
        import re
        if client_order_id is not None and (not isinstance(client_order_id,str) or
                not re.fullmatch(r'[A-Za-z0-9:_-]{8,120}',client_order_id)):
            raise ValueError('Invalid client_order_id')
        if expected_side not in ('AUTO','BUY','SELL'):
            raise ValueError('Invalid expected side')
        if purpose not in ('STRATEGY','FINAL_TMN'):
            raise ValueError('Invalid trade purpose')
        if purpose=='FINAL_TMN' and expected_side!='SELL':
            raise ValueError('Final TMN purpose can only request a sell')
        evidence={'symbol':symbol,'decision':decision,'book':book,'fee':fee,
                  'expected_side':expected_side}
        if purpose!='STRATEGY':
            evidence['purpose']=purpose
        fingerprint=hashlib.sha256(json.dumps(evidence,sort_keys=True,ensure_ascii=False,
                allow_nan=False,separators=(',',':')).encode('utf8')).hexdigest()
        if self.db.in_transaction:
            raise RuntimeError('Paper trade must own its atomic SQLite transaction')
        self.db.execute('BEGIN IMMEDIATE')
        try:
            if client_order_id is not None:
                previous=self.db.execute('SELECT symbol,fingerprint,action FROM broker_intents WHERE client_order_id=?',
                    (client_order_id,)).fetchone()
                if previous is not None:
                    if previous[0]!=symbol or previous[1]!=fingerprint:
                        raise ValueError('Idempotency conflict: identifier reused with different evidence')
                    self.db.commit()
                    return previous[2]
            cash=float(self.get('cash_tmn'))
            positions=self.db.execute('SELECT symbol,quantity,entry_cost FROM positions').fetchall()
            # The same deterministic gate authorizes ordinary and terminal orders.
            if purpose=='FINAL_TMN':
                gate=self.risk.final_tmn_liquidation(symbol,book,cash,positions,fee)
            else:
                gate=self.risk.evaluate(symbol,decision,book,cash,positions,self.get('stopped')=='1',fee)
            # Stage 8: evidence for OFFLINE replay. These are the actual persisted
            # input fields consumed by this deterministic RiskGate, NOT inferred
            # prices, recreated historical market observations or live orders.
            # Existing/legacy rows without this evidence remain explicitly unreplayable.
            replay_inputs = {
                'protocol': 'ATLAS_RISK_REPLAY_V1',
                'symbol': symbol,
                'forecast': {'quantile_log_returns': {
                    key: ((decision.get('quantile_log_returns') or {}).get(key)
                          if isinstance(decision, dict) and isinstance(decision.get('quantile_log_returns'),dict)
                          else None)
                    for key in ('q10','q50')}},
                'book': {key: book.get(key) if isinstance(book,dict) else None
                         for key in ('best_bid_tmn','best_ask_tmn','spread_bps',
                                     'top5_ask_notional_tmn','best_bid_quantity')},
                'cash_tmn': cash,
                'positions': [[s, qty, cost] for s,qty,cost in positions],
                'stopped': self.get('stopped') == '1',
                'fee_assumption': fee,
                'expected_side': expected_side,
                'purpose': purpose,
                'client_order_id': client_order_id,
                'policy_limits': asdict(self.risk.limits),
                'risk_source_sha256': hashlib.sha256(
                    Path(__file__).with_name('atlas_risk.py').read_bytes()).hexdigest(),
                'model_sha256': (decision.get('model_sha256') if isinstance(decision,dict) else None),
                'gate_decision': gate.audit_payload(),
            }
            replay_canonical=json.dumps(replay_inputs,sort_keys=True,ensure_ascii=False,
                                        separators=(',',':'),allow_nan=False)
            replay_hash=hashlib.sha256(replay_canonical.encode('utf-8')).hexdigest()
            action=gate.action
            if (expected_side=='BUY' and action=='PAPER_SELL') or (expected_side=='SELL' and action=='PAPER_BUY'):
                action='BROKER_SIDE_MISMATCH_NO_ORDER'
            quote={'bid_tmn':book.get('best_bid_tmn'),'ask_tmn':book.get('best_ask_tmn'),
                   'observed_spread_bps':book.get('spread_bps')} if isinstance(book,dict) else {'unavailable':True}
            holdings={s:(qty,cost) for s,qty,cost in positions}
            if action=='PAPER_SELL':
                bid=float(book['best_bid_tmn'])
                qty,_=holdings[symbol]
                proceeds=qty*bid*(1-fee)
                self._set('cash_tmn',cash+proceeds)
                self.db.execute('DELETE FROM positions WHERE symbol=?',(symbol,))
            elif action=='PAPER_BUY':
                invest=gate.notional_tmn
                ask=float(book['best_ask_tmn'])
                qty=(invest/(1+fee))/ask
                self._set('cash_tmn',cash-invest)
                self.db.execute('INSERT INTO positions VALUES(?,?,?,?,?)',(symbol,qty,invest,ask,now()))
            self.log(symbol,action,{'forecast':decision,
                  'source':'genuine_wallex_rest_depth' if action in ('PAPER_BUY','PAPER_SELL')
                           else 'unverified_or_incomplete_observation_no_execution',
                  'quote':quote,'fee_assumption':fee,
                  'fill_assumption':'HYPOTHETICAL at observed best bid/ask; not an exchange execution',
                  'risk_gate':gate.audit_payload(),
                  'client_order_id':client_order_id,'purpose':purpose,
                  'paper_cash_tmn':self.get('cash_tmn'),
                  'risk_replay_inputs':replay_inputs,
                  'risk_replay_sha256':replay_hash})
            if client_order_id is not None:
                self.db.execute('INSERT INTO broker_intents VALUES(?,?,?,?)',
                    (client_order_id,symbol,fingerprint,action))
            self.db.commit()
            return action
        except Exception:
            self.db.rollback()
            raise

    def update_equity_from_observed_quotes(self, bid_by_symbol,fee=.001):
        """Only mark-to-market using FRESH actual observed bids of all held symbols.
        No missing symbol may be assigned a guessed price.
        """
        positions=self.db.execute('SELECT symbol,quantity FROM positions').fetchall()
        missing=[sym for sym,_ in positions if sym not in bid_by_symbol]
        if missing:raise RuntimeError('Cannot mark equity: real bid observations missing for '+','.join(missing))
        equity=float(self.get('cash_tmn'))
        for sym,qty in positions:equity+=qty*float(bid_by_symbol[sym])*(1-fee)
        with self.db:
            assessed=self.risk.assess_equity(equity,float(self.get('high_water_tmn')),self.get('stopped')=='1')
            self._set('high_water_tmn',assessed.high_water_tmn)
            self._set('stopped','1' if assessed.stopped else '0')
            self.log('PORTFOLIO','FRESH_REAL_BID_MARK_TO_MARKET',{'equity_tmn':equity,'drawdown_pct':100*assessed.drawdown_fraction,
                        'paper_stopped':assessed.stopped,
                        'risk_gate':{'max_drawdown_fraction':self.risk.limits.max_drawdown_fraction},
                        'price_source':'current actual Wallex bid of every held symbol',
                        'valuation':'hypothetical liquidation incl. assumed fee'})
        return {'equity_tmn':equity,'drawdown_pct':100*assessed.drawdown_fraction,'stopped':assessed.stopped}

    def close(self):self.db.close()


def shadow_cycle(lake,models_dir=None,top=8,fee=.001,mode=ExecutionMode.SHADOW):
    """One autonomous cycle on REAL Wallex quotes and previously trained checkpoints.
    Never read private API keys, never submit orders or withdrawal requests.
    """
    require_mode(mode,permitted=(ExecutionMode.SHADOW,),operation='shadow_cycle')
    checkpoint=verified_champion(models_dir or lake.root/'models')
    import torch
    model_cfg=torch.load(checkpoint,map_location='cpu',weights_only=True)['config']
    metas=[]
    for (raw,) in lake.db.execute('SELECT metadata FROM assets'):
        m=json.loads(raw)
        if m.get('is_spot') is True and m.get('quote_asset')=='TMN':
            try:volume=float(m.get('quote_volume_24h') or 0)
            except (ValueError,TypeError):volume=0
            metas.append((volume,m['symbol']))
    symbols=[s for _,s in sorted(metas,reverse=True)[:top]]
    paper=PaperAccount(lake); observer=ForwardLedger(lake.root); output=[]
    model_digest=hashlib.sha256(Path(checkpoint).read_bytes()).hexdigest()
    try:
        if not paper.verify():raise RuntimeError('Persistent paper audit corrupted; fail closed')
        held=[s for (s,) in paper.db.execute('SELECT symbol FROM positions')]
        # No new entry unless entire current portfolio can be marked using real, fresh bids.
        quotes={}
        for held_symbol in held:
            observed=measure_book(market.depth(held_symbol),notional_tmn=250_000,fee_rate=fee)
            quotes[held_symbol]=observed['best_bid_tmn']
        paper.update_equity_from_observed_quotes(quotes,fee=fee)
        for symbol in symbols:
            try:
                # Capture the actual depth FIRST so past forecasts can be evaluated
                # even if today's inference is unavailable or stale.
                raw=market.depth(symbol)
                measured=measure_book(raw,notional_tmn=250_000,fee_rate=fee)
                observed_at_epoch=time.time()
                quote_id=observer.record_real_quote(symbol,raw,measured,observed_at_epoch)
                prediction=predict_latest(lake,checkpoint,symbol)
                seconds=market.ALLOWED_RESOLUTIONS[model_cfg['resolution']]
                # Refuse stale archive observations; no guess about missing latest candles.
                if observed_at_epoch-prediction['feature_end_ts']>3*seconds:
                    raise RuntimeError('Latest genuine candle is stale; refresh market archive')
                observer.record_forecast(symbol,prediction['feature_end_ts'],model_digest,
                    prediction['quantile_log_returns'],int(model_cfg['horizon'])*seconds,fee,quote_id)
                # Broker delegates to PaperAccount's atomic idempotent RiskGate path.
                intent_id='shadow-'+hashlib.sha256((str(quote_id)+'|'+symbol+'|'+model_digest).encode()).hexdigest()[:48]
                action=ShadowBroker(paper).submit(OrderIntent(intent_id,symbol,'AUTO'),
                    forecast=prediction,book=measured,fee=fee).reason
                output.append({'symbol':symbol,'action':action,'book_spread_bps':measured['spread_bps'],
                               'q10':prediction['quantile_log_returns']['q10'],
                               'q50':prediction['quantile_log_returns']['q50']})
            except Exception as exc:
                with paper.db:
                    paper.log(symbol,'REJECTED',{'error':type(exc).__name__+': '+str(exc)[:150],
                                                 'market_data_fallback':'NONE'})
                output.append({'symbol':symbol,'action':'REJECTED','reason':type(exc).__name__})
    finally:
        paper.close()
        observer.close()
    return {'mode':'SHADOW_ONLY_NO_REAL_ORDERS','checkpoint':str(checkpoint),
            'events':output,'audit':str(lake.root/'shadow.sqlite'),
            'forward_audit':str(lake.root/'forward_observations.sqlite')}
