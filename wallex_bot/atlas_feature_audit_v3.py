"""Read-only Milestone 3 reports over hash-verified genuine archive candles."""
from __future__ import annotations
import json, math
from pathlib import Path
import numpy as np
import pandas as pd

from .atlas_archive import Lake
from .atlas_feature_provenance import annotate_receipts,align_available
from .atlas_feature_health import _read_catalog_symbols
from .atlas_feature_registry import (REGISTRY, SECONDS, TIMEFRAMES, align_asof, compute_cross_asset_features,
    compute_ohlcv_features, registry_payload, sync_requirements)

def _closed_segment(lake,symbol,resolution,now):
    try:parts=lake.load(symbol,resolution)
    except (ValueError,RuntimeError,OSError,pd.errors.ParserError):return None
    period=SECONDS[resolution];eligible=[x[x.timestamp.astype('int64')+period<=now] for x in parts]
    eligible=[x.reset_index(drop=True) for x in eligible if len(x)]
    return eligible[-1] if eligible else None

def _feature_rows(symbol,resolution,segment):
    defs=[x for x in REGISTRY if x.family not in ('microstructure','cross_asset')]
    if segment is None:return [{'symbol':symbol,'timeframe':resolution,'feature':x.name,'family':x.family,
                                 'status':'MISSING_OR_UNVERIFIED_TIMEFRAME','available_rows':0,'nonfinite_rate':None,
                                 'warmup_bars':x.warmup_bars} for x in defs]
    matrix=compute_ohlcv_features(segment)
    rows=[]
    for spec in defs:
        values=matrix[spec.name].to_numpy(dtype=float);finite=np.isfinite(values)
        usable=max(0,len(values)-spec.warmup_bars+1)
        rows.append({'symbol':symbol,'timeframe':resolution,'feature':spec.name,'family':spec.family,
                     'status':('NO_FINITE_FEATURE_VALUES' if not finite.any() else
                               'LATEST_FEATURE_UNAVAILABLE' if not finite[-1] else 'FINITE_LATEST_OBSERVATION'),
                     'latest_finite':bool(finite[-1]) if len(finite) else False,
                     'ready':bool(len(values)>=spec.warmup_bars and finite[-1]),'available_rows':int(finite.sum()),
                     'effective_rows_after_warmup':int(finite[spec.warmup_bars-1:].sum()) if len(values)>=spec.warmup_bars else 0,
                     'nonfinite_rate':round(float(1-finite.mean()),8) if len(values) else None,
                     'warmup_bars':spec.warmup_bars,'observed_bars':len(values),'theoretical_post_warmup_rows':usable})
    return rows

