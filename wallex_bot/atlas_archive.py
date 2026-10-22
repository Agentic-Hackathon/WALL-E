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

# Wallex's public UDF documentation lists additional server-side intervals, but
# this archive only treats a response as native after its returned timestamps
# pass the requested-grid checks in market.candles_sparse.  The documented API
# contract is recorded by atlas_data_quality; it is never trusted over an
# observed incompatible response.
PUBLIC_UDF_ENDPOINT = '/v1/udf/history'

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
        CREATE TABLE IF NOT EXISTS download_progress(
            symbol TEXT NOT NULL, resolution TEXT NOT NULL, begin INTEGER NOT NULL, end INTEGER NOT NULL,
            source_resolution TEXT NOT NULL, status TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
            last_started_at TEXT, last_finished_at TEXT, last_error TEXT, updated_at TEXT NOT NULL,
            PRIMARY KEY(symbol,resolution,begin,end));
        CREATE TABLE IF NOT EXISTS chunk_observations(
            id INTEGER PRIMARY KEY, symbol TEXT NOT NULL, resolution TEXT NOT NULL, begin INTEGER NOT NULL,
            end INTEGER NOT NULL, filename TEXT NOT NULL, source_resolution TEXT NOT NULL,
            retrieved_at TEXT NOT NULL, available_at TEXT NOT NULL, source_endpoint TEXT NOT NULL,
            observation_note TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS idx_chunk_observations_key
            ON chunk_observations(symbol,resolution,begin,end);
        CREATE TABLE IF NOT EXISTS archive_conflicts(
            id INTEGER PRIMARY KEY, symbol TEXT NOT NULL, resolution TEXT NOT NULL, begin INTEGER NOT NULL,
            end INTEGER NOT NULL, existing_sha256 TEXT, candidate_sha256 TEXT NOT NULL,
            candidate_filename TEXT NOT NULL, observed_at TEXT NOT NULL, reason TEXT NOT NULL);
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

    def _progress(self, symbol, resolution, begin, end, source_resolution, status,
                  attempts=0, error=None, started_at=None, finished_at=None):
        """Persist retry/resume state without altering previously accepted candles."""
        with self.db:
            self.db.execute('''INSERT INTO download_progress(
                    symbol,resolution,begin,end,source_resolution,status,attempts,last_started_at,
                    last_finished_at,last_error,updated_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(symbol,resolution,begin,end) DO UPDATE SET
                    source_resolution=excluded.source_resolution,status=excluded.status,
                    attempts=excluded.attempts,last_started_at=excluded.last_started_at,
                    last_finished_at=excluded.last_finished_at,last_error=excluded.last_error,
                    updated_at=excluded.updated_at''',
                (symbol,resolution,begin,end,source_resolution,status,int(attempts),started_at,
                 finished_at,error,utcnow()))

    def _store_conflict(self, symbol, res, begin, end, temp, candidate_sha, existing_sha, reason):
        """Keep contradictory exchange evidence separately; never overwrite history."""
        folder=self.root/'conflicts'/symbol/res
        folder.mkdir(parents=True,exist_ok=True)
        candidate=folder/f'{begin}_{end}_{candidate_sha[:16]}.csv.gz'
        if not candidate.exists():
            temp.replace(candidate)
        else:
            temp.unlink(missing_ok=True)
        with self.db:
            self.db.execute('''INSERT INTO archive_conflicts(
                    symbol,resolution,begin,end,existing_sha256,candidate_sha256,candidate_filename,observed_at,reason)
                VALUES(?,?,?,?,?,?,?,?,?)''',
                (symbol,res,begin,end,existing_sha,candidate_sha,
                 candidate.relative_to(self.root).as_posix(),utcnow(),reason))
        return candidate

    def save(self,symbol,res,begin,end,frame,*,source_resolution=None,retrieved_at=None,available_at=None,
             observation_note='PUBLIC_CLOSED_CANDLES_RECEIVED_AT_LOCAL_CLOCK'):
        """Append a verified chunk; retain conflicting evidence instead of replacing it.

        ``available_at`` is deliberately local receipt time (or later), never a
        historical candle timestamp. This is conservative for point-in-time use.
        """
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
        rel=dest.relative_to(self.root).as_posix()
        candidate_sha=sha(temp)
        existing=self.db.execute('''SELECT filename,sha256 FROM chunks
                                  WHERE symbol=? AND resolution=? AND begin=? AND end=? AND status=?''',
                                 (symbol,res,begin,end,'COMPLETE')).fetchone()
        if existing:
            old_file,old_sha=existing
            old_path=self.root/old_file
            if old_path.is_file() and sha(old_path)==old_sha and old_sha==candidate_sha:
                temp.unlink(missing_ok=True)
                return {'symbol':symbol,'resolution':res,'rows':len(frame),'file':old_file,'status':'CACHED'}
            conflict=self._store_conflict(symbol,res,begin,end,temp,candidate_sha,old_sha,
                'NEW_RESPONSE_DIFFERS_FROM_OR_CANNOT_VERIFY_ACCEPTED_CHUNK')
            return {'symbol':symbol,'resolution':res,'rows':len(frame),'file':str(conflict.relative_to(self.root)),
                    'status':'CONFLICT_RETAINED'}
        if dest.exists():
            # A file without a matching catalog row is also preserved as evidence.
            conflict=self._store_conflict(symbol,res,begin,end,temp,candidate_sha,None,
                'DESTINATION_EXISTS_WITHOUT_ACCEPTED_CATALOG_ROW')
            return {'symbol':symbol,'resolution':res,'rows':len(frame),'file':str(conflict.relative_to(self.root)),
                    'status':'CONFLICT_RETAINED'}
        temp.replace(dest)
        received=retrieved_at or utcnow()
        available=available_at or received
        src=source_resolution or res
        with self.db:
            self.db.execute('INSERT INTO chunks(symbol,resolution,begin,end,first_ts,last_ts,rows,filename,sha256,observed_at,status) VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                (symbol,res,begin,end,int(frame.timestamp.iloc[0]),int(frame.timestamp.iloc[-1]),len(frame),rel,candidate_sha,received,'COMPLETE'))
            self.db.execute('''INSERT INTO chunk_observations(
                    symbol,resolution,begin,end,filename,source_resolution,retrieved_at,available_at,source_endpoint,observation_note)
                VALUES(?,?,?,?,?,?,?,?,?,?)''',
                (symbol,res,begin,end,rel,src,received,available,PUBLIC_UDF_ENDPOINT,observation_note))
        return {'symbol':symbol,'resolution':res,'rows':len(frame),'file':rel,'status':'SAVED',
                'retrieved_at':received,'available_at':available}

    def harvest(self, scope='all-spot',days=7,resolutions=('15','60'),chunk_hours=3,max_markets=None,
                delay=0.35,retries=2,backoff_seconds=.5,workers=1):
        """Fetch bounded public-history windows with resumable, auditable retries.

        SQLite writes deliberately remain on this caller thread.  Workers issue
        only public GET requests, under one shared request-start limiter; this
        prevents a worker from ever writing or replacing accepted candle files.
        """
        from concurrent.futures import ThreadPoolExecutor
        from threading import Lock
        if not 1 <= days <= 365:raise ValueError('days outside permitted range')
        if not .02<=delay<=60:raise ValueError('delay too low/high; respect rate limits')
        if not 0<=retries<=6 or not .05<=backoff_seconds<=60:raise ValueError('invalid retry/backoff policy')
        if not 1<=workers<=8:raise ValueError('workers must be 1..8')
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
        summaries={'started':utcnow(),'scope':scope,'symbols_count':len(symbols),'resolutions':list(resolutions),
                   'complete':0,'cached':0,'conflicts':0,'failed':0,'retried_requests':0,
                   'workers':workers,'min_request_start_spacing_seconds':delay,
                   'count_units':'source_window_chunks','errors':[]}
        tasks=[]
        for symbol in symbols:
            for resolution in resolutions:
                src=DERIVED.get(resolution,(resolution,1))[0]
                period=period_seconds(resolution)
                stop=end//period*period
                size=max(period, (chunk_hours*3600//period)*period)
                start=((begin+size-1)//size)*size
                for left in range(start,stop,size):
                    right=min(stop,left+size)
                    if self.has(symbol,resolution,left,right):
                        summaries['cached']+=1
                        self._progress(symbol,resolution,left,right,src,'CACHED_VALID',finished_at=utcnow())
                        continue
                    self._progress(symbol,resolution,left,right,src,'QUEUED')
                    tasks.append((symbol,resolution,src,period,left,right))
        limiter_lock=Lock()
        next_request=[0.0]
        def wait_turn():
            with limiter_lock:
                now_mono=time.monotonic()
                wait=max(0.0,next_request[0]-now_mono)
                next_request[0]=max(now_mono,next_request[0])+delay
            if wait:time.sleep(wait)
        def fetch(task):
            symbol,resolution,src,period,left,right=task
            started=utcnow()
            failures=[]
            for attempt in range(retries+1):
                try:
                    actual_src=src
                    wait_turn()
                    raw=market.candles_sparse(symbol,actual_src,left,right)
                    # A server-side coarse request can silently arrive on a 1m grid.
                    # Never relabel it: re-request 1m and derive only exact buckets.
                    return {'task':task,'raw':raw,'actual_src':actual_src,'attempts':attempt+1,
                            'started_at':started,'finished_at':utcnow(),'failures':failures}
                except Exception as exc:
                    failures.append(f'{type(exc).__name__}: {str(exc)[:280]}')
                    if attempt==retries:break
                    time.sleep(min(backoff_seconds*(2**attempt),30.0))
            return {'task':task,'error':failures[-1] if failures else 'UNKNOWN_PUBLIC_FETCH_FAILURE',
                    'attempts':retries+1,'started_at':started,'finished_at':utcnow(),'failures':failures}
        def apply_result(result):
            symbol,resolution,src,period,left,right=result['task']
            summaries['retried_requests']+=max(0,result['attempts']-1)
            if 'error' in result:
                summaries['failed']+=1
                reason=result['error']
                self._progress(symbol,resolution,left,right,src,'FAILED',result['attempts'],reason,
                               result['started_at'],result['finished_at'])
                with self.db:
                    self.db.execute('INSERT INTO incidents(symbol,resolution,begin,end,created_at,error) VALUES(?,?,?,?,?,?)',
                                    (symbol,resolution,left,right,utcnow(),reason))
                if len(summaries['errors'])<25:summaries['errors'].append({'symbol':symbol,'res':resolution,'start':left,'reason':reason})
                return
            try:
                frame=self._resample(result['raw'],result['actual_src'],resolution) if result['actual_src']!=resolution else result['raw']
                frame=frame[(frame.timestamp>=left)&(frame.timestamp<right)]
                expected=np.arange(left,right,period,dtype='int64')
                seen=frame.timestamp.to_numpy(dtype='int64')
                receipt=result['finished_at']
                if not np.array_equal(seen,expected):
                    missing=np.setdiff1d(expected,seen)
                    if len(frame):
                        breakpoints=np.where(np.diff(seen)!=period)[0]+1
                        for ids in np.split(np.arange(len(frame)),breakpoints):
                            if len(ids):
                                sub=frame.iloc[ids].reset_index(drop=True)
                                lo=int(sub.timestamp.iloc[0]);hi=int(sub.timestamp.iloc[-1])+period
                                self.save(symbol,resolution,lo,hi,sub,source_resolution=result['actual_src'],
                                          retrieved_at=receipt,available_at=receipt)
                    raise ValueError(f'incomplete real history: {len(missing)} missing; first {missing[:4].tolist()}')
                saved=self.save(symbol,resolution,left,right,frame,source_resolution=result['actual_src'],
                                retrieved_at=receipt,available_at=receipt)
                status=saved.get('status','SAVED')
                self._progress(symbol,resolution,left,right,result['actual_src'],status,result['attempts'],None,
                               result['started_at'],receipt)
                if status=='CONFLICT_RETAINED':summaries['conflicts']+=1
                elif status=='CACHED':summaries['cached']+=1
                else:summaries['complete']+=1
            except Exception as exc:
                summaries['failed']+=1
                reason=f'{type(exc).__name__}: {str(exc)[:280]}'
                self._progress(symbol,resolution,left,right,src,'INCOMPLETE_OR_INVALID',result['attempts'],reason,
                               result['started_at'],result['finished_at'])
                with self.db:
                    self.db.execute('INSERT INTO incidents(symbol,resolution,begin,end,created_at,error) VALUES(?,?,?,?,?,?)',
                                    (symbol,resolution,left,right,utcnow(),reason))
                if len(summaries['errors'])<25:summaries['errors'].append({'symbol':symbol,'res':resolution,'start':left,'reason':reason})
        with ThreadPoolExecutor(max_workers=workers,thread_name_prefix='wallex-public') as pool:
            for result in pool.map(fetch,tasks):
                apply_result(result)
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
                            # The derived bar is usable no earlier than this
                            # materialization receipt; source candle timestamps
                            # themselves are never retroactively treated as PIT availability.
                            self.save(sym,target,begin,end,part,source_resolution=src,
                                      observation_note='DERIVED_ONLY_FROM_COMPLETE_VERIFIED_SOURCE_BUCKETS')
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
