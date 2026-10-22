"""M8 real-candle analogue retrieval, no broker or model promotion authority.

DIRECT library reuse: scipy.spatial.distance.cdist (BSD-3-Clause).
Constrained DTW recurrence independently implemented; librosa 0.10.2 ISC
adapter was considered, but local import probe did not finish in minutes.
Algorithm contract: https://librosa.org/doc/0.10.2/generated/librosa.sequence.dtw.html
Atlas archive SHA/grid/gap verification and conservative receipts reused.
"""
from __future__ import annotations
import argparse,hashlib,json,math,sqlite3,time
from pathlib import Path
import numpy as np
import pandas as pd
from scipy.spatial.distance import cdist
from .atlas_forward import _sha,_canon
from .atlas_archive import period_seconds,sha
from .atlas_feature_health import _verified_segments
from .atlas_feature_provenance import annotate_receipts
from .atlas_liquidation import _save_atomic

VERSION='ATLAS_ANALOGUES_V1'
HORIZONS=(1,3,6,12)
RESOLUTIONS=('1','5','15','60','240')
REPRESENTATIONS=('relative_ohlcv','candle_structure')
DEFAULT_INDEX='atlas_store/research_challengers/milestone8/pattern_index_v1'


def representation(frame,kind='relative_ohlcv'):
    """Window-only relative normalization, never fit on labels/full series.

    Flat price variance, zero range or median volume do not get synthetic
    denominators: reject the undefined representation with a reason.
    """
    if kind not in REPRESENTATIONS:raise ValueError('UNKNOWN_REPRESENTATION')
    values=frame[['open','high','low','close','volume']].to_numpy(float)
    if len(values)<3 or not np.isfinite(values).all() or (values[:,:4]<=0).any() or (values[:,4]<0).any():raise ValueError('INVALID_OBSERVED_WINDOW')
    o,h,l,c,v=values.T;scale=float(np.std(np.diff(np.log(c)),ddof=1));median=float(np.median(v))
    if scale<=0 or median<=0:raise ValueError('UNDEFINED_WINDOW_VOLATILITY_OR_MEDIAN_VOLUME')
    relative=np.log(values[:,:4]/c[0])/scale
    volume=np.log1p(v)-math.log1p(median)
    if kind=='relative_ohlcv':result=np.column_stack([relative,volume])
    else:
        ranges=h-l
        if (ranges<=0).any():raise ValueError('ZERO_OBSERVED_CANDLE_RANGE')
        result=np.column_stack([np.log(c/o)/scale,np.log(h/l)/scale,(c-o)/ranges,
            (h-np.maximum(o,c))/ranges,(np.minimum(o,c)-l)/ranges,volume])
    if not np.isfinite(result).all():raise ValueError('NONFINITE_REPRESENTATION')
    return result


def constrained_dtw(a,b,radius=2):
    """Sakoe-Chiba constrained recurrence over reused SciPy pairwise costs.

    No audio/ML stack initialization needed; O(window*band) recurrence,
    Euclidean point cost, endpoint anchored, fixed n+m normalization.
    """
    if radius<abs(len(a)-len(b)):return float('inf')
    costs=cdist(a,b,'euclidean');previous=np.full(len(b)+1,np.inf);previous[0]=0.
    for i in range(1,len(a)+1):
        current=np.full(len(b)+1,np.inf)
        for j in range(max(1,i-radius),min(len(b),i+radius)+1):
            current[j]=costs[i-1,j-1]+min(current[j-1],previous[j],previous[j-1])
        previous=current
    return float(previous[-1]/(len(a)+len(b)))


def outcomes(frame,origin_index):
    close=float(frame.close.iloc[origin_index]);result={}
    for horizon in HORIZONS:
        future=frame.iloc[origin_index+1:origin_index+1+horizon]
        if len(future)!=horizon:raise ValueError('MISSING_REAL_OUTCOME_CANDLES')
        hi=future.high.to_numpy(float);lo=future.low.to_numpy(float)
        result[str(horizon)]={'close_log_return':float(np.log(float(future.close.iloc[-1])/close)),
            'mfe_log':float(np.log(hi.max()/close)),'mae_log':float(np.log(lo.min()/close)),
            'mfe_bar':int(np.argmax(hi)+1),'mae_bar':int(np.argmin(lo)+1),
            'range_log':float(np.log(hi.max()/lo.min()))}
    return result


