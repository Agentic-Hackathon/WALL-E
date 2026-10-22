"""Stage 14: forensic, read-only evaluation of Stage 13 research checkpoints.

Original source files and the point-in-time quote anchor are reconstructed from
Stage13's saved SHA manifest and run creation time, rather than from the latest
mutable catalog. Any mismatch to the exact Stage13 split checksum fails closed.

Does not build market observations, train, select, promote, or submit orders.
Local model inference is deliberately distinguished from actual execution PnL.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re

import numpy as np
import pandas as pd

from . import market
from .atlas_challenger_v2 import (_canonical_sha, _records_from_genuine_segment,
    _choose_split, _metadata_rows, _data_for_model, CONTEXT, HORIZON, PERIOD)
from .atlas_deep import COLS, _torch, build_model
from .atlas_feature_health import _hexsha
from .atlas_mode import ExecutionMode, require_mode
from .atlas_operational import _read_connection, _table

RUN_PATTERN=re.compile(r'^\d{8}T\d{6}Z_[0-9a-f]{8}$')
ARMS=('V1_COMMON','V2_COMMON','V2_EXPANDED')
QUANT=np.array([.1,.5,.9],dtype=np.float64)


def _run_directory(root,run_dir):
    root=Path(root).resolve()
    parent=(root/'research_challengers'/'stage13_paired_v2').resolve()
    if run_dir is None:
        return None
    path=Path(run_dir)
    if not path.is_absolute():
        path=root/path
    # Never load a checkpoint outside the dedicated Stage13 research directory.
    path=path.resolve()
    if path.parent!=parent or not RUN_PATTERN.fullmatch(path.name):
        raise ValueError('UNTRUSTED_RESEARCH_RUN_PATH')
    return path


def _load_saved_run(root,run_dir):
    directory=_run_directory(root,run_dir)
    if directory is None or not directory.is_dir():
        return None
    files=('report.json','source_manifest.json')
    if not all((directory/f).is_file() for f in files):
        raise ValueError('INCOMPLETE_RESEARCH_RUN')
    report=json.loads((directory/'report.json').read_text(encoding='utf-8'))
    manifest=json.loads((directory/'source_manifest.json').read_text(encoding='utf-8'))
    if report.get('status')!='COMPLETED_RESEARCH_ONLY_NOT_OOS_ECONOMICS':
        raise ValueError('UNVERIFIED_STAGE13_TRAINING_STATUS')
    if (report.get('policy')!='STAGE13_PAIRED_GLOBAL_PURGED_V1_V2_COMPARISON'
        or report.get('feature_recipe_v2')!='EXPERIMENTAL_CHALLENGER_FEATURE_RECIPE_V2_ZERO_DENOMINATOR_CONVENTIONS'
        or report.get('risk_or_champion_changed') is not False
        or report.get('real_order_submission') is not False):
        raise ValueError('UNTRUSTED_STAGE13_RESEARCH_PROTOCOL')
    recipe_digest=hashlib.sha256(Path(__file__).with_name('atlas_feature_recipe.py').read_bytes()).hexdigest()
    if recipe_digest!=report.get('v2_feature_recipe_sha256'):
        raise ValueError('CHALLENGER_V2_FEATURE_RECIPE_SHA256_MISMATCH')
    if not isinstance(manifest,list) or _canonical_sha(manifest)!=report.get('source_manifest_sha256'):
        raise ValueError('SAVED_SOURCE_MANIFEST_MISMATCH')
    arms=report.get('arms')
    if (not isinstance(arms,list) or {a.get('arm') for a in arms}!=set(ARMS) or len(arms)!=3):
        raise ValueError('INCOMPLETE_RESEARCH_ARMS')
    return directory,report,manifest


def _frozen_quote_anchors(root,source_symbols,run_time):
    db=_read_connection(Path(root)/'forward_observations.sqlite')
    if db is None:raise ValueError('MISSING_ORIGINAL_QUOTE_DATABASE')
    try:
        if not _table(db,'quotes'):raise ValueError('MISSING_QUOTE_RECEIPTS')
        anchors={}
        for symbol in source_symbols:
            record=db.execute('SELECT MAX(observed_epoch) FROM quotes WHERE symbol=? AND observed_epoch<=?',
                              (symbol,run_time)).fetchone()
            if not record or record[0] is None or not math.isfinite(float(record[0])):
                raise ValueError('NO_GENUINE_QUOTE_BEFORE_RUN')
            anchors[symbol]=float(record[0])
        return anchors
    finally:db.close()


def _frozen_segments(root,manifest):
    """Strictly read only the exact genuine sources named by Stage13, not new chunks."""
    root=Path(root).resolve()
    sources=defaultdict(list)
    for entry in manifest:
        if not isinstance(entry,dict):raise ValueError('INVALID_MANIFEST_ENTRY')
        symbol=entry.get('symbol');rel=entry.get('relative_file');digest=entry.get('sha256')
        if (not isinstance(symbol,str) or not symbol.isalnum() or not symbol.isupper()
            or entry.get('resolution')!='15' or not isinstance(rel,str)
            or not isinstance(digest,str) or not re.fullmatch('[0-9a-f]{64}',digest)):
            raise ValueError('INVALID_MANIFEST_SOURCE')
        path=(root/rel).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            raise ValueError('SOURCE_MISSING_OR_PATH_ESCAPE')
        if _hexsha(path)!=digest:raise ValueError('SOURCE_SHA256_MISMATCH')
        source=market.normalize(pd.read_csv(path))
        stamps=source.timestamp.to_numpy(dtype=np.int64)
        if np.any(stamps%PERIOD):raise ValueError('OFF_GRID_SOURCE')
        if len(stamps)==0:raise ValueError('EMPTY_SOURCE')
        sources[symbol].append((int(entry['begin']),rel,source))
    if not sources:raise ValueError('NO_ARCHIVED_SOURCE_FILES')
    segments={}
    for symbol,files in sources.items():
        # The original archive code sorted by begin. Filename resolves ties.
        frame=pd.concat((x[2] for x in sorted(files,key=lambda x:(x[0],x[1]))),ignore_index=True)
        duplicate=frame[frame.timestamp.duplicated(keep=False)]
        if not duplicate.empty and (duplicate.groupby('timestamp')[['open','high','low','close','volume']]
                                    .nunique().to_numpy()>1).any():
            raise ValueError('CONFLICTING_ORIGINAL_CANDLES')
        frame=frame.drop_duplicates('timestamp').sort_values('timestamp').reset_index(drop=True)
        stamps=frame.timestamp.to_numpy(dtype=np.int64)
        cuts=np.flatnonzero(np.diff(stamps)!=PERIOD)+1
        segments[symbol]=[frame.iloc[ids].reset_index(drop=True) for ids in np.split(np.arange(len(frame)),cuts) if len(ids)]
    return segments


def _recover_split(root, directory, report, manifest):
    # Training folder name is set AFTER Stage13 data preflight. Quotes received
    # after that instant were unknowable to the original trainer and excluded.
    run_time=datetime.strptime(directory.name[:16],'%Y%m%dT%H%M%SZ').replace(tzinfo=timezone.utc).timestamp()
    symbols=list(dict.fromkeys(m['symbol'] for m in manifest))
    anchors=_frozen_quote_anchors(root,symbols,run_time)
    segments=_frozen_segments(root,manifest)
    common={};extra={}
    for symbol in symbols:
        for index,part in enumerate(segments[symbol]):
            closed=part.loc[part.timestamp+PERIOD<=anchors[symbol]].reset_index(drop=True)
            c,e,_=_records_from_genuine_segment(symbol,index,closed)
            if (set(c)&set(common) or set(e)&(set(extra)|set(common))
                or set(c)&set(extra)):
                raise ValueError('DUPLICATE_SNAPSHOT_SAMPLE_KEY')
            common.update(c);extra.update(e)
    if (len(common)!=report['original_common_total'] or len(extra)!=report['v2_only_total']):
        raise ValueError('ORIGINAL_DATASET_NOT_RECONSTRUCTABLE')
    split=_choose_split(common,extra,int(report['validation_hours_effective']))
    if split is None or split['cutoff']!=report.get('global_cutoff_feature_epoch'):
        raise ValueError('ORIGINAL_SPLIT_NOT_RECONSTRUCTABLE')
    actual=_canonical_sha({'train':_metadata_rows(split['train_v1']),
         'validation':_metadata_rows(split['valid_v1']),
         'extra_v2_train':_metadata_rows(split['extra_train_v2'])})
    if actual!=report.get('split_sha256'):
        raise ValueError('ORIGINAL_SAMPLE_IDS_NOT_RECONSTRUCTABLE')
    if (len(split['extra_valid_v2'])!=report['v2_additional_validation_samples_HELD_OUT_NOT_TRAINED']
        or len(split['train_v1'])!=report['common_train_samples']
        or len(split['valid_v1'])!=report['common_validation_samples']):
        raise ValueError('SPLIT_COUNTS_MISMATCH')
    return split,anchors


def _load_models(directory,report):
    torch=_torch()
    result={}
    for record in report['arms']:
        arm=record['arm'];path=(directory/(arm+'.pt')).resolve()
        if path.parent!=directory or not path.is_file() or _hexsha(path)!=record.get('checkpoint_sha256'):
            raise ValueError('CHECKPOINT_FILE_SHA256_MISMATCH')
        # Reject arbitrary pickled Python object constructions, even from local files.
        saved=torch.load(path,map_location='cpu',weights_only=True)
        meta=saved.get('metadata',{})
        if (meta.get('arm')!=arm or meta.get('checkpoint_kind')!='NON_PROMOTABLE_RESEARCH_ONLY'
            or meta.get('split_sha256')!=report.get('split_sha256')
            or meta.get('source_manifest_sha256')!=report.get('source_manifest_sha256')
            or meta.get('model_feature_columns')!=COLS or meta.get('seed')!=20261022
            or meta.get('validation_loss')!=record.get('validation_loss')):
            raise ValueError('CHECKPOINT_PROVENANCE_MISMATCH')
        architecture=meta.get('architecture')
        if architecture not in ('patchtst','itransformer'):
            raise ValueError('UNSUPPORTED_RESEARCH_ARCHITECTURE')
        model=build_model(architecture,CONTEXT,len(COLS),device='cpu')
        model.load_state_dict(saved['state_dict'],strict=True)
        model.eval()
        result[arm]=model
    return result


def _predict(model,rows):
    if not rows:return np.empty((0,3),dtype=np.float64)
    torch=_torch();X,_=_data_for_model(rows)
    outputs=[]
    with torch.inference_mode():
        for start in range(0,len(X),32):
            outputs.append(model(torch.from_numpy(X[start:start+32])).cpu().numpy())
    result=np.concatenate(outputs).astype(np.float64)
    if result.shape!=(len(rows),3) or not np.isfinite(result).all():
        raise ValueError('NONFINITE_CHECKPOINT_PREDICTIONS')
    return result


def _metrics(rows,pred):
    if not rows:return {'n':0}
    y=np.array([r['y'] for r in rows],dtype=np.float64)
    residual=y[:,None]-pred
    pin=np.maximum(QUANT*residual,(QUANT-1)*residual)
    crossing=np.maximum(pred[:,:2]-pred[:,1:],0).mean()
    return {'n':len(rows),
       'raw_pinball':round(float(pin.mean()),9),
       'pinball_plus_stage13_crossing_penalty':round(float(pin.mean()+.05*crossing),9),
       'median_q50_absolute_error':round(float(np.median(abs(y-pred[:,1]))),9),
       'q50_directional_accuracy':round(float(np.mean((pred[:,1]>0)==(y>0))),6),
       'q10_empirical_lower_coverage':round(float(np.mean(y>=pred[:,0])),6),
       'q90_empirical_upper_coverage':round(float(np.mean(y<=pred[:,2])),6),
       'quantile_crossing_rate':round(float(np.mean((pred[:,0]>pred[:,1])|(pred[:,1]>pred[:,2]))),6)}


def _per_symbol(rows,pred):
    indices=defaultdict(list)
    for i,r in enumerate(rows):indices[r['symbol']].append(i)
    return {symbol:_metrics([rows[i] for i in ids],pred[ids]) for symbol,ids in sorted(indices.items())}


def evaluate(root,run_dir=None):
    """Evaluate saved real Stage13 models; never writes SQLite or checkpoints."""
    require_mode(ExecutionMode.BACKTEST,permitted=(ExecutionMode.BACKTEST,),operation='challenger-evaluate')
    root=Path(root).resolve()
    base={'mode':'BACKTEST_READ_ONLY_SAVED_CHECKPOINT_EVALUATION',
          'orders':False,'network_requests':False,'db_mutation':False,
          'local_model_inference':True,'training_or_model_promotion':False,
          'shared_validation_was_used_for_epoch_selection':True,
          'extra_v2_validation_not_used_for_training_or_epoch_selection':True,
          'real_trading_pnl_established':False}
    if run_dir is None:return {**base,'status':'EXPLICIT_STAGE13_RUN_DIRECTORY_REQUIRED'}
    try:
        data=_load_saved_run(root,run_dir)
        if data is None:return {**base,'status':'RESEARCH_RUN_NOT_FOUND'}
        directory,report,manifest=data
        split,anchors=_recover_split(root,directory,report,manifest)
        models=_load_models(directory,report)
        groups={
            'V1_COMMON':split['valid_v1'],
            'V2_COMMON':split['valid_v2'],
            'V2_EXPANDED':split['valid_v2']}
        shared={}
        for arm,rows in groups.items():
            pred=_predict(models[arm],rows)
            shared[arm]={'overall':_metrics(rows,pred),'per_symbol':_per_symbol(rows,pred)}
        extra=split['extra_valid_v2']
        additional={}
        for arm in ('V2_COMMON','V2_EXPANDED'):
            pred=_predict(models[arm],extra)
            additional[arm]={'overall':_metrics(extra,pred),'per_symbol':_per_symbol(extra,pred)}
        c=shared['V2_COMMON']['overall']['raw_pinball']
        x=shared['V2_EXPANDED']['overall']['raw_pinball']
        e=additional['V2_EXPANDED']['overall'].get('raw_pinball')
        cextra=additional['V2_COMMON']['overall'].get('raw_pinball')
        return {**base,'status':'RECONSTRUCTED_ORIGINAL_STAGE13_SNAPSHOT',
            'run_directory':str(directory),
            'source_chunks_sha256_verified':len(manifest),
            'original_split_sha256_verified':report['split_sha256'],
            'frozen_quote_anchor_epoch_per_symbol':anchors,
            'common_validation_count':len(split['valid_v2']),
            'v2_only_held_out_validation_count':len(extra),
            'shared_epoch_selected_validation':shared,
            'v2_only_extra_held_out_validation':additional,
            'expanded_minus_common_shared_raw_pinball':round(x-c,9),
            'expanded_minus_common_v2_only_raw_pinball':round(e-cextra,9) if e is not None and cextra is not None else None,
            'warning':'No trade simulation. 8h internal shared validation not independent OOS; V2-only heldout is small and correlated. Cached checkpoint model code/weight runtime build is not a cryptographic proof of the original training environment.'}
    except (ValueError,KeyError,TypeError,RuntimeError,OSError,OverflowError,AttributeError) as exc:
        # Do not dump model, source or free-text exception contents to console.
        return {**base,'status':'FAIL_CLOSED_SAVED_RUN_OR_PROVENANCE_MISMATCH',
                'failure_class':type(exc).__name__,
                'failure_code':str(exc) if str(exc).isupper() and len(str(exc))<100 else 'UNVERIFIABLE_ARCHIVE_OR_CHECKPOINT'}
