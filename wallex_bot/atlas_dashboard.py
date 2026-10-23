"""Read-only localhost dashboard over genuine Wallex Atlas V3.4 evidence.

Never generates prices, predictions, news impacts, fills, or orders.
Does not run or pause watch and does not write to the Atlas market databases.
"""
from __future__ import annotations
import argparse
import csv
import gzip
import hashlib
import json
import math
import os
import re
import sqlite3
import time
from datetime import datetime, timezone
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

SYMBOL_RE = re.compile(r'^[A-Z0-9]{2,40}$')
RESOLUTIONS = {'1': 60, '5': 300, '15': 900, '30': 1800, '60': 3600, '180': 10800,
               '240': 14400, '360': 21600, '480': 28800, '720': 43200, '1D': 86400,
               '2D': 172800, '3D': 259200}
SHADOW_TRADE_ACTIONS = {'PAPER_BUY', 'PAPER_SELL', 'PAPER_END_OF_WATCH_SELL'}


def _read_json(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding='utf8'))
    except (FileNotFoundError, ValueError, OSError):
        return default


def _sql(root, name):
    path = Path(root) / name
    if not path.is_file():
        return None
    # Mode RO avoids creating or changing the user's live SQLite databases.
    connection = sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True, timeout=2)
    connection.row_factory = sqlite3.Row
    connection.execute('PRAGMA query_only=ON')
    connection.execute('PRAGMA busy_timeout=2000')
    return connection


def _rows(db, query, args=()):
    if db is None:
        return []
    try:
        return [dict(x) for x in db.execute(query, args).fetchall()]
    except sqlite3.OperationalError:
        return []


def _one(db, query, args=(), default=None):
    found = _rows(db, query, args)
    return found[0] if found else (default or {})


def _digest(path):
    h = hashlib.sha256()
    with open(path, 'rb') as stream:
        for part in iter(lambda: stream.read(1 << 20), b''):
            h.update(part)
    return h.hexdigest()


def _finite(v):
    try:
        f = float(v)
        return f if math.isfinite(f) else None
    except (ValueError, TypeError):
        return None


def _quote_currency(x):
    return 'TMN' if x and x.endswith('TMN') else ('USDT' if x and x.endswith('USDT') else 'UNKNOWN')


def _catalog(root):
    db = _sql(root, 'catalog.sqlite')
    if db is None:
        return {'symbols': [], 'assets': 0, 'spot': 0, 'chunks': 0, 'candle_rows': 0, 'incidents': 0}
    try:
        symbols = []
        tmn_count=0
        for row in _rows(db, 'SELECT symbol,metadata FROM assets ORDER BY symbol'):
            info = _read_json_str(row['metadata'])
            if info.get('is_spot') is True:
                if info.get('quote_asset') == 'TMN':tmn_count+=1
                symbols.append({'symbol': row['symbol'], 'quote_volume_24h': _finite(info.get('quote_volume_24h')) or 0})
        symbols.sort(key=lambda p: -p['quote_volume_24h'])
        counts = _one(db, '''SELECT (SELECT count(*) FROM assets) AS assets,
                         (SELECT count(*) FROM chunks) AS chunks,
                         (SELECT coalesce(sum(rows),0) FROM chunks) AS candle_rows,
                         (SELECT count(*) FROM incidents) AS incidents''')
        return {**counts, 'symbols': [x['symbol'] for x in symbols], 'spot_tmn': tmn_count}
    finally:
        db.close()


def _read_json_str(text):
    try:
        obj = json.loads(text)
        return obj if isinstance(obj, dict) else {}
    except (ValueError, TypeError):
        return {}