class PatternIndex:
    def __init__(self,directory=DEFAULT_INDEX,*,readonly=False):
        self.directory=Path(directory).resolve();self.readonly=readonly
        if not readonly:self.directory.mkdir(parents=True,exist_ok=True)
        path=self.directory/'patterns.sqlite'
        self.db=sqlite3.connect(path.as_uri()+'?mode=ro' if readonly else str(path),uri=readonly,timeout=30)
        if not readonly:
            self.db.executescript('''PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS patterns(id TEXT PRIMARY KEY,symbol TEXT,resolution TEXT,length INTEGER,representation TEXT,
                start REAL,end REAL,outcome_end REAL,available REAL,payload TEXT,sha256 TEXT);
            CREATE INDEX IF NOT EXISTS pattern_lookup ON patterns(resolution,length,representation,outcome_end,available);
            CREATE TABLE IF NOT EXISTS pattern_meta(key TEXT PRIMARY KEY,payload TEXT);
            ''');self.db.commit()
    def close(self):self.db.close()
    def manifest(self):
        row=self.db.execute("SELECT payload FROM pattern_meta WHERE key='manifest'").fetchone()
        if not row:raise ValueError('INDEX_NOT_BUILT')
        value=json.loads(row[0]);digest=value.pop('manifest_sha256')
        if _sha(value)!=digest or value['version']!=VERSION:raise ValueError('INDEX_MANIFEST_INVALID')
        value['manifest_sha256']=digest;return value
    def verify_sources(self):
        value=self.manifest();root=Path(value['archive_root']).resolve()
        implementation=hashlib.sha256(Path(__file__).read_bytes().replace(b'\r\n',b'\n')).hexdigest()
        if implementation!=value['implementation_sha256_LF']:raise ValueError('PATTERN_IMPLEMENTATION_CHANGED_NEW_INDEX_REQUIRED')
        for filename,digest in value['sources'].items():
            path=(root/filename).resolve()
            if not path.is_relative_to(root) or not path.is_file() or sha(path)!=digest:raise ValueError('PATTERN_SOURCE_CHANGED_REBUILD_SEPARATE_INDEX')
        if _sha(self.db.execute('SELECT id,sha256 FROM patterns ORDER BY id').fetchall())!=value['rows_sha256']:raise ValueError('PATTERN_INDEX_ROWS_CHANGED')
        return True
    def build(self,lake,*,resolutions=RESOLUTIONS,lengths=(7,10),max_windows_per_asset=1000):
        if self.readonly:raise ValueError('READ_ONLY_INDEX')
        if not set(resolutions)<=set(RESOLUTIONS) or not set(lengths)<={7,10,16,24} or max_windows_per_asset<1:raise ValueError('INVALID_INDEX_CONTRACT')
        if self.db.execute("SELECT 1 FROM pattern_meta WHERE key='manifest'").fetchone():
            self.verify_sources();return {'status':'CACHE_HIT_IMMUTABLE_INDEX','manifest':self.manifest()}
        if self.db.execute('SELECT count(*) FROM patterns').fetchone()[0]:raise ValueError('PARTIAL_BUILD_REQUIRES_NEW_INDEX_DIRECTORY')
        built=time.time();sources={};counts={};skips={};eligible=[]
        for symbol,raw in lake.db.execute('SELECT symbol,metadata FROM assets ORDER BY symbol').fetchall():
            m=json.loads(raw)
            if m.get('is_spot') is True and m.get('quote_asset')=='TMN':eligible.append(symbol)
        self.db.execute('BEGIN IMMEDIATE')
        try:
            for symbol in eligible:
                for res in resolutions:
                    try:segments,_=_verified_segments(lake.root,lake.db,symbol,res)
                    except (ValueError,RuntimeError,OSError) as exc:
                        # Preserve conflicting evidence in the archive; omit
                        # this market/timeframe, never choose a winning copy.
                        skips[symbol+'|'+res+'|'+str(exc)[:100]]=1;continue
                    if not segments:continue
                    receipts=dict(lake.db.execute("SELECT filename,sha256 FROM chunks WHERE symbol=? AND resolution=? AND status='COMPLETE'",(symbol,res)))
                    sources.update(receipts);step=period_seconds(res)
                    for part in segments:
                        part=part[part.timestamp+step<=built].reset_index(drop=True)
                        if len(part)<min(lengths)+max(HORIZONS):continue
                        annotated=annotate_receipts(lake,symbol,res,part)
                        # Legacy candle timestamps never prove historical
                        # access. Actual verification NOW permits only current
                        # decisions; retrospective studies have a separate flag.
                        available=float(annotated.available_at.max())
                        legacy=not math.isfinite(available)
                        available=time.time() if legacy else available
                        for length in lengths:
                            end_indices=range(length-1,len(part)-max(HORIZONS))
                            end_indices=list(end_indices)[-max_windows_per_asset:]
                            for end in end_indices:
                                window=part.iloc[end-length+1:end+1];label=outcomes(part,end)
                                for kind in REPRESENTATIONS:
                                    try:features=representation(window,kind)
                                    except ValueError as exc:
                                        reason=str(exc);skips[reason]=skips.get(reason,0)+1;continue
                                    start=int(window.timestamp.iloc[0]);closed=int(window.timestamp.iloc[-1])+step
                                    outcome_end=int(part.timestamp.iloc[end+max(HORIZONS)])+step
                                    payload={'version':VERSION,'symbol':symbol,'resolution':res,'length':length,'representation':kind,
                                        'start':start,'end':closed,'outcome_end':outcome_end,'available_at':max(available,outcome_end),
                                        'availability_policy':'VERIFIED_NOW_ONLY_LEGACY' if legacy else 'CONSERVATIVE_PREFIX_RECEIPTS',
                                        'features':features.tolist(),'outcomes':label,'source_sha256':_sha(receipts),
                                        'volatility':float(np.std(np.diff(np.log(window.close.to_numpy(float))),ddof=1)),
                                        'regime':'UP' if window.close.iloc[-1]>window.close.iloc[0] else 'DOWN_OR_FLAT',
                                        'liquidity':None,'liquidity_status':'CANDLE_VOLUME_IS_NOT_EXECUTABLE_BOOK_LIQUIDITY'}
                                    key=_sha({k:payload[k] for k in ('version','symbol','resolution','length','representation','start','end')})
                                    self.db.execute('INSERT INTO patterns VALUES(?,?,?,?,?,?,?,?,?,?,?)',(key,symbol,res,length,kind,start,closed,outcome_end,payload['available_at'],_canon(payload),_sha(payload)))
                                    counts[symbol+'|'+res+'|'+str(length)+'|'+kind]=counts.get(symbol+'|'+res+'|'+str(length)+'|'+kind,0)+1
            manifest={'version':VERSION,'archive_root':str(lake.root),'created_at':time.time(),'sources':sources,'counts':counts,'skipped':skips,
                'rows_sha256':_sha(self.db.execute('SELECT id,sha256 FROM patterns ORDER BY id').fetchall()),
                'resolutions':list(resolutions),'lengths':list(lengths),'max_windows_per_segment_asset':max_windows_per_asset,
                'selection':'latest bounded windows per real contiguous segment; no fitted scaler/encoder',
                'implementation_sha256_LF':hashlib.sha256(Path(__file__).read_bytes().replace(b'\r\n',b'\n')).hexdigest()}
            manifest['manifest_sha256']=_sha(manifest)
            self.db.execute("INSERT INTO pattern_meta VALUES('manifest',?)",(_canon(manifest),));self.db.commit()
        except Exception:self.db.rollback();raise
        _save_atomic(self.directory/'manifest.json',manifest)
        return {'status':'BUILT_FROM_REAL_VERIFIED_CANDLES','manifest':manifest}

    def search(self,query,*,method='euclidean',k=20,min_matches=8,scope='all',regime=None,volatility_range=None,
               liquidity_range=None,history_begin=None,history_end=None,embargo_bars=1,retrospective=False):
        if method not in ('euclidean','dtw','return_structure','historical_random'):raise ValueError('UNKNOWN_SIMILARITY')
        if k<1 or min_matches<2 or scope not in ('all','same') or embargo_bars<1:raise ValueError('INVALID_SEARCH_CONTRACT')
        if query['available_at']>query['decision_time'] and not retrospective:raise ValueError('QUERY_NOT_AVAILABLE_AT_DECISION')
        if liquidity_range is not None:return {'status':'INSUFFICIENT_REAL_HISTORICAL_BOOK_LIQUIDITY','matches':[],'empirical_quantiles':None}
        kind='candle_structure' if method=='return_structure' else query['representation']
        if kind not in query['representations']:return {'status':'QUERY_REPRESENTATION_UNDEFINED','matches':[],'empirical_quantiles':None}
        q=np.asarray(query['representations'][kind],float);step=period_seconds(query['resolution']);candidates=[]
        cutoff=query['start']-embargo_bars*step
        for key,symbol,start,end,available,raw,digest in self.db.execute('SELECT id,symbol,start,outcome_end,available,payload,sha256 FROM patterns WHERE resolution=? AND length=? AND representation=? AND outcome_end<=? ORDER BY id',
                (query['resolution'],query['length'],kind,cutoff)):
            if scope=='same' and symbol!=query['symbol']:continue
            if not retrospective and available>query['decision_time']:continue
            if history_begin is not None and start<history_begin:continue
            if history_end is not None and end>history_end:continue
            p=json.loads(raw)
            if _sha(p)!=digest:raise ValueError('PATTERN_PAYLOAD_HASH_INVALID')
            if regime is not None and p['regime']!=regime:continue
            if volatility_range is not None and not volatility_range[0]<=p['volatility']<=volatility_range[1]:continue
            candidates.append((key,p))
        result={'version':VERSION,'query_id':query['query_id'],'query_cutoff':query['decision_time'],'window':{key:query[key] for key in ('symbol','resolution','length','start','end')},
            'normalization':kind,'similarity':method,'index_sha256':self.manifest()['manifest_sha256'],'scope':scope,'eligible_candidates':len(candidates),
            'track':'RETROSPECTIVE_CANDLE_RESEARCH_NOT_PROVEN_PIT' if retrospective else 'RECEIPT_AWARE_CURRENT_EVIDENCE',
            'embargo_bars':embargo_bars,'promotion':False,'decision_path_eligible':False,'matches':[],
            'confidence':None,'uncertainty':'No independent value-added validation; global temporal de-overlap is conservative, not proof of independence'}
        if not candidates:return {**result,'status':'INSUFFICIENT_HISTORICAL_ANALOGUES','effective_independent_match_count':0,'empirical_quantiles':None}
        vectors=np.array([p['features'] for _,p in candidates]);distances=cdist(q.reshape(1,-1),vectors.reshape(len(vectors),-1),'euclidean')[0]/math.sqrt(q.size)
        if method=='historical_random':distances=np.random.default_rng(8001).random(len(candidates))
        if method=='dtw':
            # Explicit approximate prefilter to bound startup/query work. No
            # outcome is used to choose/refine the shortlist.
            pool=np.argsort(distances,kind='stable')[:min(512,len(candidates))];dtw=np.full(len(candidates),np.inf)
            for i in pool:dtw[i]=constrained_dtw(q,vectors[i],radius=2)
            distances=dtw;result['dtw_euclidean_prefilter_candidates']=len(pool)
        intervals=[]
        for i in np.argsort(distances,kind='stable'):
            if not math.isfinite(distances[i]):continue
            key,p=candidates[i]
            # Across symbols too: same-time outcomes are correlated evidence,
            # not multiple independent trials. Include entire pattern+label.
            if any(not (p['outcome_end']+step<=a or p['start']>=b+step) for a,b in intervals):continue
            intervals.append((p['start'],p['outcome_end']))
            result['matches'].append({'pattern_id':key,'symbol':p['symbol'],'start':p['start'],'end':p['end'],'outcome_end':p['outcome_end'],
                'available_at':p['available_at'],'distance':float(distances[i]),'outcomes':p['outcomes'],'source_sha256':p['source_sha256']})
            if len(intervals)>=k:break
        n=len(intervals);quantiles={}
        for horizon in HORIZONS:
            values=np.array([p['outcomes'][str(horizon)]['close_log_return'] for p in result['matches']])
            if len(values):quantiles[str(horizon)]={'q10':float(np.quantile(values,.1)),'q50':float(np.quantile(values,.5)),'q90':float(np.quantile(values,.9)),
                'positive_fraction':float(np.mean(values>0)),'label':'HISTORICAL_CLOSE_RETURN_NOT_EXECUTABLE_PNL'}
        result.update(status='RESEARCH_ANALOGUES_UNVALIDATED' if n>=min_matches else 'INSUFFICIENT_HISTORICAL_ANALOGUES',
            effective_independent_match_count=n,empirical_quantiles=quantiles if n>=min_matches else None,
            ood_status='NOT_CALIBRATED_NO_RELIABLE_OOD_THRESHOLD')
        result['result_sha256']=_sha(result);return result


