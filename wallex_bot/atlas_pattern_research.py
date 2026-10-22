"""M8 chronological analogue research, reuse Atlas M5 quantile metrics.

No price-return result is a Fill/PnL. Retrospective legacy availability is
explicitly separated from actual current receipt-aware searches. No model
selection/promotion on the final period. No encoder trained on test windows.
"""
import argparse,json,time
from pathlib import Path
import numpy as np
from .atlas_archive import Lake,period_seconds
from .atlas_patterns import PatternIndex,make_query,representation,RESOLUTIONS,DEFAULT_INDEX
from .atlas_feature_health import _verified_segments
from .atlas_forward import _sha
from .atlas_m5_models import metrics
from .atlas_portfolio_report import write_csv
from .atlas_liquidation import _save_atomic

METHODS=('euclidean','dtw','return_structure','historical_random')


def multiscale_evidence(lake,index,symbol,*,cutoff=None,length=10):
    """Backward closed-bucket alignment. Different horizons are NOT averaged."""
    cutoff=time.time() if cutoff is None else cutoff;results={}
    for res in RESOLUTIONS:
        try:
            q=make_query(lake,symbol,res,length,decision_time=cutoff)
            result=index.search(q);result['closed_bucket_end']=q['end'];result['staleness_seconds']=cutoff-q['end']
            result['horizon_seconds']={str(h):h*period_seconds(res) for h in (1,3,6,12)};results[res]=result
        except ValueError as exc:results[res]={'status':str(exc),'empirical_quantiles':None}
    return {'version':'ATLAS_MULTISCALE_ANALOGUES_V1','symbol':symbol,'decision_at':cutoff,'timeframes':results,
        'fusion':'ALIGNED_EVIDENCE_BUNDLE_ONLY; no averaging incompatible horizons or unvalidated forecasts',
        'decision_path_eligible':False}


