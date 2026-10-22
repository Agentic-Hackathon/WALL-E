"""Prospective point-in-time Wallex forecast evaluation using genuine depth receipts.

No synthetic market prices, mock order fills, price imputation, or exchange orders.
Quotes are ACTUAL REST depth observations, timestamped at LOCAL receipt time.
The future outcome is unknowable until a LATER real quote arrives.
"""
from __future__ import annotations
import datetime as dt
import hashlib
import json
import math
import sqlite3
import time
from pathlib import Path


def _canon(obj):
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def _sha(obj):
    return hashlib.sha256(_canon(obj).encode('utf-8')).hexdigest()


class ForwardLedger:
    """Append-only market observations; late outcomes are linked to both receipts."""
    def __init__(self, root):
        self.path = Path(root) / 'forward_observations.sqlite'
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path, timeout=30)
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS quotes(
                id INTEGER PRIMARY KEY, symbol TEXT NOT NULL, observed_epoch REAL NOT NULL,
                best_bid REAL NOT NULL, best_ask REAL NOT NULL, mid REAL NOT NULL,
                raw_book TEXT NOT NULL, receipt_sha256 TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS quotes_symbol_time ON quotes(symbol, observed_epoch);
            CREATE TABLE IF NOT EXISTS forecasts(
                id INTEGER PRIMARY KEY, symbol TEXT NOT NULL,
                feature_end_ts INTEGER NOT NULL, model_sha256 TEXT NOT NULL,
                q10 REAL NOT NULL, q50 REAL NOT NULL, q90 REAL NOT NULL,
                horizon_seconds INTEGER NOT NULL, fee_per_side REAL NOT NULL,
                origin_quote_id INTEGER NOT NULL REFERENCES quotes(id),
                due_epoch REAL NOT NULL, status TEXT NOT NULL DEFAULT 'PENDING',
                forecast_sha256 TEXT NOT NULL,
                UNIQUE(symbol,feature_end_ts,model_sha256));
            CREATE INDEX IF NOT EXISTS forecast_due ON forecasts(symbol,status,due_epoch);
            CREATE TABLE IF NOT EXISTS outcomes(
                forecast_id INTEGER PRIMARY KEY REFERENCES forecasts(id),
                future_quote_id INTEGER NOT NULL REFERENCES quotes(id),
                elapsed_seconds REAL NOT NULL,
                actual_mid_log_return REAL NOT NULL,
                observed_ask_to_future_bid_net_log_return REAL NOT NULL,
                outcome_sha256 TEXT NOT NULL);
        ''')
        self.db.commit()

    def record_real_quote(self, symbol, raw_book, book_metrics, observed_epoch=None):
        """Persist the real source depth JSON and score any due observations.
        Tests and replay must never substitute fabricated books for this method.
        """
        if not isinstance(raw_book, dict) or not raw_book:
            raise ValueError('Actual nonempty Wallex depth response required')
        t=float(time.time() if observed_epoch is None else observed_epoch)
        bid=float(book_metrics['best_bid_tmn'])
        ask=float(book_metrics['best_ask_tmn'])
        if not (math.isfinite(bid) and math.isfinite(ask) and 0 < bid < ask):
            raise ValueError('Invalid bid/ask; reject observation')
        mid=(bid+ask)/2
        payload={'symbol':symbol,'observed_epoch':t,'best_bid':bid,'best_ask':ask,
                 'mid':mid,'raw_book':raw_book}
        with self.db:
            cur=self.db.execute('''INSERT INTO quotes(symbol,observed_epoch,best_bid,best_ask,mid,raw_book,receipt_sha256)
                VALUES(?,?,?,?,?,?,?)''',(symbol,t,bid,ask,mid,_canon(raw_book),_sha(payload)))
            quote_id=cur.lastrowid
            pending=self.db.execute('''SELECT f.id,f.due_epoch,f.fee_per_side,q.observed_epoch,q.best_ask,q.mid
                FROM forecasts f JOIN quotes q ON q.id=f.origin_quote_id
                WHERE f.symbol=? AND f.status='PENDING' AND f.due_epoch<=?
                ORDER BY f.due_epoch''',(symbol,t)).fetchall()
            for fid,due,fee,origin_epoch,origin_ask,origin_mid in pending:
                if t <= origin_epoch:
                    continue
                # The first later quote received after the horizon must be recent enough.
                # Never interpolate an unobserved price or silently backdate a quote.
                if t > due + 20*60:
                    self.db.execute("UPDATE forecasts SET status='EXPIRED_NO_TIMELY_REAL_QUOTE' WHERE id=?",(fid,))
                    continue
                midpoint_ret=math.log(mid/origin_mid)
                hypothetical_net=math.log(bid/origin_ask)+math.log1p(-fee)-math.log1p(fee)
                outcome={'forecast_id':fid,'future_quote_id':quote_id,'elapsed_seconds':t-origin_epoch,
                         'actual_mid_log_return':midpoint_ret,
                         'observed_ask_to_future_bid_net_log_return':hypothetical_net}
                self.db.execute('''INSERT INTO outcomes VALUES(?,?,?,?,?,?)''',
                    (fid,quote_id,t-origin_epoch,midpoint_ret,hypothetical_net,_sha(outcome)))
                self.db.execute("UPDATE forecasts SET status='SCORED_FROM_REAL_FUTURE_QUOTE' WHERE id=?",(fid,))
        return quote_id

    def record_forecast(self, symbol, feature_end_ts, model_sha256, quantiles,
                        horizon_seconds, fee_per_side, origin_quote_id):
        if not (isinstance(model_sha256,str) and len(model_sha256)==64):
            raise ValueError('Exact model SHA-256 required')
        q10,q50,q90=(float(quantiles[k]) for k in ('q10','q50','q90'))
        if not (math.isfinite(q10) and math.isfinite(q50) and math.isfinite(q90)
                and q10<=q50<=q90):
            raise ValueError('Model quantiles invalid or crossing')
        if not 0<=fee_per_side<.05 or int(horizon_seconds)<60:
            raise ValueError('Fee/horizon invalid')
        origin=self.db.execute('SELECT observed_epoch,symbol FROM quotes WHERE id=?',
                               (origin_quote_id,)).fetchone()
        if origin is None or origin[1]!=symbol:
            raise ValueError('Forecast cannot exist without its actual Wallex quote')
        due=origin[0]+int(horizon_seconds)
        payload={'symbol':symbol,'feature_end_ts':int(feature_end_ts),
                 'model_sha256':model_sha256,'q10':q10,'q50':q50,'q90':q90,
                 'horizon_seconds':int(horizon_seconds), 'fee_per_side':float(fee_per_side),
                 'origin_quote_id':origin_quote_id,'due_epoch':due}
        with self.db:
            self.db.execute('''INSERT OR IGNORE INTO forecasts
              (symbol,feature_end_ts,model_sha256,q10,q50,q90,horizon_seconds,
               fee_per_side,origin_quote_id,due_epoch,forecast_sha256)
              VALUES(?,?,?,?,?,?,?,?,?,?,?)''',
              (symbol,int(feature_end_ts),model_sha256,q10,q50,q90,int(horizon_seconds),
               fee_per_side,origin_quote_id,due,_sha(payload)))

    def summary(self):
        count=self.db.execute('SELECT COUNT(*) FROM quotes').fetchone()[0]
        statuses=dict(self.db.execute('SELECT status,COUNT(*) FROM forecasts GROUP BY status').fetchall())
        data=self.db.execute('''SELECT f.symbol,f.q10,f.q50,f.q90,o.actual_mid_log_return,
            o.observed_ask_to_future_bid_net_log_return
            FROM forecasts f JOIN outcomes o ON f.id=o.forecast_id''').fetchall()
        result={'mode':'PROSPECTIVE_REAL_QUOTES_NO_TRADES',
                'quote_receipts':count,'forecast_statuses':statuses,'scored':len(data),
                'source':'Wallex real public order books; future outcomes from later actual receipts',
                'limits':'Only one research horizon; overlapping forecasts not independent; best quotes are not guaranteed fills',
                'fee_assumption_applies_to':'counterfactual ask-to-future-bid, NOT executed account PnL',
                'alignment_caveat':'Returns compare observed quote times; DL was trained on candle close-to-close labels, so model-vs-quote statistics are proxies, NOT calibrated on identical timestamp targets'}
        if data:
            import numpy as np
            actual=np.array([r[4] for r in data],dtype=float)
            predicted=np.array([r[2] for r in data],dtype=float)
            net=np.array([r[5] for r in data],dtype=float)
            result['forecast_vs_quote_proxy_diagnostics']={
                'median_forecast_mae_log_return':round(float(np.mean(abs(actual-predicted))),9),
                'directional_accuracy':round(float(np.mean((actual>0)==(predicted>0))),6),
                'real_mid_log_return_mean':round(float(np.mean(actual)),9),
                'observed_ask_to_future_bid_net_mean':round(float(np.mean(net)),9),
                'fraction_positive_counterfactual_net':round(float(np.mean(net>0)),6),
                'q10_coverage':round(float(np.mean(actual>=np.array([r[1] for r in data]))),6),
                'q90_coverage':round(float(np.mean(actual<=np.array([r[3] for r in data]))),6),
                'distinct_symbols':len(set(r[0] for r in data)),
            }
        return result

    def verify(self):
        for rid,sym,t,bid,ask,mid,raw,digest in self.db.execute(
            'SELECT id,symbol,observed_epoch,best_bid,best_ask,mid,raw_book,receipt_sha256 FROM quotes'):
            payload={'symbol':sym,'observed_epoch':t,'best_bid':bid,'best_ask':ask,
                     'mid':mid,'raw_book':json.loads(raw)}
            if _sha(payload)!=digest:return False
        for row in self.db.execute('''SELECT symbol,feature_end_ts,model_sha256,q10,q50,q90,
                horizon_seconds,fee_per_side,origin_quote_id,due_epoch,forecast_sha256 FROM forecasts'''):
            keys=['symbol','feature_end_ts','model_sha256','q10','q50','q90',
                  'horizon_seconds','fee_per_side','origin_quote_id','due_epoch']
            if _sha(dict(zip(keys,row[:-1])))!=row[-1]:return False
        for row in self.db.execute('''SELECT forecast_id,future_quote_id,elapsed_seconds,
                actual_mid_log_return,observed_ask_to_future_bid_net_log_return,outcome_sha256 FROM outcomes'''):
            keys=['forecast_id','future_quote_id','elapsed_seconds',
                  'actual_mid_log_return','observed_ask_to_future_bid_net_log_return']
            if _sha(dict(zip(keys,row[:-1])))!=row[-1]:return False
        inconsistent=self.db.execute('''SELECT COUNT(*) FROM forecasts f WHERE
            (f.status='SCORED_FROM_REAL_FUTURE_QUOTE' AND NOT EXISTS
               (SELECT 1 FROM outcomes o WHERE o.forecast_id=f.id)) OR
            (f.status!='SCORED_FROM_REAL_FUTURE_QUOTE' AND EXISTS
               (SELECT 1 FROM outcomes o WHERE o.forecast_id=f.id))''').fetchone()[0]
        if inconsistent:return False
        return True

    def close(self):self.db.close()


def report(root):
    ledger=ForwardLedger(root)
    try:
        result=ledger.summary()
        result['receipt_hashes_valid']=ledger.verify()
        result['database']=str(ledger.path)
        return result
    finally:ledger.close()
