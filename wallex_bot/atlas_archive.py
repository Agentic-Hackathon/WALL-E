"""Real Wallex research lake. No invented observations, no market mocks.
All-market archival is independent of trade eligibility.
"""
from __future__ import annotations
import hashlib, json, os, sqlite3, time
from datetime import datetime, timezone, timedelta
from pathlib import Path
import pandas as pd
import numpy as np
from . import market

# These are exactly the published/resolved intervals supported by current adapter.
NATIVE = ('1','60','1D')
DERIVED = {
    '5': ('1',5), '15': ('1',15), '30': ('1',30),
    '180': ('60',3), '240': ('60',4), '360': ('60',6),
    '480': ('60',8), '720': ('60',12),
    '2D': ('1D',2),'3D': ('1D',3)}
ALL_RESOLUTIONS = NATIVE + tuple(DERIVED)

def period_seconds(res):
    return market.ALLOWED_RESOLUTIONS.get(res) or (int(res[:-1])*86400 if res.endswith('D') else int(res)*60)


def utcnow():
    return datetime.now(timezone.utc).isoformat()


def sha(path: Path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def root_path():
    return Path(os.environ.get('WALLEX_ATLAS_HOME', 'atlas_store')).resolve()


class Lake:
    def __init__(self, root=None):
        self.root = Path(root or root_path()).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.root/'catalog.sqlite', timeout=30)
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS assets(symbol TEXT PRIMARY KEY, metadata TEXT NOT NULL, observed_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS chunks(id INTEGER PRIMARY KEY, symbol TEXT NOT NULL, resolution TEXT NOT NULL,
            begin INTEGER NOT NULL, end INTEGER NOT NULL, first_ts INTEGER, last_ts INTEGER, rows INTEGER NOT NULL,
            filename TEXT NOT NULL UNIQUE, sha256 TEXT NOT NULL, observed_at TEXT NOT NULL, status TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS idx_chunks ON chunks(symbol,resolution,begin,end);
        CREATE TABLE IF NOT EXISTS incidents(id INTEGER PRIMARY KEY, symbol TEXT,resolution TEXT,begin INTEGER,end INTEGER,
            created_at TEXT NOT NULL,error TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS provenance(id INTEGER PRIMARY KEY, kind TEXT NOT NULL, sha256 TEXT NOT NULL,
            path TEXT NOT NULL, observed_at TEXT NOT NULL);
        ''')
        self.db.commit()

    def close(self): self.db.close()

    def discover(self):
        rows = market.markets()
        now = utcnow()
        with self.db:
            for m in rows:
                symbol = m.get('symbol')
                if isinstance(symbol,str) and symbol.isalnum() and symbol.isupper():
                    self.db.execute('INSERT OR REPLACE INTO assets VALUES(?,?,?)',
                                    (symbol, json.dumps(m,ensure_ascii=False,sort_keys=True),now))
        return {'all_listed':len(rows),'spot':sum(x.get('is_spot') is True for x in rows),
                'tmn_spot':sum(x.get('is_spot') is True and x.get('quote_asset')=='TMN' for x in rows),
                'timestamp':now}

    def symbols(self, scope='all-spot'):
        out=[]
        for (raw,) in self.db.execute('SELECT metadata FROM assets ORDER BY symbol'):
            m=json.loads(raw)
            if scope=='all-listed' or (m.get('is_spot') is True and
                                     (scope!='tmn-spot' or m.get('quote_asset')=='TMN')):
                out.append(m['symbol'])
        return out

    def has(self,symbol,res,begin,end):
        r=self.db.execute('SELECT filename,sha256 FROM chunks WHERE symbol=? AND resolution=? AND begin=? AND end=? AND status=?',
                          (symbol,res,begin,end,'COMPLETE')).fetchone()
        return bool(r and (self.root/r[0]).exists() and sha(self.root/r[0])==r[1])

    def _resample(self,source:pd.DataFrame,src:str,dst:str):
        # Calls original audited exact-bucket aggregator; missing observations never synthesized.
        if src==dst:return source
        if dst in market.ALLOWED_RESOLUTIONS:
            return market.resample_candles(source,src,dst)
        source=market.normalize(source)
        a=period_seconds(src);b=period_seconds(dst)
        if b<=a or b%a:raise ValueError('Cannot safely resample requested periods')
        chunks=[]
        for begin,df in source.assign(_bucket=(source.timestamp//b)*b).groupby('_bucket',sort=True):
            exact=np.arange(int(begin),int(begin+b),a)
            if np.array_equal(df.timestamp.to_numpy(dtype='int64'),exact):
                chunks.append({'timestamp':int(begin),'open':df.open.iloc[0],
                    'high':df.high.max(),'low':df.low.min(),'close':df.close.iloc[-1],
                    'volume':df.volume.sum()})
        if not chunks:raise ValueError('No complete real source buckets')
        return market.normalize(pd.DataFrame(chunks))

    def save(self,symbol,res,begin,end,frame):
        if frame.empty:raise ValueError('Cannot save empty market data')
        frame=market.normalize(frame).sort_values('timestamp')
        expected=period_seconds(res)
        if np.any(frame.timestamp.to_numpy(dtype='int64')%expected):
            raise ValueError('Off-grid timestamps; reject, do not correct')
        if np.any(np.diff(frame.timestamp.to_numpy(dtype='int64'))!=expected):
            raise ValueError('Noncontiguous chunk; must segment, not fill gaps')
        if int(frame.timestamp.iloc[0])<begin or int(frame.timestamp.iloc[-1])>=end:
            raise ValueError('Returned records outside requested time window')
        folder=self.root/'candles'/symbol/res
        folder.mkdir(parents=True,exist_ok=True)
        dest=folder/f'{begin}_{end}.csv.gz'
        temp=dest.with_name(dest.name+'.partial')
        frame[['timestamp','open','high','low','close','volume']].to_csv(temp,index=False,compression='gzip')
        temp.replace(dest)
        rel=dest.relative_to(self.root).as_posix()
        with self.db:
            self.db.execute('INSERT OR REPLACE INTO chunks(symbol,resolution,begin,end,first_ts,last_ts,rows,filename,sha256,observed_at,status) VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                (symbol,res,begin,end,int(frame.timestamp.iloc[0]),int(frame.timestamp.iloc[-1]),len(frame),rel,sha(dest),utcnow(),'COMPLETE'))
        return {'symbol':symbol,'resolution':res,'rows':len(frame),'file':rel}

    def harvest(self, scope='all-spot',days=7,resolutions=('15','60'),chunk_hours=3,max_markets=None,delay=0.35):
        if not 1 <= days <= 365:raise ValueError('days outside permitted range')
        if not 0.15<=delay<=60:raise ValueError('delay too low/high; respect rate limits')
        if any(res not in ALL_RESOLUTIONS for res in resolutions):raise ValueError('unsupported resolution')
        symbols=self.symbols(scope)
        if not symbols: self.discover(); symbols=self.symbols(scope)
        if max_markets is not None:
            # A limited research watch uses the highest observed real quote turnover,
            # never alphabetical symbol order or invented popularity scores.
            volume_by={}
            for (raw,) in self.db.execute('SELECT metadata FROM assets'):
                info=json.loads(raw)
                try:volume_by[info['symbol']]=float(info.get('quote_volume_24h') or 0)
                except (ValueError,TypeError):volume_by[info['symbol']]=0
            symbols=sorted(symbols,key=lambda z:volume_by.get(z,0),reverse=True)[:max_markets]
        end=int(time.time()); end=end//60*60
        begin=end-days*86400
        summaries={'started':utcnow(),'scope':scope,'symbols_count':len(symbols),'resolutions':list(resolutions),'complete':0,'cached':0,'failed':0,'count_units':'source_window_chunks','errors':[]}
        for si,symbol in enumerate(symbols):
            for resolution in resolutions:
                native_res=resolution
                src=DERIVED.get(resolution,(resolution,1))[0]
                period=period_seconds(resolution)
                # Request source grid-aligned, full periods only; avoid partial final candle.
                stop=end//period*period
                size=max(period, (chunk_hours*3600//period)*period)
                # Absolute epoch anchoring makes repeats resumable at stable chunk keys.
                start=((begin+size-1)//size)*size
                for left in range(start,stop,size):
                    right=min(stop,left+size)
                    if self.has(symbol,native_res,left,right): summaries['cached']+=1;continue
                    try:
                        # Independent market source; explicitly resample observed source bars only.
                        # Sparse UDF reader validates the source grid but preserves
                        # REAL missing periods so we can retain valid contiguous runs.
                        actual_src=src
                        try:
                            raw=market.candles_sparse(symbol,actual_src,left,right)
                        except market.MarketDataError as exc:
                            # Exchange may silently downgrade a coarse request to 1m.
                            # Never relabel it; re-request the actual 1m source.
                            if actual_src=='1' or 'native resolution grid' not in str(exc):raise
                            actual_src='1'
                            raw=market.candles_sparse(symbol,actual_src,left,right)
                        frame=self._resample(raw,actual_src,native_res) if actual_src!=native_res else raw
                        # Some sources are left-closed/right-open and some include the end: trim only fully observed periods.
                        frame=frame[(frame.timestamp>=left)&(frame.timestamp<right)]
                        expected=np.arange(left,right,period,dtype='int64')
                        seen=frame.timestamp.to_numpy(dtype='int64')
                        if not np.array_equal(seen,expected):
                            # Save EVERY actual contiguous observed subsegment, without filling missing candles.
                            missing=np.setdiff1d(expected,seen)
                            if len(frame):
                                breakpoints=np.where(np.diff(seen)!=period)[0]+1
                                for ids in np.split(np.arange(len(frame)),breakpoints):
                                    if len(ids):
                                        sub=frame.iloc[ids].reset_index(drop=True)
                                        lo=int(sub.timestamp.iloc[0]);hi=int(sub.timestamp.iloc[-1])+period
                                        self.save(symbol,native_res,lo,hi,sub)
                            raise ValueError(f'incomplete real history: {len(missing)} missing; first {missing[:4].tolist()}')
                        self.save(symbol,native_res,left,right,frame)
                        summaries['complete']+=1
                    except Exception as e:
                        summaries['failed']+=1
                        reason=f'{type(e).__name__}: {str(e)[:280]}'
                        with self.db:
                            self.db.execute('INSERT INTO incidents(symbol,resolution,begin,end,created_at,error) VALUES(?,?,?,?,?,?)',
                                            (symbol,resolution,left,right,utcnow(),reason))
                        if len(summaries['errors'])<25:summaries['errors'].append({'symbol':symbol,'res':resolution,'start':left,'reason':reason})
                    time.sleep(delay)
            print(f'[{si+1}/{len(symbols)}] {symbol} complete={summaries["complete"]} missing={summaries["failed"]}',flush=True)
        summaries['finished']=utcnow()
        (self.root/'last_harvest.json').write_text(json.dumps(summaries,indent=2,ensure_ascii=False),encoding='utf-8')
        return summaries

    def load(self,symbol,resolution, strict=False):
        rows=self.db.execute('SELECT filename,sha256 FROM chunks WHERE symbol=? AND resolution=? AND status=? ORDER BY begin',
                             (symbol,resolution,'COMPLETE')).fetchall()
        frames=[]
        for file,digest in rows:
            p=self.root/file
            if not p.is_file() or sha(p)!=digest:raise RuntimeError('Archive tampering or missing chunk: '+file)
            frames.append(pd.read_csv(p))
        if not frames:raise ValueError(f'No verified real data for {symbol}/{resolution}')
        data=pd.concat(frames,ignore_index=True).drop_duplicates('timestamp').sort_values('timestamp').reset_index(drop=True)
        market.normalize(data)
        seconds=period_seconds(resolution)
        cuts=np.where(np.diff(data.timestamp.to_numpy(dtype='int64'))!=seconds)[0]+1
        segments=np.split(np.arange(len(data)),cuts)
        answer=[data.iloc[idx].reset_index(drop=True) for idx in segments if len(idx)>0]
        if strict and len(answer)!=1:raise RuntimeError('Market data contains gaps; cannot use as continuous')
        return answer

    def materialize_derived(self, resolutions=None):
        """Derive every possible higher interval from genuine verified base observations.
        No additional exchange requests and no partial-bucket fabrication.
        """
        wanted=tuple(resolutions or DERIVED)
        counters={'materialized':0,'skipped':0,'errors':[]}
        for target in wanted:
            if target not in DERIVED:raise ValueError('Only supported derived resolution')
            src=DERIVED[target][0];step=period_seconds(target)
            for sym in self.symbols('all-spot'):
                try:segs=self.load(sym,src)
                except ValueError:continue
                for frame in segs:
                    try:
                        out=self._resample(frame,src,target)
                        for cut in np.split(np.arange(len(out)),np.where(np.diff(out.timestamp.to_numpy(dtype='int64'))!=step)[0]+1):
                            if not len(cut):continue
                            part=out.iloc[cut].reset_index(drop=True)
                            begin=int(part.timestamp.iloc[0]);end=int(part.timestamp.iloc[-1])+step
                            if self.has(sym,target,begin,end):counters['skipped']+=1;continue
                            self.save(sym,target,begin,end,part)
                            counters['materialized']+=1
                    except (ValueError,market.MarketDataError) as e:
                        if len(counters['errors'])<20:
                            counters['errors'].append({'symbol':sym,'resolution':target,'reason':str(e)[:100]})
        return counters

    def status(self):
        return {'assets':self.db.execute('SELECT count(*) FROM assets').fetchone()[0],
                'chunks':self.db.execute('SELECT count(*) FROM chunks').fetchone()[0],
                'candles':self.db.execute('SELECT coalesce(sum(rows),0) FROM chunks').fetchone()[0],
                'incidents':self.db.execute('SELECT count(*) FROM incidents').fetchone()[0],
                'path':str(self.root)}