def run(root='atlas_store',index_dir=DEFAULT_INDEX,*,max_queries=8,out='reports'):
    lake=Lake(root);index=PatternIndex(index_dir,readonly=True);out=Path(out);out.mkdir(parents=True,exist_ok=True)
    rows=[];samples=[];failures=[];current=[];started=time.time()
    try:
        index.verify_sources();manifest=index.manifest()
        # Universe is fixed by this protocol, not selected by test returns.
        for res in RESOLUTIONS:
            step=period_seconds(res)
            for symbol in ('BTCTMN','ETHTMN'):
                try:segments,_=_verified_segments(lake.root,lake.db,symbol,res)
                except ValueError as exc:failures.append({'symbol':symbol,'resolution':res,'reason':str(exc)});continue
                segments=[p for p in segments if len(p)>=64]
                if not segments:failures.append({'symbol':symbol,'resolution':res,'reason':'INSUFFICIENT_REAL_CONTIGUOUS_HISTORY'});continue
                frame=segments[-1]
                for length in (7,10):
                    # Disjoint outcome intervals within each symbol/timeframe;
                    # 60/20/20 fixed temporal partition of query end positions.
                    endpoints=list(range(length+12,len(frame)-12,13))
                    endpoints=endpoints[-max_queries:]
                    for position,end in enumerate(endpoints):
                        window=frame.iloc[end-length+1:end+1];cutoff=int(window.timestamp.iloc[-1])+step
                        partition='train_diagnostic' if position<.6*len(endpoints) else ('validation' if position<.8*len(endpoints) else 'test_once')
                        representations={}
                        for kind in ('relative_ohlcv','candle_structure'):
                            try:representations[kind]=representation(window,kind).tolist()
                            except ValueError:continue
                        if 'relative_ohlcv' not in representations:continue
                        query={'symbol':symbol,'resolution':res,'length':length,'start':int(window.timestamp.iloc[0]),'end':cutoff,
                            'decision_time':cutoff,'available_at':time.time(),'representation':'relative_ohlcv','representations':representations}
                        query['query_id']=_sha(query)
                        actual=float(np.log(float(frame.close.iloc[end+3])/float(frame.close.iloc[end])))
                        observations={}
                        for method in METHODS:
                            result=index.search(query,method=method,retrospective=True)
                            if result.get('empirical_quantiles'):
                                p=result['empirical_quantiles']['3'];observations[method]=[p['q10'],p['q50'],p['q90']]
                        # All compared methods share the exact query, target
                        # and available historical labels. Missing is not zero.
                        sample={'symbol':symbol,'resolution':res,'length':length,'cutoff':cutoff,'partition':partition,
                            'actual_close_log_return':actual,'horizon_seconds':3*step,'predictions':observations,
                            'pit_status':'RETROSPECTIVE_ONLY_LEGACY_RECEIPTS_NOT_PROVEN_AT_HISTORICAL_CUTOFF'}
                        samples.append(sample)
        for res in RESOLUTIONS:
            for length in (7,10):
                for partition in ('train_diagnostic','validation','test_once'):
                    shared=[s for s in samples if s['resolution']==res and s['length']==length and s['partition']==partition and set(METHODS)<=s['predictions'].keys()]
                    for method in (*METHODS,'zero_persistence'):
                        metric=metrics([s['actual_close_log_return'] for s in shared],
                            [s['predictions'][method] if method!='zero_persistence' else [0.,0.,0.] for s in shared]) if shared else {'n':0}
                        rows.append({'resolution':res,'length':length,'partition':partition,'method':method,
                            'status':'RETROSPECTIVE_DIAGNOSTIC_NOT_DEPLOYABLE' if len(shared)>=30 else 'INSUFFICIENT_MATCHED_VALIDATION',
                            'promotion':False,'net_trading_pnl':None,**metric})
        for symbol in ('BTCTMN','ETHTMN'):
            for length in (7,10):
                try:
                    q=make_query(lake,symbol,length=length);result=index.search(q)
                    result['query_staleness_seconds']=q['decision_time']-q['end'];current.append(result)
                except ValueError as exc:failures.append({'symbol':symbol,'length':length,'reason':str(exc)})
        result={'protocol':'ATLAS_PATTERN_RESEARCH_V1','index_sha256':manifest['manifest_sha256'],
            'real_index_rows':index.db.execute('SELECT count(*) FROM patterns').fetchone()[0],
            'universe_with_eligible_windows':index.db.execute('SELECT count(DISTINCT symbol) FROM patterns').fetchone()[0],
            'index_resolutions':manifest['resolutions'],'index_lengths':manifest['lengths'],'skipped':manifest['skipped'],
            'current_receipt_aware_searches':current,'retrospective_samples':samples,'failures':failures,
            'multiscale':multiscale_evidence(lake,index,'BTCTMN'),
            'model_selection':'NONE; methods predeclared, no selection on held-out period',
            'economic_edge':'NO_VERIFIED_ECONOMIC_EDGE','pattern_decision_path_eligible':False,
            'validation_status':'INSUFFICIENT_INDEPENDENT_PIT_ECONOMIC_VALIDATION',
            'known_selection_bias':'archive availability and current catalog; index bounded by segment/window count, not return',
            'historical_costs':None,'historical_fills':None,'elapsed_seconds':time.time()-started}
        _save_atomic(out/'m8_pattern_retrieval_results.json',result)
        write_csv(out/'m8_pattern_retrieval_ablation.csv',rows)
        print(json.dumps({'real_index_rows':result['real_index_rows'],'assets':result['universe_with_eligible_windows'],
            'retrospective_samples':len(samples),'current_searches':len(current),'status':result['validation_status']}))
        return result
    finally:index.close();lake.close()


def main():
    p=argparse.ArgumentParser();p.add_argument('--root',default='atlas_store');p.add_argument('--index-dir',default=DEFAULT_INDEX);p.add_argument('--max-queries',type=int,default=8);p.add_argument('--output-dir',default='reports')
    a=p.parse_args();run(a.root,a.index_dir,max_queries=a.max_queries,out=a.output_dir)

if __name__=='__main__':main()
