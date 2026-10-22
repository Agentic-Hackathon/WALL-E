"""Bounded, resumable startup synchronization for real Wallex public candles.

This module never calls private trading endpoints.  It plans only the recent
warmup window needed by existing models/features, uses the Milestone 2 archive
progress ledger, and declines a market when verified continuous input is absent.

Source: independently authored for Wallex Atlas Milestone 2.1; it reuses only
the project's existing Milestone 2 archive contracts, not third-party code.
"""
from __future__ import annotations

import json
import os
import socket
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from .atlas_archive import DERIVED, NATIVE, period_seconds, sha, utcnow


DEFAULT_TARGET_RESOLUTION='15'
DEFAULT_WARMUP_HOURS=48
# Public candle APIs can publish the just-ended minute slightly after its wall
# clock boundary.  Plan/readiness share this one-source-bar settlement grace;
# it prevents an otherwise healthy process from permanently chasing the clock.
SOURCE_SETTLEMENT_BARS=1


class DataSyncManager:
    """Coordinate small public-data sync batches across startup/watch processes."""
    def __init__(self, lake, *, owner=None):
        self.lake=lake
        self.owner=owner or f'{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:12]}'
        self._schema()

    def _schema(self):
        with self.lake.db:
            self.lake.db.executescript('''
            CREATE TABLE IF NOT EXISTS data_sync_leases(
                name TEXT PRIMARY KEY, owner TEXT NOT NULL, acquired_at TEXT NOT NULL, expires_epoch REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS data_sync_runs(
                id INTEGER PRIMARY KEY, started_at TEXT NOT NULL, finished_at TEXT, owner TEXT NOT NULL,
                purpose TEXT NOT NULL, plan_json TEXT NOT NULL, result_json TEXT, status TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS idx_data_sync_runs_started ON data_sync_runs(started_at);
            ''')

    def _model_demand(self):
        """Read checkpoint metadata only; never train/promote/select a model here."""
        result={'target_resolution':DEFAULT_TARGET_RESOLUTION,'context':96,'horizon':3,'origin':'SAFE_DEFAULT'}
        active=self.lake.root/'models'/'active_champion.json'
        try:
            manifest=json.loads(active.read_text(encoding='utf-8'))
            selected=manifest.get('checkpoint') or manifest.get('selected_checkpoint')
            checkpoint=Path(selected) if selected else None
            if checkpoint is not None and not checkpoint.is_absolute():checkpoint=self.lake.root/'models'/checkpoint
            meta=checkpoint.with_suffix('.json') if checkpoint else None
            cfg=json.loads(meta.read_text(encoding='utf-8')) if meta and meta.is_file() else {}
            res=cfg.get('resolution');context=cfg.get('context');horizon=cfg.get('horizon')
            if isinstance(res,str) and res in tuple(DERIVED)+NATIVE:
                result.update({'target_resolution':res,'context':int(context),'horizon':int(horizon),'origin':'ACTIVE_CHAMPION_METADATA'})
        except (OSError,ValueError,TypeError,json.JSONDecodeError):
            pass
        return result

    def _priority_symbols(self, top, scope):
        records=[]
        for raw, in self.lake.db.execute('SELECT metadata FROM assets'):
            try:m=json.loads(raw)
            except json.JSONDecodeError:continue
            spot=m.get('is_spot') is True
            tmn=spot and m.get('quote_asset')=='TMN'
            if scope=='priority' and not tmn:continue
            if scope=='tmn' and not tmn:continue
            if scope=='spot' and not spot:continue
            if scope=='catalog':
                pass
            elif not spot:
                continue
            try:turnover=float(m.get('quote_volume_24h') or 0)
            except (TypeError,ValueError):turnover=0
            symbol=m.get('symbol')
            if isinstance(symbol,str) and symbol.isalnum() and symbol.isupper():records.append((turnover,symbol))
        return [symbol for _,symbol in sorted(records,reverse=True)[:top]]

    def _window_covered(self, symbol, resolution, begin, end):
        """Verify every expected source timestamp in one bounded window."""
        return not self._missing_ranges(symbol,resolution,begin,end)

    def _missing_ranges(self, symbol, resolution, begin, end):
        """Return exact absent runs; never turn an absent observation into a bar.

        Planning against these runs, rather than against an entire rolling
        three-hour block, is what makes a second startup a true cache hit and
        lets the next run request only candles that have elapsed since it.
        """
        step=period_seconds(resolution)
        rows=self.lake.db.execute('''SELECT filename,sha256 FROM chunks
            WHERE symbol=? AND resolution=? AND status='COMPLETE' AND end>? AND begin<?''',
            (symbol,resolution,begin,end)).fetchall()
        seen=set()
        for filename,digest in rows:
            path=self.lake.root/filename
            try:
                if not path.is_file() or sha(path)!=digest:continue
                frame=pd.read_csv(path,usecols=['timestamp'])
                seen.update(int(x) for x in frame['timestamp'] if begin<=int(x)<end)
            except (OSError,ValueError,pd.errors.ParserError):
                continue
        expected=np.arange(begin,end,step,dtype='int64')
        absent=[int(x) for x in expected if int(x) not in seen]
        if not absent:return []
        runs=[];left=previous=absent[0]
        for stamp in absent[1:]:
            if stamp!=previous+step:
                runs.append((left,previous+step));left=stamp
            previous=stamp
        runs.append((left,previous+step))
        return runs

    def _unavailable(self, symbol, resolution, begin, end):
        # A subsequent plan can split an originally unavailable range at a
        # chunk boundary.  Treat a verified prior SOURCE_UNAVAILABLE interval
        # as applying to its contained subrange too, so restarts do not hammer
        # a source that already declined the observation.
        row=self.lake.db.execute('''SELECT status,last_error FROM download_progress
            WHERE symbol=? AND resolution=? AND status='SOURCE_UNAVAILABLE'
              AND begin<=? AND end>=?
            ORDER BY (end-begin) ASC LIMIT 1''',
            (symbol,resolution,begin,end)).fetchone()
        return bool(row and row[0]=='SOURCE_UNAVAILABLE'), (row[1] if row else None)

    def plan(self, *, top=8, scope='priority', warmup_hours=None, target_resolutions=None, now=None, symbols=None):
        if scope not in ('priority','tmn','spot','catalog'):raise ValueError('invalid sync scope')
        demand=self._model_demand()
        targets=tuple(target_resolutions or (demand['target_resolution'],))
        if any(x not in tuple(DERIVED)+NATIVE for x in targets):raise ValueError('unsupported target resolution')
        warmup=float(warmup_hours or max(DEFAULT_WARMUP_HOURS,
            (demand['context']+55+demand['horizon'])*period_seconds(demand['target_resolution'])/3600))
        if not 1<=warmup<=72:raise ValueError('warmup hours must stay within 1..72')
        reference=float(time.time() if now is None else now)
        symbols=list(symbols) if symbols is not None else self._priority_symbols(int(top),scope)
        if not symbols or any(not isinstance(x,str) or not x.isalnum() or x!=x.upper() for x in symbols):
            raise ValueError('sync symbols must be nonempty uppercase catalog symbols')
        windows=[];unavailable=[]
        for target in targets:
            source=DERIVED.get(target,(target,1))[0]
            step=period_seconds(source);chunk=max(step,(3*3600//step)*step)
            stop=max(0,(int(reference)//step-SOURCE_SETTLEMENT_BARS)*step)
            start=max(0,stop-int(warmup*3600)); start=(start//chunk)*chunk
            for symbol in symbols:
                for left in range(start,stop,chunk):
                    right=min(stop,left+chunk)
                    # Preserve observed coverage and request only the exact
                    # missing sequence(s), including after a partial current
                    # bucket.  This keeps resume idempotent without filling
                    # gaps locally.
                    for missing_begin,missing_end in self._missing_ranges(symbol,source,left,right):
                        known,reason=self._unavailable(symbol,source,missing_begin,missing_end)
                        item={'symbol':symbol,'target_resolution':target,'source_resolution':source,
                              'begin':missing_begin,'end':missing_end,
                              'begin_utc':datetime.fromtimestamp(missing_begin,timezone.utc).isoformat(),
                              'end_utc':datetime.fromtimestamp(missing_end,timezone.utc).isoformat()}
                        if known:
                            item['reason']=reason;unavailable.append(item)
                        else:windows.append(item)
        # Most-recent missing windows first, but rotate across markets deterministically.
        windows.sort(key=lambda x:(-x['end'],x['symbol'],x['source_resolution']))
        return {'generated_at_utc':utcnow(),'purpose':'STARTUP_OR_WATCH_PUBLIC_DATA_SYNC','scope':scope,
                'symbols':symbols,'target_resolutions':list(targets),'model_demand':demand,
                'warmup_hours':warmup,'planned_windows':windows,'source_unavailable_windows':unavailable,
                'network_requests_planned':len(windows),'network_requests_skipped_known_unavailable':len(unavailable),
                'dry_run':True}

    def _acquire(self, ttl_seconds=120):
        now=time.time()
        try:
            with self.lake.db:
                self.lake.db.execute('DELETE FROM data_sync_leases WHERE expires_epoch<?',(now,))
                self.lake.db.execute('INSERT INTO data_sync_leases(name,owner,acquired_at,expires_epoch) VALUES(?,?,?,?)',
                    ('global-public-data-sync',self.owner,utcnow(),now+ttl_seconds))
            return True
        except Exception:
            return False

    def _release(self):
        with self.lake.db:
            self.lake.db.execute('DELETE FROM data_sync_leases WHERE name=? AND owner=?',('global-public-data-sync',self.owner))

    def run(self, *, top=8, scope='priority', warmup_hours=None, target_resolutions=None,
            max_windows=8, delay=.35, retries=2, backoff_seconds=.5, workers=1, purpose='startup',symbols=None):
        plan=self.plan(top=top,scope=scope,warmup_hours=warmup_hours,target_resolutions=target_resolutions,symbols=symbols)
        selected=plan['planned_windows'][:max(0,int(max_windows))]
        plan['selected_windows']=selected;plan['dry_run']=False
        if not selected:
            return {'status':'NO_SYNC_NEEDED_OR_ALL_PENDING_UNAVAILABLE','plan':plan,'complete':0,'cached':0,'failed':0}
        if not self._acquire():
            return {'status':'LEASE_HELD_BY_ANOTHER_DATASYNC','plan':plan,'complete':0,'cached':0,'failed':0}
        run_id=None
        try:
            with self.lake.db:
                cur=self.lake.db.execute('''INSERT INTO data_sync_runs(started_at,owner,purpose,plan_json,status)
                    VALUES(?,?,?,?,?)''',(utcnow(),self.owner,purpose,json.dumps(plan,sort_keys=True),'RUNNING'))
                run_id=cur.lastrowid
            raw_windows=[(x['symbol'],x['source_resolution'],x['begin'],x['end']) for x in selected]
            outcome=self.lake.harvest(resolutions=tuple(sorted({x[1] for x in raw_windows})),windows=raw_windows,
                                      delay=delay,retries=retries,backoff_seconds=backoff_seconds,workers=workers)
            derived=sorted({x['target_resolution'] for x in selected if x['target_resolution'] in DERIVED})
            if derived:self.lake.materialize_derived(derived,symbols=sorted({x['symbol'] for x in selected}))
            result={'status':'COMPLETED','plan':plan,'harvest':outcome,'derived_requested':derived,
                    'complete':outcome['complete'],'cached':outcome['cached'],'failed':outcome['failed'],
                    'remaining_planned_windows':max(0,len(plan['planned_windows'])-len(selected))}
            with self.lake.db:
                self.lake.db.execute('UPDATE data_sync_runs SET finished_at=?,result_json=?,status=? WHERE id=?',
                    (utcnow(),json.dumps(result,sort_keys=True),'COMPLETED',run_id))
            return result
        except Exception as exc:
            result={'status':'FAILED_SAFE_NO_DATA_REPLACED','error_type':type(exc).__name__,'plan':plan,
                    'complete':0,'cached':0,'failed':len(selected)}
            if run_id is not None:
                with self.lake.db:self.lake.db.execute('UPDATE data_sync_runs SET finished_at=?,result_json=?,status=? WHERE id=?',
                    (utcnow(),json.dumps(result,sort_keys=True),'FAILED',run_id))
            return result
        finally:self._release()

    def market_readiness(self, symbol, resolution=None, warmup_hours=None, now=None):
        demand=self._model_demand();target=resolution or demand['target_resolution']
        plan=self.plan(top=1,scope='catalog',warmup_hours=warmup_hours,target_resolutions=(target,),now=now,symbols=(symbol,))
        source=DERIVED.get(target,(target,1))[0]; step=period_seconds(source);ref=float(time.time() if now is None else now)
        stop=max(0,(int(ref)//step-SOURCE_SETTLEMENT_BARS)*step)
        start=((max(0,stop-int(plan['warmup_hours']*3600)))//max(step,(3*3600//step)*step))*max(step,(3*3600//step)*step)
        missing=[]
        for left in range(start,stop,max(step,(3*3600//step)*step)):
            right=min(stop,left+max(step,(3*3600//step)*step))
            if not self._window_covered(symbol,source,left,right):missing.append((left,right))
        # A derived target is only usable after its most recent *closed* bucket
        # has been materialized from a complete native source bucket.  Do not
        # demand an incomplete candle merely because the source clock advanced.
        target_step=period_seconds(target)
        target_stop=(stop//target_step)*target_step
        target_ready=not missing and (target in NATIVE or
            (target_stop>=target_step and self._window_covered(symbol,target,target_stop-target_step,target_stop)))
        return {'symbol':symbol,'target_resolution':target,'source_resolution':source,'ready':target_ready,
                'reason':'VERIFIED_RECENT_CONTIGUOUS_INPUT' if target_ready else 'MISSING_OR_STALE_VERIFIED_INPUT',
                'missing_windows':len(missing),'warmup_hours':plan['warmup_hours']}

    def run_continuous(self, stop_event, *, interval_seconds=60, max_cycles=None, **run_kwargs):
        """Run bounded reconciliation periodically until the supplied event stops it.

        This deliberately owns no background thread: callers (Watch, a service,
        or a supervisor) retain lifecycle control.  The SQLite lease makes two
        independently started schedulers safely co-exist.
        """
        if interval_seconds<1:raise ValueError('sync interval must be at least one second')
        results=[];cycles=0
        while not stop_event.is_set() and (max_cycles is None or cycles<int(max_cycles)):
            results.append(self.run(purpose='continuous-sync',**run_kwargs));cycles+=1
            if stop_event.wait(interval_seconds):break
        return {'status':'STOPPED' if stop_event.is_set() else 'CYCLE_LIMIT_REACHED',
                'cycles':cycles,'results':results}

    def status(self):
        lease=self.lake.db.execute('SELECT owner,acquired_at,expires_epoch FROM data_sync_leases WHERE name=?',('global-public-data-sync',)).fetchone()
        last=self.lake.db.execute('SELECT started_at,finished_at,purpose,status,result_json FROM data_sync_runs ORDER BY id DESC LIMIT 1').fetchone()
        return {'owner':self.owner,'lease':{'held':bool(lease),'owner':lease[0] if lease else None,
                'acquired_at':lease[1] if lease else None,'expires_epoch':lease[2] if lease else None},
                'last_run':{'started_at':last[0],'finished_at':last[1],'purpose':last[2],'status':last[3],
                             'result':json.loads(last[4]) if last and last[4] else None} if last else None,
                'resume_source':'catalog.sqlite.download_progress','live_execution':'HARD_DISABLED'}
