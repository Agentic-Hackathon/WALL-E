"""WALL-E localhost read-only console on existing stdlib dashboard stack.

Actual archive/SQLite/public research reports only. No network, secret discovery,
process launch, arbitrary export path, order transport or frozen-session resume.
"""
import argparse,hashlib,json,sqlite3,time,secrets
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
    bars=sorted(rows,key=lambda r:r['timestamp'])[-240:]
    # Chart diagnostics reuse the versioned feature recipe, NEVER the trading
    # recipe. A gap resets warmup; do not join a rolling indicator across it.
    indicators=[];technical=None;definitions=[]
    if bars:
        import pandas as pd
        from .atlas_feature_registry import compute_ohlcv_features,registry_payload
        from .atlas_technical_evidence import compute
        frame=pd.DataFrame(bars);period=RESOLUTIONS[resolution]
        breaks=frame.timestamp.diff().ne(period)
        frame=frame.loc[breaks[breaks].index[-1]:].copy().reset_index(drop=True)
        features=compute_ohlcv_features(frame)
        mid=frame.close.rolling(20).mean();std=frame.close.rolling(20).std()
        features['bb_upper']=mid+2*std;features['bb_lower']=mid-2*std
        indicators=json.loads(features.to_json(orient='records'))
        technical=compute(frame,period)
        definitions=registry_payload()['definitions']
    return {'status':'VERIFIED_CLOSED_REAL_CANDLES' if bars else 'DATA_NOT_AVAILABLE','bars':bars,'resolution':resolution,
        'indicators':indicators,'technical':technical,'feature_definitions':definitions,
        'indicator_policy':'CONTIGUOUS_SUFFIX_ONLY_WARMUP_NULL_NO_IMPUTATION_RESEARCH_ONLY'}

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


