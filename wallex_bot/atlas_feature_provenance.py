"""V3.1 conservative receipt-aware candle features; no archive mutations.

Independent implementation over Milestone 2 chunk_observations. A close-time
join is not proof that this archive possessed the input at that historical time.
"""
import numpy as np
import pandas as pd
import json
import sqlite3
from datetime import datetime,timezone
from pathlib import Path
from .atlas_archive import period_seconds,sha


def annotate_receipts(lake,symbol,resolution,frame):
    result=frame.copy();period=period_seconds(resolution)
    result['candle_close_at']=result.timestamp.astype('int64')+period
    rows=lake.db.execute('''SELECT c.filename,c.sha256,o.retrieved_at,o.available_at
        FROM chunks c LEFT JOIN chunk_observations o ON c.filename=o.filename
        WHERE c.symbol=? AND c.resolution=? AND c.status='COMPLETE' ''',(symbol,resolution)).fetchall()
    receipts=[];legacy=0
    for filename,digest,retrieved,available in rows:
        path=(lake.root/filename).resolve()
        if not path.is_relative_to(lake.root.resolve()) or not path.is_file() or sha(path)!=digest:
            raise ValueError('UNVERIFIED_FEATURE_SOURCE')
        if retrieved is None or available is None:legacy+=1;continue
        try:
            rt=pd.Timestamp(retrieved);at=pd.Timestamp(available)
            if rt.tzinfo is None or at.tzinfo is None:legacy+=1;continue
            receipts.append((rt.timestamp(),max(rt.timestamp(),at.timestamp())))
        except (ValueError,TypeError):legacy+=1
    # Indicators can depend on the entire contiguous prefix (EMA/OBV). A
    # conservative whole-input maximum avoids retroactive indicator availability.
    known=bool(receipts) and legacy==0
    result['retrieved_at']=max((x[0] for x in receipts),default=np.nan) if known else np.nan
    result['available_at']=np.maximum(result.candle_close_at,max((x[1] for x in receipts),default=np.nan)) if known else np.nan
    result['pit_status']='RECEIPTS_VERIFIED_CONSERVATIVE_PREFIX' if known else 'LEGACY_AVAILABILITY_UNCERTAIN'
    return result


def align_available(base,other,*,cutoff_column='decision_at'):
    """Reject unknown availability, backward join at the explicit decision time."""
    if cutoff_column not in base or 'available_at' not in other:raise ValueError('receipt-aware keys required')
    right=other.loc[other.available_at.notna()].sort_values('available_at').copy()
    left=base.sort_values(cutoff_column).copy()
    left[cutoff_column]=left[cutoff_column].astype('float64')
    right['available_at']=right['available_at'].astype('float64')
    if right.empty:
        result=left.copy()
        for col in right.columns:
            if col not in result:result[col]=np.nan
        return result
    return pd.merge_asof(left,right,left_on=cutoff_column,right_on='available_at',direction='backward')


def microstructure_at(root,symbol,cutoff_epoch,*,max_age_seconds=300):
    """Read an actual stored order book, verify its receipt, then remeasure it.

    No OHLCV argument is accepted. The real quote's local receipt determines
    availability; a stale or missing book yields missing features.
    """
    from .atlas_forward import _sha
    from .live_scout import measure_book
    from .atlas_feature_registry import compute_microstructure_features
    absent={'book_spread_bps':None,'book_imbalance':None}
    path=(Path(root)/'forward_observations.sqlite').resolve()
    if not path.is_file():return {'status':'NO_REAL_SNAPSHOT','features':absent}
    db=sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)
    try:
        row=db.execute('''SELECT symbol,observed_epoch,best_bid,best_ask,mid,raw_book,receipt_sha256
            FROM quotes WHERE symbol=? AND observed_epoch<=? ORDER BY observed_epoch DESC LIMIT 1''',
            (symbol,float(cutoff_epoch))).fetchone()
    finally:db.close()
    if row is None:return {'status':'NO_REAL_SNAPSHOT_AT_CUTOFF','features':absent}
    name,stamp,bid,ask,mid,raw,digest=row;book=json.loads(raw)
    payload={'symbol':name,'observed_epoch':stamp,'best_bid':bid,'best_ask':ask,'mid':mid,'raw_book':book}
    if _sha(payload)!=digest:return {'status':'SNAPSHOT_RECEIPT_HASH_MISMATCH','features':absent}
    provenance={'source_sha256':digest,'observed_at':datetime.fromtimestamp(stamp,timezone.utc).isoformat(),
                'source':'forward_observations.sqlite.quotes','receipt_id_policy':'SHA256_CANONICAL_ACTUAL_QUOTE'}
    if float(cutoff_epoch)-stamp>max_age_seconds:return {'status':'STALE_REAL_SNAPSHOT','features':absent,'provenance':provenance}
    measured=measure_book(book,notional_tmn=250000,fee_rate=0)
    measured['provenance']=provenance
    return {'status':'VERIFIED_REAL_SNAPSHOT_AT_CUTOFF','features':compute_microstructure_features(measured),'provenance':provenance}