def make_query(lake,symbol,resolution='15',length=10,decision_time=None,*,retrospective=False):
    stamp=time.time() if decision_time is None else float(decision_time);step=period_seconds(resolution)
    if stamp>time.time()+1:raise ValueError('FUTURE_QUERY_CLOCK_FORBIDDEN')
    parts,_=_verified_segments(lake.root,lake.db,symbol,resolution)
    parts=[p[p.timestamp+step<=stamp] for p in parts];parts=[p for p in parts if len(p)>=length]
    if not parts:raise ValueError('INSUFFICIENT_VERIFIED_QUERY_WINDOW')
    window=parts[-1].tail(length);annotated=annotate_receipts(lake,symbol,resolution,window)
    available=float(annotated.available_at.max());available=time.time() if not math.isfinite(available) else available
    if decision_time is None:stamp=time.time()
    if not retrospective and available>stamp:raise ValueError('QUERY_AVAILABILITY_AFTER_CUTOFF_USE_CURRENT_RESEARCH_OR_EXPLICIT_RETROSPECTIVE')
    representations={}
    for kind in REPRESENTATIONS:
        try:representations[kind]=representation(window,kind).tolist()
        except ValueError:continue
    if 'relative_ohlcv' not in representations:raise ValueError('PRIMARY_QUERY_REPRESENTATION_UNDEFINED')
    payload={'symbol':symbol,'resolution':resolution,'length':length,'start':int(window.timestamp.iloc[0]),
        'end':int(window.timestamp.iloc[-1])+step,'decision_time':stamp,'available_at':available,
        'representation':'relative_ohlcv','representations':representations}
    payload['query_id']=_sha(payload);return payload


def main():
    from .atlas_archive import Lake
    p=argparse.ArgumentParser();p.add_argument('command',choices=['build','search','status']);p.add_argument('--root',default='atlas_store');p.add_argument('--index-dir',default=DEFAULT_INDEX)
    p.add_argument('--symbol',default='BTCTMN');p.add_argument('--resolution',default='15');p.add_argument('--length',type=int,default=10);p.add_argument('--method',default='euclidean')
    p.add_argument('--max-windows-per-asset',type=int,default=1000);p.add_argument('--output');args=p.parse_args()
    lake=Lake(args.root);index=PatternIndex(args.index_dir,readonly=args.command!='build')
    try:
        if args.command=='build':result=index.build(lake,max_windows_per_asset=args.max_windows_per_asset)
        elif args.command=='status':result=index.manifest()
        else:
            index.verify_sources();result=index.search(make_query(lake,args.symbol,args.resolution,args.length),method=args.method)
        if args.output:_save_atomic(Path(args.output),result)
        print(json.dumps(result,ensure_ascii=False,default=str))
    finally:index.close();lake.close()

if __name__=='__main__':main()