def build_reports(root,output_dir='reports',top=8):
    """Create required artifacts from real archive only; no sync, no model fitting."""
    root=Path(root).resolve();out=Path(output_dir);out.mkdir(parents=True,exist_ok=True)
    if not root.exists() or not (root/'catalog.sqlite').is_file():
        payload={'status':'NO_EXISTING_CATALOG','mode':'READ_ONLY_NO_NETWORK','symbols':[]}
        (out/'feature_registry.json').write_text(json.dumps(registry_payload(),ensure_ascii=False,indent=2),encoding='utf8')
        for name,columns in [('feature_health.csv',['symbol','timeframe','feature','status']),('feature_coverage.csv',['symbol','timeframe','status']),('feature_redundancy.csv',['symbol','timeframe','feature_a','feature_b','status']),('feature_ablation.csv',['family','status'])]:pd.DataFrame(columns=columns).to_csv(out/name,index=False)
        for name,data in [('multitimeframe_alignment.json',payload),('per_asset_readiness.json',payload),('feature_sync_requirements.json',{'advanced':sync_requirements()})]: (out/name).write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf8')
        return payload
    lake=Lake(root)
    try:
        now=int(pd.Timestamp.now(tz='UTC').timestamp());symbols=_read_catalog_symbols(lake.db,top)
        (out/'feature_registry.json').write_text(json.dumps(registry_payload(),ensure_ascii=False,indent=2),encoding='utf8')
        health=[];coverage=[];redundancy=[];alignment=[];readiness=[];raw15={}
        for symbol in symbols:
            matrices={}
            for label,res in TIMEFRAMES.items():
                segment=_closed_segment(lake,symbol,res,now);health.extend(_feature_rows(symbol,res,segment))
                if res=='15' and segment is not None:raw15[symbol]=segment
                coverage.append({'symbol':symbol,'timeframe':res,'label':label,'status':'VERIFIED_CLOSED_SEGMENT' if segment is not None else 'MISSING_OR_UNVERIFIED_TIMEFRAME','closed_bars':len(segment) if segment is not None else 0})
                if segment is not None:
                    try:
                        values=compute_ohlcv_features(segment)
                        receipts=annotate_receipts(lake,symbol,res,segment)
                        for key in ('candle_close_at','retrieved_at','available_at','pit_status'):values[key]=receipts[key]
                        matrices[res]=values
                    except (ValueError,TypeError,FloatingPointError):pass
            # PIT alignment is observed, not assumed: as-of only from a completed
            # source candle into the completed 15m base candle.
            base=matrices.get('15')
            if base is not None:
                for res,other in matrices.items():
                    if res=='15':continue
                    # Separate a retrospective candle-clock diagnostic from the
                    # actual receipt-aware historical decision join.
                    joined=align_available(pd.DataFrame({'decision_at':base.timestamp.astype('int64')+900}),other)
                    feature_columns=[x.name for x in REGISTRY if x.family not in ('microstructure','cross_asset')]
                    alignment.append({'symbol':symbol,'base_resolution':'15','source_resolution':res,
                        'status':'RECEIPT_AWARE_JOIN_LEGACY_ROWS_EXCLUDED',
                        'base_rows':len(base),'aligned_rows':int(joined[feature_columns].notna().any(axis=1).sum()),
                        'source_rows_with_verified_receipt':int(other.available_at.notna().sum()),
                        'legacy_rows_with_unknown_availability':int(other.available_at.isna().sum()),
                        'forward_fill_prices':False})
                usable=base[[x.name for x in REGISTRY if x.family not in ('microstructure','cross_asset')]].replace([np.inf,-np.inf],np.nan)
                for a in range(len(usable.columns)):
                    for b in range(a+1,len(usable.columns)):
                        pair=usable.iloc[:,[a,b]].dropna()
                        if len(pair)<20:continue
                        if pair.iloc[:,0].std()==0 or pair.iloc[:,1].std()==0:continue
                        corr=float(pair.iloc[:,0].corr(pair.iloc[:,1]))
                        if math.isfinite(corr) and abs(corr)>=.95:
                            redundancy.append({'symbol':symbol,'timeframe':'15','feature_a':usable.columns[a],'feature_b':usable.columns[b],
                                               'pearson_correlation':round(corr,8),'samples':len(pair),'status':'HIGH_CORRELATION_RESEARCH_REVIEW'})
            req=sync_requirements('advanced');item=[]
            for res,need in req.items():
                bars=next((r['closed_bars'] for r in coverage[::-1] if r['symbol']==symbol and r['timeframe']==res),0)
                item.append({'resolution':res,'required_warmup_bars':need['warmup_bars'],'verified_closed_bars':bars,
                             'ready':bars>=need['warmup_bars'] and all(row.get('ready',False) for row in health if row['symbol']==symbol and row['timeframe']==res),
                             'reason':'NUMERICAL_READINESS_REQUIRED_IN_ADDITION_TO_WARMUP'})
            readiness.append({'symbol':symbol,'profile':'advanced','ready':all(x['ready'] for x in item),'timeframes':item})
        benchmark=raw15.get('BTCTMN')
        cross_defs=[x for x in REGISTRY if x.family=='cross_asset']
        for symbol in symbols:
            if benchmark is None or symbol not in raw15:
                health.extend({'symbol':symbol,'timeframe':'15','feature':x.name,'family':x.family,
                    'status':'MISSING_ALIGNED_VERIFIED_BTC_TMN','available_rows':0,'nonfinite_rate':None,'warmup_bars':x.warmup_bars} for x in cross_defs)
                continue
            cross=compute_cross_asset_features(raw15[symbol],benchmark)
            for spec in cross_defs:
                finite=np.isfinite(cross[spec.name].to_numpy(dtype=float));health.append({'symbol':symbol,'timeframe':'15','feature':spec.name,'family':spec.family,
                    'status':'MEASURED_CLOSED_TIME_ALIGNED_BTC_LEGACY_PIT_UNCERTAIN','available_rows':int(finite.sum()),'nonfinite_rate':round(float(1-finite.mean()),8) if len(finite) else None,'warmup_bars':spec.warmup_bars,'observed_bars':len(cross)})
        for symbol in symbols:
            for spec in (x for x in REGISTRY if x.family=='microstructure'):
                health.append({'symbol':symbol,'timeframe':'snapshot','feature':spec.name,'family':spec.family,
                    'status':'NO_TIME_MATCHED_REAL_ORDER_BOOK_SNAPSHOT','available_rows':0,'nonfinite_rate':None,'warmup_bars':spec.warmup_bars})
        # Snapshot-only exploration: deliberately no new model or feature selection.
        ablation=[{'family':family,'status':'INSUFFICIENT_VALIDATION_DATA','reason':'Milestone 3 does not fit/promote a model; temporal ablation is deferred'} for family in sorted({x.family for x in REGISTRY})]
        pd.DataFrame(health).to_csv(out/'feature_health.csv',index=False);pd.DataFrame(coverage).to_csv(out/'feature_coverage.csv',index=False)
        pd.DataFrame(redundancy,columns=['symbol','timeframe','feature_a','feature_b','pearson_correlation','samples','status']).to_csv(out/'feature_redundancy.csv',index=False)
        pd.DataFrame(ablation).to_csv(out/'feature_ablation.csv',index=False)
        (out/'multitimeframe_alignment.json').write_text(json.dumps({'status':'READ_ONLY_REAL_ARCHIVE','alignments':alignment,'rules':{'join':'backward_asof_by_verified_receipt_available_at','legacy_availability':'UNKNOWN_EXCLUDED_FROM_HISTORICAL_JOIN','forward_fill_prices':False}},ensure_ascii=False,indent=2),encoding='utf8')
        (out/'per_asset_readiness.json').write_text(json.dumps({'status':'READ_ONLY_REAL_ARCHIVE','profile':'advanced','assets':readiness,'no_global_blocking':True},ensure_ascii=False,indent=2),encoding='utf8')
        (out/'feature_sync_requirements.json').write_text(json.dumps({'status':'REGISTRY_DERIVED_DEMAND','advanced':sync_requirements('advanced'),'watch_core':sync_requirements('watch_core'),'automatic_startup_cap_hours':72,'longer_history':'reported_missing; never silently backfilled'},ensure_ascii=False,indent=2),encoding='utf8')
        return {'status':'COMPLETED_READ_ONLY_REAL_ARCHIVE','symbols':symbols,'feature_count':len(REGISTRY),'health_rows':len(health),'high_correlation_pairs':len(redundancy),'output_dir':str(out)}
    finally:lake.close()
