"""Original chart adapters, reusing Atlas's verified archive and rule signals.

Presentation references: FinRL paper arXiv:2011.09607v2 figures 4/5 and
AI4Finance-Foundation/FinRL (MIT). No charts, performance data or source copied;
no FinRL model is trained/executed. Existing atlas_signals/features/strategies,
hash verification and actual decision receipts are reused, not reimplemented.
Historical OPEN scenarios are hypothetical, never exchange executions or the
Champion strategy. Agent roles have no separately measured trading returns.
"""
import argparse
import json
import math
from pathlib import Path
import sqlite3
import time
from functools import partial
from http.server import ThreadingHTTPServer
from urllib.parse import urlparse,parse_qs
from wallex_bot.atlas_console import ConsoleHandler,digest
from wallex_bot.atlas_feature_health import _verified_segments
from wallex_bot.atlas_signals import features,strategies,trade_path
from wallex_bot.atlas_risk import RiskLimits

RULES=('sma_9_20','macd_trend','rsi_reversion_30')
INITIAL=5_000_000


def scenario(frame,signal,begin,end,fee=.003,slippage=.0005):
    """Fixed 10% sleeve, one position, next observed OPEN, three-bar exit.

    Existing trade_path determines causal timestamps. No historical book was
    recorded here: liquidity is unknown and this is NOT RiskGate authorization.
    Equity marks observed CLOSE less assumed exit costs while holding.
    """
    p=trade_path(frame,signal,begin,end,hold=3,fee=fee,slippage=slippage)
    entries={e['entry_ts']:e for e in p['events']};exits={e['exit_ts']:e for e in p['events']}
    cash=float(INITIAL);qty=0.;basis=0.;curve=[];events=[];peak=cash;stopped=False
    limits=RiskLimits()
    for i in range(begin,end):
        b=frame.iloc[i];stamp=int(b.timestamp)
        if stamp in entries and not stopped and not qty:
            budget=min(cash*limits.max_cash_fraction_per_entry,limits.max_order_notional_tmn)
            if budget>=limits.min_order_notional_tmn:
                qty=budget/(float(b.open)*(1+slippage)*(1+fee));cash-=budget;basis=budget
                events.append({'timestamp':stamp,'side':'BUY','price':float(b.open),'quantity':qty,'hypothetical':True})
        if stamp in exits and qty:
            proceeds=qty*float(b.open)*(1-slippage)*(1-fee)
            events.append({'timestamp':stamp,'side':'SELL','price':float(b.open),'quantity':qty,'pnl_tmn':proceeds-basis,'hypothetical':True})
            cash+=proceeds;qty=0.
        nav=cash+qty*float(b.close)*(1-slippage)*(1-fee)
        peak=max(peak,nav);dd=100*(nav/peak-1)
        if -dd>=100*limits.max_drawdown_fraction:stopped=True
        curve.append({'timestamp':stamp+900,'nav_tmn':nav,'drawdown_pct':dd})
    return {'curve':curve,'events':events,'net_pnl_tmn':curve[-1]['nav_tmn']-INITIAL if curve else None,
        'execution':'HYPOTHETICAL_NEXT_OPEN_NOT_VERIFIED_LIQUIDITY','fee_per_side_assumed':fee,
        'slippage_per_side_assumed':slippage,'champion_or_riskgate_execution':False}


def evidence(root,start,end,symbol):
    """Read actual session records only; a role recommendation is not a fill."""
    rows=[];seen=set();base=Path(root)/'research_challengers/milestone8'
    for path in sorted(base.glob('*/agentic_decisions.sqlite')):
        db=sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True)
        try:
            exists=db.execute("SELECT 1 FROM sqlite_master WHERE name='agentic_decisions_v8'").fetchone()
            if not exists:continue
            for key,raw,sha in db.execute('SELECT id,payload,sha256 FROM agentic_decisions_v8 WHERE created>=? AND created<=? AND symbol=? ORDER BY created LIMIT 5000',(start,end,symbol)):
                p=json.loads(raw)
                if digest(p)!=sha:raise ValueError('DECISION_HASH_INVALID')
                identity=(path.parent.name,key)
                if identity in seen:continue
                seen.add(identity)
                review=p['review'];agents=review.get('agents',[])
                rows.append({'timestamp':p['evidence']['decision_time'],'session':path.parent.name,
                    'action':p['intent']['action'],'reason':p['receipt']['reason'],
                    'nav_tmn':p['receipt']['after']['nav_tmn'],
                    'agents':[{'role':a.get('agent_name',a.get('role')),'recommendation':a.get('recommendation'),
                               'status':a.get('status')} for a in agents]})
        finally:db.close()
    return sorted(rows,key=lambda x:(x['timestamp'],x['session']))