def pattern_search(root,symbol='BTCTMN',resolution='15',length=10,method='euclidean',scope='same',k=8):
    """On-demand research over the existing immutable SciPy/DTW index.

    Reuses atlas_patterns (source/licensing in that module), archive SHA/grid
    verification and receipt-aware cutoff. No rebuilding, network or trade path.
    """
    from types import SimpleNamespace
    from .atlas_patterns import PatternIndex,make_query,HORIZONS,RESOLUTIONS as PATTERN_RESOLUTIONS
    from .atlas_feature_health import _verified_segments
    from .atlas_archive import period_seconds
    if (not SYMBOL_RE.fullmatch(symbol) or resolution not in PATTERN_RESOLUTIONS or
        length not in (7,10,16,24) or method not in ('euclidean','dtw','return_structure') or
        scope not in ('same','all') or not 2<=k<=12):raise ValueError('INVALID_PATTERN_SEARCH')
    root=Path(root).resolve();folder=root/'research_challengers/milestone8/pattern_index_v1'
    empty={'status':'DATA_NOT_AVAILABLE','matches':[],'query':None,'research_only':True,'decision_path_eligible':False}
    if not (root/'catalog.sqlite').is_file() or not (folder/'patterns.sqlite').is_file():return empty
    db=sqlite3.connect((root/'catalog.sqlite').as_uri()+'?mode=ro',uri=True,timeout=20)
    index=PatternIndex(folder,readonly=True)
    try:
        index.verify_sources();manifest=index.manifest()
        if length not in manifest['lengths'] or resolution not in manifest['resolutions']:
            return {**empty,'status':'WINDOW_NOT_INDEXED','indexed_lengths':manifest['lengths'],'indexed_resolutions':manifest['resolutions']}
        lake=SimpleNamespace(root=root,db=db)
        try:query=make_query(lake,symbol,resolution,length)
        except ValueError as exc:
            return {**empty,'status':'QUERY_UNAVAILABLE','reason':str(exc)}
        result=index.search(query,method=method,scope=scope,k=k,min_matches=2)
        cache={};step=period_seconds(resolution)
        def bars_for(asset,start,end):
            if asset not in cache:cache[asset]=_verified_segments(root,db,asset,resolution)[0]
            # A whole contiguous segment must cover both pattern and outcome.
            for part in cache[asset]:
                frame=part[(part.timestamp>=start)&(part.timestamp<end)]
                if len(frame)==round((end-start)/step) and len(frame) and int(frame.timestamp.iloc[0])==start:
                    return [{key:float(row[key]) for key in ('timestamp','open','high','low','close','volume')} for row in frame.to_dict('records')]
            raise ValueError('PATTERN_DISPLAY_CANDLES_NOT_CONTIGUOUS')
        current=bars_for(symbol,query['start'],query['end'])
        matches=[]
        for match in result['matches']:
            row=index.db.execute('SELECT payload,sha256 FROM patterns WHERE id=?',(match['pattern_id'],)).fetchone()
            if not row or digest(json.loads(row[0]))!=row[1]:raise ValueError('PATTERN_DISPLAY_HASH_INVALID')
            p=json.loads(row[0]);bars=bars_for(match['symbol'],match['start'],match['outcome_end'])
            matches.append({**match,'bars':bars[:length],'future_bars':bars[length:],
                'normalized_close':[100*b['close']/bars[0]['close'] for b in bars],
                'normalization':'FIRST_PATTERN_CLOSE_100_DISPLAY_ONLY',
                'availability_policy':p['availability_policy']})
        age=max(0,query['decision_time']-query['end'])
        return {**result,'matches':matches,'query':{**query,'bars':current,
                'normalized_close':[100*b['close']/current[0]['close'] for b in current]},
                'query_age_seconds':age,'freshness':'RECENT_CLOSED_ARCHIVE' if age<=2*step else 'STALE_ARCHIVE_NOT_CURRENT_MARKET',
                'indexed_lengths':manifest['lengths'],'indexed_resolutions':manifest['resolutions'],
                'observed_at':time.time(),'horizons':list(HORIZONS),'research_only':True,
                'distance_policy':'LOWER_IS_MORE_SIMILAR_NOT_PROBABILITY',
                'future_policy':'MATCH_OUTCOMES_END_BEFORE_QUERY_START_WITH_EMBARGO',
                'archive_only_no_network':True}
    finally:index.close();db.close()

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
            ('Content-Security-Policy',"default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; connect-src 'self'; img-src 'self' data:; object-src 'none'; frame-ancestors 'none'")]:self.send_header(key,value)
        self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
    def do_GET(self):
        if self.headers.get('Host','').split(':')[0] not in ('localhost','127.0.0.1'):return self._json({'error':'HOST_NOT_ALLOWED'},403)
        parsed=urlparse(self.path);args=parse_qs(parsed.query)
        try:
            if parsed.path=='/':return self._page()
            if parsed.path in ('/static/fonts/Vazirmatn.woff2','/static/fonts/OFL.txt','/static/console_v2.js','/static/console_v2.css'):
                path=Path(__file__).parent/parsed.path.lstrip('/');data=path.read_bytes()
                self.send_response(200);self.send_header('Content-Type',{'.woff2':'font/woff2','.js':'text/javascript; charset=utf-8','.css':'text/css; charset=utf-8'}.get(path.suffix,'text/plain; charset=utf-8'))
                self.send_header('Cache-Control','public, max-age=86400' if path.suffix=='.woff2' else 'no-store');self.send_header('X-Content-Type-Options','nosniff')
                self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data);return
            if parsed.path=='/api/overview':result=overview(self.root)
            elif parsed.path=='/api/finance':
                from .atlas_finance import status
                result=status(self.root)
                result['control']=self.server.finance_control.state() if hasattr(self.server,'finance_control') else {'status':'DISABLED'}
            elif parsed.path=='/api/research-token':result={'token':getattr(self.server,'research_token',None)}
            elif parsed.path=='/api/tools':result=inventory()
            elif parsed.path=='/api/news':result=real_news(self.root)
            elif parsed.path=='/api/observations':result=observations(self.root)
            elif parsed.path=='/api/candles':result=real_candles(self.root,args.get('symbol',['BTCTMN'])[0],args.get('resolution',['15'])[0])
            elif parsed.path=='/api/pattern-lines':result=pattern_lines(self.root)
            elif parsed.path=='/api/pattern-search':result=pattern_search(self.root,
                args.get('symbol',['BTCTMN'])[0],args.get('resolution',['15'])[0],
                int(args.get('length',['10'])[0]),args.get('method',['euclidean'])[0],
                args.get('scope',['same'])[0],int(args.get('k',['8'])[0]))
            elif parsed.path=='/api/report':result=public_report(args.get('name',[''])[0])
            else:return self._json({'error':'NOT_FOUND'},404)
            return self._json(result)
        except ValueError as exc:return self._json({'status':'INVALID_OR_UNVERIFIED_SOURCE','type':type(exc).__name__},400)
        except (OSError,sqlite3.Error,KeyError,RuntimeError) as exc:return self._json({'status':'DATA_NOT_AVAILABLE','type':type(exc).__name__},503)
    def do_POST(self):
        if self.path!='/api/research-control':return self._json({'error':'READ_ONLY_NO_ORDER_OR_PROCESS_CONTROL'},405)
        host=self.headers.get('Host','');origin=self.headers.get('Origin','')
        if host not in ('127.0.0.1:'+str(self.server.server_port),'localhost:'+str(self.server.server_port)) or origin!='http://'+host:
            return self._json({'error':'SAME_ORIGIN_REQUIRED'},403)
        token=getattr(self.server,'research_token',None)
        if not token or not secrets.compare_digest(self.headers.get('X-Research-Token',''),token):return self._json({'error':'TOKEN_REQUIRED'},403)
        try:
            size=int(self.headers.get('Content-Length','0'))
            if not 0<size<=128:raise ValueError('BOUNDED_BODY_REQUIRED')
            value=json.loads(self.rfile.read(size))
            if set(value)!={'action'}:raise ValueError('ONLY_FIXED_RESEARCH_ACTION')
            return self._json(self.server.finance_control.command(value['action']))
        except (ValueError,RuntimeError,OSError,KeyError) as exc:
            return self._json({'status':'RESEARCH_BLOCKED','type':type(exc).__name__},409)
    def do_DELETE(self):self._json({'error':'NO_FINANCIAL_CONTROL'},405)

def main():
    p=argparse.ArgumentParser();p.add_argument('--root',default='atlas_store');p.add_argument('--port',type=int,default=8766);a=p.parse_args()
    if not 1024<=a.port<=65535:raise ValueError('INVALID_PORT')
    server=ThreadingHTTPServer(('127.0.0.1',a.port),partial(ConsoleHandler,root=a.root))
    from .atlas_finance_control import FinanceControl
    server.finance_control=FinanceControl(a.root);server.research_token=secrets.token_urlsafe(32)
    print('WALL-E READ_ONLY / LIVE HARD_DISABLED http://127.0.0.1:'+str(a.port),flush=True)
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:server.finance_control.close();server.server_close()

if __name__=='__main__':main()
