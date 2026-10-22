"""Real Wallex public WebSocket trade tape, append-only with observed-at timestamps.
No order tools or synthetic trades. Official endpoint wss://api.wallex.ir/ws.
"""
from __future__ import annotations
import json, time, hashlib
from pathlib import Path
from datetime import datetime,timezone

ENDPOINT='wss://api.wallex.ir/ws'

def capture(lake,minutes=10,max_markets=12):
    if not 1<=minutes<=4320 or not 1<=max_markets<=24:raise ValueError('Invalid capture budget')
    try:from websockets.sync.client import connect
    except ImportError as e:raise RuntimeError('Install websockets>=12 to capture live real trade tape') from e
    from .atlas_agent import select_symbol
    metas=[]
    for (raw,) in lake.db.execute('SELECT metadata FROM assets'):
        m=json.loads(raw)
        if m.get('is_spot') is not True or m.get('quote_asset')!='TMN':continue
        try:vol=float(m.get('quote_volume_24h') or 0)
        except (ValueError,TypeError):vol=0
        metas.append((vol,m['symbol']))
    symbols=[s for _,s in sorted(metas,reverse=True)[:max_markets]]
    if not symbols:raise RuntimeError('Discover active Wallex spot markets first')
    folder=lake.root/'live_trade_tapes';folder.mkdir(exist_ok=True)
    target=folder/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'.jsonl')
    deadline=time.monotonic()+minutes*60; n=0;failure_count=0
    with target.open('a',encoding='utf-8',buffering=1) as output:
        while time.monotonic()<deadline:
            try:
                with connect(ENDPOINT,open_timeout=15,close_timeout=5) as ws:
                    for sym in symbols:ws.send(json.dumps(['subscribe',{'channel':sym+'@trade'}]))
                    while time.monotonic()<deadline:
                        try:message=ws.recv(timeout=5)
                        except TimeoutError:continue
                        received=datetime.now(timezone.utc).isoformat()
                        try:obj=json.loads(message)
                        except ValueError:continue
                        # Only actual exchange trade channels, not subscription acks/errors.
                        if not isinstance(obj,list) or len(obj)!=2 or not isinstance(obj[0],str) or not obj[0].endswith('@trade'):
                            continue
                        if obj[0].split('@')[0] not in symbols:continue
                        trade=obj[1]
                        if not isinstance(trade,dict) or not all(k in trade for k in ('price','quantity','timestamp','isBuyOrder')):
                            continue
                        row={'observed_at_utc':received,'origin':'wallex_websocket_trade',
                             'channel':obj[0],'exchange_trade':trade}
                        output.write(json.dumps(row,ensure_ascii=False,sort_keys=True)+'\n');n+=1
            except (OSError,ConnectionError,TimeoutError) as e:
                failure_count+=1
                output.write(json.dumps({'received_at_utc':datetime.now(timezone.utc).isoformat(),
                     'type':'CONNECTION_INTERRUPTED','exception_class':type(e).__name__},sort_keys=True)+'\n')
                time.sleep(min(30,2**min(failure_count,4)))
    digest=hashlib.sha256(target.read_bytes()).hexdigest()
    with lake.db:
        lake.db.execute('INSERT INTO provenance(kind,sha256,path,observed_at) VALUES(?,?,?,?)',
                        ('RAW_WALLEX_LIVE_TRADES',digest,target.relative_to(lake.root).as_posix(),
                         datetime.now(timezone.utc).isoformat()))
    return {'captured_real_trades':n,'connection_interruptions':failure_count,
            'file':str(target),'sha256':digest,'subscribed_symbols':symbols}