def charts(root,symbol='BTCTMN',start=None,end=None):
    if symbol not in ('BTCTMN','ETHTMN'):raise ValueError('MARKET_NOT_ALLOWED')
    root=Path(root).resolve();dbfile=root/'catalog.sqlite'
    empty={'bars':[],'rules':{},'agent_decisions':[],'status':'NO_REAL_DATA'}
    if not dbfile.is_file():return empty
    db=sqlite3.connect(dbfile.as_uri()+'?mode=ro',uri=True)
    try:parts,_=_verified_segments(root,db,symbol,'15')
    finally:db.close()
    parts=[p[p.timestamp+900<=time.time()] for p in parts];parts=[p for p in parts if len(p)]
    if not parts:return empty
    latest=max(int(p.timestamp.iloc[-1])+900 for p in parts)
    end=latest if end is None else float(end);start=end-48*3600 if start is None else float(start)
    if not all(math.isfinite(x) for x in (start,end)) or not 0<end-start<=7*86400 or end>time.time()+1:raise ValueError('INVALID_DATE_RANGE')
    # No best-profit segment selection or silent stitching across missing bars.
    eligible=[p for p in parts if int(p.timestamp.iloc[0])<=start and int(p.timestamp.iloc[-1])+900>=end]
    bars=[]
    for part in parts:
        bars.extend({k:float(row[k]) for k in ('timestamp','open','high','low','close','volume')} for row in part[(part.timestamp>=start)&(part.timestamp+900<=end)].to_dict('records'))
    bars.sort(key=lambda b:b['timestamp']);result={**empty,'bars':bars,'requested_start':start,'requested_end':end,
        'symbol':symbol,'observed_at':time.time(),'status':'MISSING_CONTIGUOUS_HISTORY',
        'agent_decisions':evidence(root,start,end,symbol),'initial_hypothetical_tmn':INITIAL,
        'source':'SHA_VERIFIED_WALLEX_ARCHIVE','reference':'arxiv:2011.09607v2; design only, NOT FinRL results'}
    if not eligible:return result
    frame=max(eligible,key=lambda p:int(p.timestamp.iloc[0])).reset_index(drop=True)
    begin=int(frame.index[frame.timestamp>=start][0]);end_index=int((frame.timestamp+900<=end).sum())
    if begin<65 or end_index-begin<12:return {**result,'status':'INSUFFICIENT_WARMUP_OR_RANGE'}
    signals=strategies(features(frame))
    result['rules']={name:scenario(frame,signals[name],begin,end_index) for name in RULES}
    observed=frame.iloc[begin:end_index];budget=INITIAL*.1
    quantity=budget/(float(observed.open.iloc[0])*1.0005*1.003)
    hold=[];peak=float(INITIAL)
    for row in observed.itertuples():
        nav=INITIAL-budget+quantity*float(row.close)*.9995*.997;peak=max(peak,nav)
        hold.append({'timestamp':int(row.timestamp)+900,'nav_tmn':nav,'drawdown_pct':100*(nav/peak-1)})
    result['baselines']={'buy_hold_10pct':{'curve':hold,'net_pnl_tmn':hold[-1]['nav_tmn']-INITIAL},
        'cash':{'curve':[{'timestamp':p['timestamp'],'nav_tmn':INITIAL,'drawdown_pct':0.} for p in hold],'net_pnl_tmn':0.}}
    result['status']='HYPOTHETICAL_FIXED_RULES_NOT_CHAMPION'
    return result


class BacktestHandler(ConsoleHandler):
    def do_POST(self):
        return self._json({'error':'READ_ONLY_CHARTS_NO_PROCESS_OR_FINANCIAL_CONTROL'},405)

    def _page(self):
        from wallex_bot import atlas_console
        raw=Path(atlas_console.__file__).with_name('atlas_console.html').read_text(encoding='utf-8')
        raw=raw.replace('</html>','<script src="/backtest-ui.js"></script></html>')
        data=raw.encode();self.send_response(200)
        self.send_header('Content-Type','text/html; charset=utf-8');self.send_header('Cache-Control','no-store')
        self.send_header('X-Content-Type-Options','nosniff');self.send_header('Content-Length',str(len(data)))
        self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; connect-src 'self'; img-src 'self' data:; object-src 'none'; frame-ancestors 'none'")
        self.end_headers();self.wfile.write(data)

    def do_GET(self):
        if self.headers.get('Host','').split(':')[0] not in ('localhost','127.0.0.1'):return self._json({'error':'HOST_NOT_ALLOWED'},403)
        p=urlparse(self.path)
        if p.path=='/backtest-ui.js':
            data=Path(__file__).with_name('view.js').read_bytes();self.send_response(200)
            self.send_header('Content-Type','text/javascript; charset=utf-8');self.send_header('Cache-Control','no-store')
            self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data);return
        if p.path=='/api/backtest-charts':
            a=parse_qs(p.query)
            try:return self._json(charts(self.root,a.get('symbol',['BTCTMN'])[0],a.get('start',[None])[0],a.get('end',[None])[0]))
            except (ValueError,OSError,sqlite3.Error,KeyError):return self._json({'status':'UNVERIFIED_OR_MISSING_DATA'},400)
        return super().do_GET()


def main():
    p=argparse.ArgumentParser();p.add_argument('--root',default='atlas_store');p.add_argument('--port',type=int,default=8769);a=p.parse_args()
    if not 1024<=a.port<=65535:raise ValueError('INVALID_PORT')
    server=ThreadingHTTPServer(('127.0.0.1',a.port),partial(BacktestHandler,root=a.root))
    # This presentation server cannot start/stop studies or send orders.
    server.research_token=None
    print('WALL-E Backtest http://127.0.0.1:'+str(a.port),flush=True)
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:server.server_close()


if __name__=='__main__':main()
