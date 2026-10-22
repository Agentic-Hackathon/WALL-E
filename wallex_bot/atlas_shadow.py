"""Persistent, real-quote-only PAPER ledger; never places Wallex orders.
Hypothetical execution assumptions are distinguished from observed market data.
"""
from __future__ import annotations
import json,sqlite3,time,hashlib,math
from pathlib import Path
from datetime import datetime,timezone
from . import market
from .atlas_deep import predict_latest, verified_champion
from .live_scout import measure_book
from .atlas_forward import ForwardLedger


def now():return datetime.now(timezone.utc).isoformat()

class PaperAccount:
    def __init__(self,lake,starting_tmn=5_000_000):
        self.db=sqlite3.connect(Path(lake.root)/'shadow.sqlite',timeout=20)
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS kv(key TEXT PRIMARY KEY,value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS positions(symbol TEXT PRIMARY KEY,quantity REAL NOT NULL,entry_cost REAL NOT NULL,
                entry_price REAL NOT NULL,entry_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY, observed_at TEXT NOT NULL, symbol TEXT NOT NULL,
                action TEXT NOT NULL, payload TEXT NOT NULL, prev_hash TEXT NOT NULL, hash TEXT NOT NULL);
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

    def trade(self,symbol,decision,book,fee=.001):
        cash=float(self.get('cash_tmn'))
        positions=self.db.execute('SELECT symbol,quantity,entry_cost FROM positions').fetchall()
        bid=float(book['best_bid_tmn']);ask=float(book['best_ask_tmn'])
        quote={'bid_tmn':bid,'ask_tmn':ask,'observed_spread_bps':book['spread_bps']}
        if bid<=0 or ask<=bid:raise ValueError('Invalid actual Wallex bid/ask')
        with self.db:
            # Approximate liquidation equity from CURRENT observed bids; not actual realized PnL.
            holdings={s:(qty,cost) for s,qty,cost in positions}
            own=holdings.get(symbol)
            q10=decision.get('quantile_log_returns',{}).get('q10')
            q50=decision.get('quantile_log_returns',{}).get('q50')
            if own:
                qty,cost=own
                # Exit on adverse evidence; uses actual currently observed bid.
                if self.get('stopped')=='1' or (q50 is not None and (q50<0 or bid/(cost/qty)-1 < -0.012)):
                    proceeds=qty*bid*(1-fee)
                    self._set('cash_tmn',cash+proceeds)
                    self.db.execute('DELETE FROM positions WHERE symbol=?',(symbol,))
                    action='PAPER_SELL'
                else:action='HOLD_POSITION'
            elif self.get('stopped')=='1':
                action='RISK_CIRCUIT_BREAKER_STOPPED'
            else:
                spread_log=math.log(ask/bid)
                estimated_cost=2*math.log(1+fee)+spread_log+0.001
                # Conservative q10 forecast must exceed cost: an ML-driven decision gate.
                invest=min(cash*0.10,500_000.)
                held_cost=sum(cost for _,_,cost in positions)
                if q10 is None or not math.isfinite(q10):action='NO_TRUSTED_FORECAST'
                elif q10<=estimated_cost:action='INSUFFICIENT_RISK_ADJUSTED_EDGE'
                elif held_cost+invest>1_000_000.:action='PORTFOLIO_RISK_LIMIT'
                elif book['top5_ask_notional_tmn']<invest*3:action='INSUFFICIENT_VISIBLE_LIQUIDITY'
                elif invest<100_000:action='ORDER_BELOW_RESEARCH_MIN'
                else:
                    qty=(invest/(1+fee))/ask
                    self._set('cash_tmn',cash-invest)
                    self.db.execute('INSERT INTO positions VALUES(?,?,?,?,?)',(symbol,qty,invest,ask,now()))
                    action='PAPER_BUY'
            self.log(symbol,action,{'forecast':decision,'source':'genuine_wallex_rest_depth',
                  'quote':quote,'fee_assumption':fee,
                  'fill_assumption':'HYPOTHETICAL at observed best bid/ask; not an exchange execution',
                  'risk_limits':'10% cash per position; 20% of initial portfolio max',
                  'paper_cash_tmn':self.get('cash_tmn')})
        return action

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
            peak=max(float(self.get('high_water_tmn')),equity)
            self._set('high_water_tmn',peak)
            drawdown=1-equity/peak
            if drawdown>=.03:self._set('stopped',1)
            self.log('PORTFOLIO','FRESH_REAL_BID_MARK_TO_MARKET',{'equity_tmn':equity,'drawdown_pct':100*drawdown,
                        'paper_stopped':self.get('stopped')=='1',
                        'price_source':'current actual Wallex bid of every held symbol',
                        'valuation':'hypothetical liquidation incl. assumed fee'})
        return {'equity_tmn':equity,'drawdown_pct':100*drawdown,'stopped':self.get('stopped')=='1'}

    def close(self):self.db.close()


def shadow_cycle(lake,models_dir=None,top=8,fee=.001):
    """One autonomous cycle on REAL Wallex quotes and previously trained checkpoints.
    Never read private API keys, never submit orders or withdrawal requests.
    """
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
                action=paper.trade(symbol,prediction,measured,fee)
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