def candles(root, symbol, resolution='15', limit=240):
    if not SYMBOL_RE.fullmatch(symbol) or resolution not in RESOLUTIONS:
        raise ValueError('Invalid symbol/timeframe')
    db = _sql(root, 'catalog.sqlite')
    if db is None:
        return {'bars': [], 'gaps': [], 'reason': 'NO_REAL_CANDLE_ARCHIVE'}
    try:
        chunks = _rows(db, '''SELECT filename, sha256, rows,first_ts,last_ts FROM chunks
                      WHERE symbol=? AND resolution=? AND status='COMPLETE'
                      ORDER BY last_ts DESC LIMIT 80''', (symbol, resolution))
    finally:
        db.close()
    all_bars = {}
    checked_files = 0
    for c in chunks:
        rel = c['filename']
        path = Path(root) / rel
        if not path.is_file() or _digest(path) != c['sha256']:
            # A corrupted file is never returned to a chart as genuine evidence.
            return {'bars': [], 'gaps': [], 'reason': 'ARCHIVE_FILE_INTEGRITY_FAILED', 'file': rel}
        try:
            with gzip.open(path, 'rt', encoding='utf8', newline='') as stream:
                for item in csv.DictReader(stream):
                    ts = int(item['timestamp'])
                    ohlc = {k: _finite(item.get(k)) for k in ('open', 'high', 'low', 'close', 'volume')}
                    if (all(v is not None for v in ohlc.values()) and
                        ohlc['low'] <= min(ohlc['open'],ohlc['close']) and
                        ohlc['high'] >= max(ohlc['open'],ohlc['close']) and ohlc['volume'] >= 0):
                        all_bars[ts] = {'t': ts, **ohlc}
            checked_files += 1
        except (OSError, ValueError, KeyError, EOFError):
            return {'bars': [], 'gaps': [], 'reason': 'ARCHIVE_FILE_UNREADABLE', 'file': rel}
        if len(all_bars) >= limit + 50:
            break
    bars = sorted(all_bars.values(), key=lambda b: b['t'])[-limit:]
    step = RESOLUTIONS[resolution]
    gaps = [{'after': p['t'], 'before': n['t'], 'missing_bars': (n['t']-p['t'])//step-1}
            for p,n in zip(bars,bars[1:]) if n['t']-p['t'] > step]
    latest = bars[-1]['t'] if bars else None
    return {'symbol': symbol, 'resolution': resolution, 'bars': bars, 'gaps': gaps,
            'verified_files': checked_files, 'last_candle_epoch': latest,
            'age_minutes': round(max(0, time.time()-(latest+step))/60, 1) if latest is not None else None,
            'reason': None if bars else 'NO_VERIFIED_REAL_BARS',
            'note': 'Actual, SHA256-verified archived OHLCV. Gaps never interpolated. Derived full buckets are labeled by timeframe.'}


def forecasts(root, symbol=None, limit=40):
    db = _sql(root, 'forward_observations.sqlite')
    if db is None:
        return {'rows': [], 'counts': {}, 'real_quotes': 0}
    try:
        w = 'WHERE f.symbol=?' if symbol else ''
        rows = _rows(db, f'''SELECT f.id,f.symbol,f.feature_end_ts,f.model_sha256,f.q10,f.q50,f.q90,
                          f.horizon_seconds, f.status,f.due_epoch,q.observed_epoch,q.best_ask,q.best_bid,
                          o.actual_mid_log_return,o.observed_ask_to_future_bid_net_log_return
                          FROM forecasts f JOIN quotes q ON q.id=f.origin_quote_id
                          LEFT JOIN outcomes o ON o.forecast_id=f.id {w}
                          ORDER BY q.observed_epoch DESC LIMIT ?''', ((symbol, limit) if symbol else (limit,)))
        counts = _rows(db, 'SELECT status,count(*) AS n FROM forecasts GROUP BY status')
        quotes = _one(db, 'SELECT count(*) AS n FROM quotes').get('n', 0)
        for row in rows:
            row['model_sha256'] = row['model_sha256'][:12]  # sufficient UI label, no secrets
        return {'rows': rows, 'counts': {r['status']: r['n'] for r in counts}, 'real_quotes': quotes,
                'note': 'Only actual time-stamped forecast receipts; future results require later actual quotes.'}
    finally:
        db.close()


def shadow(root, symbol=None, limit=80):
    db = _sql(root, 'shadow.sqlite')
    if db is None:
        return {'events': [], 'positions': [], 'cash_tmn': None, 'initial_tmn': None, 'number_of_paper_trades': 0}
    try:
        where = 'WHERE symbol=?' if symbol else ''
        evs = _rows(db, f'SELECT id,observed_at,symbol,action,payload FROM events {where} ORDER BY id DESC LIMIT ?',
                    (symbol, limit) if symbol else (limit,))
        for item in evs:
            p = _read_json_str(item.pop('payload'))
            pred = p.get('forecast') if isinstance(p.get('forecast'), dict) else {}
            expl = p.get('model_prediction') if isinstance(p.get('model_prediction'), dict) else {}
            chosen = pred or expl
            item['q10'] = _finite((chosen.get('quantile_log_returns') or {}).get('q10'))
            item['q50'] = _finite((chosen.get('quantile_log_returns') or {}).get('q50'))
            item['q90'] = _finite((chosen.get('quantile_log_returns') or {}).get('q90'))
            item['veto_reasons'] = p.get('veto_reasons', [])
            item['reason'] = p.get('error') or p.get('status') or item['action']
            item['quote'] = p.get('quote') or {}
            item['paper_cash_tmn'] = _finite(p.get('paper_cash_tmn'))
            item['model'] = (chosen.get('model') or None)
        kv = {r['key']: r['value'] for r in _rows(db,'SELECT key,value FROM kv')}
        positions = _rows(db, 'SELECT symbol,quantity,entry_cost,entry_price,entry_at FROM positions')
        number_trades = _one(db, "SELECT count(*) AS n FROM events WHERE action IN ('PAPER_BUY','PAPER_SELL','PAPER_END_OF_WATCH_SELL')").get('n', 0)
        return {'events': evs, 'positions': positions,
                'cash_tmn': _finite(kv.get('cash_tmn')),
                'initial_tmn': _finite(kv.get('starting_tmn')),
                'high_water_tmn': _finite(kv.get('high_water_tmn')),
                'stopped': kv.get('stopped') == '1',
                'number_of_paper_trades': number_trades,
                'note': 'PAPER ONLY; no verified real Wallex fills. Unrealized positions cannot be valued without fresh genuine bids.'}
    finally:
        db.close()


def news(root, symbol=None, limit=30):
    db = _sql(root, 'news.sqlite')
    if db is None:
        return {'rows': [], 'note': 'No actual archived news receipts'}
    try:
        rows = _rows(db, '''SELECT title,url,source,published_at,first_observed_at,
                            available_at,sentiment FROM articles ORDER BY first_observed_at DESC LIMIT ?''', (limit,))
        base = (symbol[:-3] if symbol.endswith('TMN') else symbol[:-4] if symbol.endswith('USDT') else symbol) if symbol else ''
        aliases = {'BTC': ('bitcoin', 'btc'), 'ETH': ('ethereum', 'eth'), 'XRP': ('ripple','xrp'),
                   'DOGE': ('dogecoin','doge'), 'SOL': ('solana','sol'), 'ADA': ('cardano','ada'),
                   'USDT': ('tether', 'usdt'), 'PEPE': ('pepe',), 'TRX': ('tron','trx'),
                   'BNB': ('bnb','binance coin')}
        keywords = aliases.get(base, (base.lower(),) if base else ())
        for r in rows:
            sentiment = None
            if isinstance(r.get('sentiment'), str):
                try: sentiment = json.loads(r['sentiment'])
                except (ValueError, TypeError): pass
            if isinstance(sentiment, list):
                sentiment = [{k:x.get(k) for k in ('label','score')} for x in sentiment if isinstance(x,dict)]
            else:
                sentiment = None
            r['sentiment'] = sentiment
            r['symbol_title_match'] = bool(base and any(re.search(r'(?<![a-z])'+re.escape(word)+r'(?![a-z])',r['title'].lower()) for word in keywords))
            r['trade_effect'] = 'NOT_VALIDATED_OR_USED_BY_CHAMPION'
            r['available_for_decision'] = bool(r['available_at'])
        return {'rows': rows,
                'model_uses_news': False,
                'note': 'Sentiment, if present, describes article title ONLY; no causal price impact or news-conditioned trades have been established.'}
    finally:
        db.close()


def strategies(root, symbol=None, limit=25):
    path = Path(root)/'research'/'chronological_winners.csv'
    if not path.is_file():
        return {'rows':[], 'note':'No historical verified-candle strategy benchmark file'}
    rows = []
    try:
        with path.open(encoding='utf8',newline='') as f:
            for row in csv.DictReader(f):
                if symbol and row.get('symbol')!=symbol:
                    continue
                for k in ('train_return_pct','holdout_return_pct','holdout_max_trade_dd_pct','holdout_win_rate'):
                    row[k] = _finite(row.get(k))
                rows.append({k:row.get(k) for k in ('symbol','strategy','train_return_pct','holdout_return_pct',
                          'holdout_trades','holdout_max_trade_dd_pct','holdout_win_rate','train_end_ts','holdout_start_ts')})
    except (OSError, ValueError):
        pass
    return {'rows': rows[:limit], 'generated_from': str(path.name),
            'note':'Historical hypothetical next-open trades, assumed fee/slippage, multiple-testing bias; NOT executed PnL or independently validated Champion.'}


_account_cache = {'at': 0., 'payload': None}
def _existing_api_key(root):
    # Environment ONLY. Never discover credentials from files, including .env/pass.
    return os.environ.get('WALLEX_API_KEY','').strip()

def real_account(root):
    # Read-only private endpoint is optional; never request or display the key.
    now = time.time()
    if now - _account_cache['at'] < 60 and _account_cache['payload'] is not None:
        return _account_cache['payload']
    api_key=_existing_api_key(root)
    if not api_key:
        return {'connected': False, 'reason': 'WALLEX_API_KEY_NOT_EXPORTED_TO_DASHBOARD_PROCESS',
                'account_binding_verified': False, 'real_fills_available': False}
    try:
        from .wallex_api import WallexReadClient
        client = WallexReadClient(api_key=api_key)
        balances = client.balances_detail()
        nonzero = {k:{'available':_finite(v.get('available')),'total':_finite(v.get('total')),
                      'freeze':_finite(v.get('freeze'))} for k,v in balances.items()
                   if _finite(v.get('total')) is not None and _finite(v.get('total'))>0}
        result = {'connected': True, 'read_at_utc': datetime.now(timezone.utc).isoformat(),
                  'nonzero_balances':nonzero, 'account_binding_verified':False,
                  'real_fills_available':False,
                  'warning':'The API key may point to a non-contest account; do not label holdings contest portfolio until independently verified.'}
    except Exception as exc:
        result = {'connected':False,'reason':type(exc).__name__,
                  'account_binding_verified':False, 'real_fills_available':False}
    _account_cache.update(at=now,payload=result)
    return result


def summary(root):
    root = Path(root)
    ct = _catalog(root)
    state = _read_json(root/'watch_session.json', {}) or {}
    champion = _read_json(root/'models'/'active_champion.json', {}) or {}
    paper = shadow(root, limit=1)
    forecast_db = _sql(root, 'forward_observations.sqlite')
    if forecast_db is not None:
        try:
            forward = {'quotes':_one(forecast_db, 'SELECT count(*) AS n FROM quotes').get('n',0),
                       'forecasts':_one(forecast_db, 'SELECT count(*) AS n FROM forecasts').get('n',0),
                       'scored':_one(forecast_db, 'SELECT count(*) AS n FROM outcomes').get('n',0)}
        finally: forecast_db.close()
    else:
        forward = {'quotes':0,'forecasts':0,'scored':0}
    ndb = _sql(root,'news.sqlite')
    if ndb is None:
        news_count = 0
    else:
        try:news_count=_one(ndb,'SELECT count(*) AS n FROM articles').get('n',0)
        finally:ndb.close()
    age = None
    if state.get('last_cycle_finished_utc'):
        try:age=round((time.time()-datetime.fromisoformat(state['last_cycle_finished_utc']).timestamp())/60,1)
        except (ValueError,TypeError):pass
    context_db=_sql(root,'context_memory.sqlite')
    if context_db is None:
        context_count=0
    else:
        try: context_count=_one(context_db,'SELECT count(*) AS n FROM context_events').get('n',0)
        finally:context_db.close()
    research=_read_json(root/'reports'/'dashboard_research_eval.json', {}) or {}
    return {'agent':{'context_events':context_count,'news_entering_model':False,
                      'langgraph_runs_in_watch':False,'technical_indicators_gate_watch_trades':False,
                      'strategy_benchmark_stored':(root/'research'/'chronological_winners.csv').is_file(),
                      'retrospective_last_run_utc':research.get('generated_at_utc')},
            'mode':'READ_ONLY_RESEARCH_SHADOW','server_utc':datetime.now(timezone.utc).isoformat(),
            'catalog':ct,'watch':{'status':state.get('status','NOT_STARTED'),
                'hours':state.get('hours'), 'cycles_completed':state.get('cycles_completed',0),
                'last_cycle_finished_utc':state.get('last_cycle_finished_utc'),
                'last_cycle_age_minutes':age,'deadline_epoch':state.get('deadline_epoch')},
            'champion':{'architecture':champion.get('selected_architecture'),
                'name':champion.get('selected_checkpoint'),'validation_pinball':champion.get('validation_pinball'),
                'economic_performance_established':False},
            'shadow':{'cash_tmn':paper['cash_tmn'],'positions_count':len(paper['positions']),
                'trades_count':paper['number_of_paper_trades'],'stopped':paper.get('stopped',False)},
            'news_count':news_count,'forward':forward,
            'warnings':['No real Wallex trades are sent by Atlas V3.4.',
                        'News has not been wired as a model input.',
                        'No claim of profitable historical Champion backtest or 48h confirmed real PnL.']}


class DashboardHandler(BaseHTTPRequestHandler):
    server_version = 'WallexAtlasDashboard/3.5'
    def __init__(self, *args, root=None, **kwargs):
        self.root = Path(root).resolve()
        super().__init__(*args, **kwargs)

    def log_message(self, fmt, *args):
        # No query arguments or API secrets logged. Keep server terminal readable.
        if args and isinstance(args[0], str) and args[0].startswith('GET /api/'):
            return
        super().log_message(fmt, *args)

    def _json(self, obj, status=200):
        payload = json.dumps(obj, ensure_ascii=False, allow_nan=False, separators=(',',':')).encode('utf8')
        self.send_response(status)
        self.send_header('Content-Type','application/json; charset=utf-8')
        self.send_header('Cache-Control','no-store')
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Content-Security-Policy',"default-src 'none'; frame-ancestors 'none'")
        self.send_header('Content-Length',str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _page(self):
        path=Path(__file__).resolve().parent / 'atlas_dashboard.html'
        data=path.read_bytes()
        self.send_response(200)
        self.send_header('Content-Type','text/html; charset=utf-8')
        self.send_header('Cache-Control','no-store')
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Content-Security-Policy', "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; connect-src 'self'; img-src 'self' data:; object-src 'none'; frame-ancestors 'none'")
        self.send_header('Content-Length',str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        # Localhost-only; reject DNS-rebinding Host requests.
        host=self.headers.get('Host','').split(':')[0].lower()
        if host not in ('127.0.0.1','localhost'):
            return self._json({'error':'HOST_NOT_ALLOWED'},403)
        parsed = urlparse(self.path)
        path = parsed.path
        if path in ('/','/index.html'):
            return self._page()
        if not path.startswith('/api/'):
            return self._json({'error':'NOT_FOUND'},404)
        params=parse_qs(parsed.query)
        sym=params.get('symbol',[''])[0]
        if sym and not SYMBOL_RE.fullmatch(sym):
            return self._json({'error':'INVALID_SYMBOL'},400)
        try:
            if path=='/api/summary': result=summary(self.root)
            elif path=='/api/candles':
                res=params.get('resolution',['15'])[0]
                result=candles(self.root,sym or 'BTCTMN',res)
            elif path=='/api/forecasts':result=forecasts(self.root,sym or None)
            elif path=='/api/shadow':result=shadow(self.root,sym or None)
            elif path=='/api/news':result=news(self.root,sym or None)
            elif path=='/api/strategies':result=strategies(self.root,sym or None)
            elif path=='/api/account':result=real_account(self.root)
            elif path=='/api/research':result=_read_json(self.root/'reports'/'dashboard_research_eval.json', {'status':'NOT_RUN'})
            else:return self._json({'error':'NOT_FOUND'},404)
            return self._json(result)
        except ValueError as exc:
            return self._json({'error':'INVALID_REQUEST','reason':str(exc)[:100]},400)
        except (sqlite3.Error,OSError,RuntimeError,KeyError) as exc:
            # No exchange keys, local absolute paths or stack traces exposed.
            return self._json({'error':'SOURCE_UNAVAILABLE','type':type(exc).__name__},503)


def main(argv=None):
    p=argparse.ArgumentParser(description='Wallex Atlas read-only offline-friendly dashboard')
    p.add_argument('--root', default=os.environ.get('WALLEX_ATLAS_HOME','atlas_store'))
    p.add_argument('--port',type=int,default=8765)
    args=p.parse_args(argv)
    if not 1024 <= args.port <= 65535:raise ValueError('Port out of allowed range')
    server=ThreadingHTTPServer(('127.0.0.1',args.port),partial(DashboardHandler,root=args.root))
    print(f'Wallex Atlas Dashboard READ ONLY: http://127.0.0.1:{args.port}',flush=True)
    print('Reads existing genuine market files; does not start, stop, or change watch.',flush=True)
    try:server.serve_forever(poll_interval=.5)
    except KeyboardInterrupt:pass
    finally:server.server_close()

if __name__=='__main__':main()
