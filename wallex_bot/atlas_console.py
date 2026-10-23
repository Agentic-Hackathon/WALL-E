"""WALL-E localhost read-only console on existing stdlib dashboard stack.

Actual archive/SQLite/public research reports only. No network, secret discovery,
process launch, arbitrary export path, order transport or frozen-session resume.
"""
import argparse,hashlib,json,sqlite3,time
from datetime import datetime,timezone
from functools import partial
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse,parse_qs
from .atlas_dashboard import DashboardHandler,_read_json,_sql,_rows,shadow,_catalog,SYMBOL_RE,RESOLUTIONS
from .atlas_deadline import schedule

WORKSPACE=Path(__file__).resolve().parents[1]
REPORTS={'models':'model_inventory.json','patterns':'m8_pattern_retrieval_results.json','technical':'m8_technical_indicator_audit.json',
 'news':'m8_news_model_integration.json','sync':'m8_startup_sync_audit.json','replay':'m8_backtest_results.json','shadow':'m8_shadow_results.json',
 'rubric':'m8_hackathon_rubric.json','readiness':'live_readiness.json','tests':'m8_followup_test_results.json','publish':'github_publish_audit.json'}

def digest(p):return hashlib.sha256(json.dumps(p,sort_keys=True,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode()).hexdigest()

def public_report(name):
    if name not in REPORTS:raise ValueError('REPORT_NOT_ALLOWLISTED')
    value=_read_json(WORKSPACE/'reports'/REPORTS[name])
    return {'status':'ARCHIVED_RESEARCH_SNAPSHOT' if value is not None else 'DATA_NOT_AVAILABLE','report':REPORTS[name],
        'data':value,'not_current_account_or_live_permission':True}

def inventory():
    import importlib.util
    path=WORKSPACE/'scripts/judge_preflight.py';spec=importlib.util.spec_from_file_location('atlas_judge_tools',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module.tools(WORKSPACE)

def session_source(root):
    folder=Path(root)/'research_challengers/milestone8'
    choices=sorted(folder.glob('formal*/study_contract.json')) if folder.exists() else []
    return choices[-1].parent if choices else None

def observations(root):
    folder=session_source(root)
    if folder is None:return {'status':'DATA_NOT_AVAILABLE','forecasts':[],'decisions':[],'paper':None,'session':None}
    db=_sql(folder,'forward_observations.sqlite')
    try:
        predictions=[]
        for item in _rows(db,'SELECT prediction_id,model,symbol,decision,due,status,payload,payload_sha FROM m6_predictions ORDER BY decision DESC LIMIT 40'):
            payload=json.loads(item.pop('payload'));sha=item.pop('payload_sha')
            if digest(payload)!=sha:raise ValueError('FORECAST_HASH_INVALID')
            item.update(quantiles={k:payload.get(k) for k in ('q10','q50','q90')},model_sha256=payload.get('model_sha256'),
                effective_status='UNSCORED_WINDOW_ELAPSED_NOT_REWRITTEN' if item['status']=='PENDING' and time.time()>item['due']+300 else item['status'])
            predictions.append(item)
        quotes=[]
        for q in _rows(db,'SELECT symbol,observed_epoch,best_bid,best_ask,mid,raw_book,receipt_sha256 FROM quotes ORDER BY observed_epoch DESC LIMIT 10'):
            payload={k:q[k] for k in ('symbol','observed_epoch','best_bid','best_ask','mid')};payload['raw_book']=json.loads(q['raw_book'])
            if digest(payload)!=q['receipt_sha256']:raise ValueError('QUOTE_RECEIPT_HASH_INVALID')
            from .live_scout import _levels
            q.pop('raw_book');q.update(bid_top5=_levels(payload['raw_book'],'bid')[:5],ask_top5=_levels(payload['raw_book'],'ask')[:5],
                age_seconds=time.time()-q['observed_epoch'],status='ARCHIVED_BOOK_NOT_CURRENT_EXECUTION_QUOTE')
            quotes.append(q)
        runtime=_rows(db,'SELECT payload FROM study_runtime_v7 WHERE key=?',('session',))
        lease=_rows(db,'SELECT expires FROM m6_lease WHERE expires>?',(time.time(),))
    finally:
        if db:db.close()
    db=_sql(folder,'agentic_decisions.sqlite')
    try:
        decisions=[]
        for row in _rows(db,'SELECT id,created,symbol,payload,sha256 FROM agentic_decisions_v8 ORDER BY created DESC LIMIT 20'):
            p=json.loads(row['payload'])
            if digest(p)!=row['sha256']:raise ValueError('DECISION_HASH_INVALID')
            # Explicit public evidence subset; no arbitrary DB column/secret export.
            decisions.append({'id':row['id'],'created':row['created'],'symbol':row['symbol'],'action':p['intent']['action'],
                'reason':p['receipt']['reason'],'agents':p['review']['agents'],'cross_review':p['review']['cross_review_messages'],
                'quote_receipt_sha256':p['evidence']['quote_receipt_sha256'],'model_prediction_id':p['intent'].get('prediction_id'),
                'allocation':p['allocation'],'cash_before':p['receipt']['before']['cash_tmn'],'cash_after':p['receipt']['after']['cash_tmn'],
                'nav_at_receipt':p['receipt']['after']['nav_tmn'],'exchange_fill':None,'source_hash':row['sha256'],
                'technical':p['evidence'].get('technical_extended'),'memory':p['evidence'].get('research_memory',[])})
    finally:
        if db:db.close()
    return {'status':'ACTUAL_SAVED_RECEIPTS_NOT_LIVE_PROCESS','session':folder.name,'source_contract':_read_json(folder/'study_contract.json',{}).get('contract_sha256'),
        'forecasts':predictions,'decisions':decisions,'quotes':quotes,'paper':shadow(folder),
        'collector_lease_current':bool(lease),'runtime':json.loads(runtime[0]['payload']) if runtime else None,
        'realized_exchange_pnl':None,'real_account':'NOT_VERIFIED_NO_PRIVATE_READ_FROM_UI'}

def real_news(root):
    db=_sql(root,'news.sqlite')
    try:
        rows=_rows(db,'SELECT s.article_id,d.title,s.source,s.published_at,s.first_observed_at,s.available_at,s.processing_status FROM news_article_status s JOIN news_documents d USING(article_id) ORDER BY s.first_observed_at DESC LIMIT 30')
        return {'rows':rows,'status':'ACTUAL_ARCHIVED_METADATA' if rows else 'DATA_NOT_AVAILABLE','model_license':'FinBERT CC-BY-NC-SA-4.0; contest vote disabled','missing_is_neutral':False}
    finally:
        if db:db.close()

def real_candles(root,symbol,resolution):
    if not SYMBOL_RE.fullmatch(symbol) or resolution not in RESOLUTIONS:raise ValueError('INVALID_MARKET_TIMEFRAME')
    if not (Path(root)/'catalog.sqlite').is_file():return {'status':'DATA_NOT_AVAILABLE','bars':[]}
    from .atlas_feature_health import _verified_segments
    db=_sql(root,'catalog.sqlite')
    try:parts,_=_verified_segments(Path(root),db,symbol,resolution)
    finally:db.close()
    rows=[]
    for part in parts:
        for r in part.tail(240).to_dict('records'):
            if int(r['timestamp'])+RESOLUTIONS[resolution]<=time.time():rows.append({k:float(r[k]) for k in ('timestamp','open','high','low','close','volume')})
    return {'status':'VERIFIED_CLOSED_REAL_CANDLES' if rows else 'DATA_NOT_AVAILABLE','bars':sorted(rows,key=lambda r:r['timestamp'])[-240:],'resolution':resolution}

def pattern_lines(root):
    from .atlas_patterns import PatternIndex
    report=public_report('patterns')['data'] or {};searches=report.get('current_receipt_aware_searches',[])
    folder=Path(root)/'research_challengers/milestone8/pattern_index_v1'
    if not searches or not (folder/'patterns.sqlite').is_file():return {'status':'DATA_NOT_AVAILABLE','series':[]}
    index=PatternIndex(folder,readonly=True)
    try:
        index.verify_sources();series=[]
        for match in searches[0]['matches'][:5]:
            row=index.db.execute('SELECT payload,sha256 FROM patterns WHERE id=?',(match['pattern_id'],)).fetchone()
            if not row:continue
            payload=json.loads(row[0])
            if digest(payload)!=row[1]:raise ValueError('PATTERN_HASH_INVALID')
            if payload['representation']=='relative_ohlcv':
                series.append({'symbol':payload['symbol'],'pattern_id':match['pattern_id'],'values':[r[3] for r in payload['features']],
                    'unit':'window-only log-close / within-window return volatility; NOT return forecast'})
        return {'status':'ACTUAL_IMMUTABLE_PATTERN_FEATURES','series':series,'research_only':True}
    finally:index.close()

def overview(root):
    data=observations(root);clock=_read_json(Path(root)/'operations/clock_receipt.json',{}) or {}
    fresh=0<=time.time()-clock.get('observed_epoch',0)<=120
    return {'mode':'READ_ONLY','LIVE':'HARD_DISABLED','now_utc':datetime.now(timezone.utc).isoformat(),
        'deadline':schedule(clock_verified=fresh and clock.get('verified',False),clock_skew_seconds=clock.get('skew_seconds')),
        'catalog':_catalog(root),'champion':_read_json(Path(root)/'models/active_champion.json',{'status':'DATA_NOT_AVAILABLE'}),
        'observations':data,'real_account':{'status':'NOT_VERIFIED','contest_credit':None,'balance':None,'pnl':None},
        'network':'UI_OFFLINE_READ_ONLY; age of receipts is not current connectivity','data_fabricated':False}

class ConsoleHandler(DashboardHandler):
    def _page(self):
        data=Path(__file__).with_name('atlas_console.html').read_bytes();self.send_response(200)
        for key,value in [('Content-Type','text/html; charset=utf-8'),('Cache-Control','no-store'),('X-Content-Type-Options','nosniff'),
            ('Content-Security-Policy',"default-src 'self'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; connect-src 'self'; img-src 'self' data:; object-src 'none'; frame-ancestors 'none'")]:self.send_header(key,value)
        self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
    def do_GET(self):
        if self.headers.get('Host','').split(':')[0] not in ('localhost','127.0.0.1'):return self._json({'error':'HOST_NOT_ALLOWED'},403)
        parsed=urlparse(self.path);args=parse_qs(parsed.query)
        try:
            if parsed.path=='/':return self._page()
            if parsed.path=='/api/overview':result=overview(self.root)
            elif parsed.path=='/api/tools':result=inventory()
            elif parsed.path=='/api/news':result=real_news(self.root)
            elif parsed.path=='/api/observations':result=observations(self.root)
            elif parsed.path=='/api/candles':result=real_candles(self.root,args.get('symbol',['BTCTMN'])[0],args.get('resolution',['15'])[0])
            elif parsed.path=='/api/pattern-lines':result=pattern_lines(self.root)
            elif parsed.path=='/api/report':result=public_report(args.get('name',[''])[0])
            else:return self._json({'error':'NOT_FOUND'},404)
            return self._json(result)
        except ValueError as exc:return self._json({'status':'INVALID_OR_UNVERIFIED_SOURCE','type':type(exc).__name__},400)
        except (OSError,sqlite3.Error,KeyError,RuntimeError) as exc:return self._json({'status':'DATA_NOT_AVAILABLE','type':type(exc).__name__},503)
    def do_POST(self):self._json({'error':'READ_ONLY_NO_ORDER_OR_PROCESS_CONTROL'},405)
    do_DELETE=do_POST

def main():
    p=argparse.ArgumentParser();p.add_argument('--root',default='atlas_store');p.add_argument('--port',type=int,default=8766);a=p.parse_args()
    if not 1024<=a.port<=65535:raise ValueError('INVALID_PORT')
    server=ThreadingHTTPServer(('127.0.0.1',a.port),partial(ConsoleHandler,root=a.root))
    print('WALL-E READ_ONLY / LIVE HARD_DISABLED http://127.0.0.1:'+str(a.port),flush=True)
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:server.server_close()

if __name__=='__main__':main()
