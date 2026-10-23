"""Read-only causal/cost and matured-forecast diagnostics over genuine receipts.

Reuses ModelObservationLedger evaluation and existing Atlas metrics; no new
strategy, synthetic market data, fitting, model selection or external code.
"""
import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import sqlite3
import time
from .atlas_finance import current_session,read_json,recorded_summary
from .atlas_forward import _sha
from .atlas_prospective import ModelObservationLedger
from .atlas_liquidation import _save_atomic


def diagnose(root,session=None):
    root=Path(root).resolve();folder=Path(session).resolve() if session else current_session(root)
    if not folder.is_relative_to(root/'research_challengers'):raise ValueError('LOCAL_RESEARCH_SESSION_ONLY')
    contract=read_json(folder/'study_contract.json')
    if not contract or _sha({k:v for k,v in contract.items() if k!='contract_sha256'})!=contract['contract_sha256']:
        raise ValueError('INVALID_STUDY_CONTRACT')
    db=sqlite3.connect((folder/'forward_observations.sqlite').as_uri()+'?mode=ro',uri=True)
    ledger=ModelObservationLedger.__new__(ModelObservationLedger);ledger.db=db
    now=time.time();predictions={};recost=[];fee_mismatches=0
    try:
        db.execute('BEGIN')
        for key,model,raw,sha,origin_id,due in db.execute('SELECT prediction_id,model,payload,payload_sha,quote_id,due FROM m6_predictions'):
            p=json.loads(raw)
            if _sha(p)!=sha or p['prediction_id']!=key:raise ValueError('FORECAST_HASH_INVALID')
            if p['model_sha256']!=contract['models'][model]['model_sha256'] or p['prediction_available_at']+p['forecast_horizon']!=due:
                raise ValueError('FORECAST_IDENTITY_OR_HORIZON_INVALID')
            origin=ledger.quote(origin_id)
            if origin['receipt_sha256']!=p['origin_quote_sha256'] or origin['symbol']!=p['symbol'] or origin['observed_epoch']>p['prediction_available_at']:
                raise ValueError('FORECAST_ORIGIN_INVALID')
            mismatch=p['expected_cost']['fee_per_side_assumed']!=contract['settings']['fee_per_side_assumed']
            fee_mismatches+=int(mismatch)
            predictions[key]=(p,origin,due,model)
        for key,future_id,raw,sha in db.execute('SELECT prediction_id,future_quote_id,payload,payload_sha FROM m6_outcomes'):
            o=json.loads(raw);p,origin,due,model=predictions[key];future=ledger.quote(future_id)
            if _sha(o)!=sha or o['origin_sha256']!=origin['receipt_sha256'] or o['future_sha256']!=future['receipt_sha256']:
                raise ValueError('OUTCOME_HASH_OR_QUOTE_LINK_INVALID')
            if not due<=future['observed_epoch']<=min(now,due+p['quote_tolerance_seconds']) or future['symbol']!=p['symbol']:
                raise ValueError('OUTCOME_OUTSIDE_REAL_FUTURE_WINDOW')
            actual=math.log(future['mid']/origin['mid'])
            if abs(actual-o['MID_TO_MID_RETURN'])>1e-12:raise ValueError('OUTCOME_VALUE_NOT_FROM_QUOTE')
            fee=contract['settings']['fee_per_side_assumed']
            proxy=math.log(future['best_bid']/origin['best_ask'])+math.log1p(-fee)-math.log1p(fee)
            recost.append({'prediction_id':key,'symbol':p['symbol'],'model':model,
                'due':due,'observed_at':future['observed_epoch'],'mid_log_return':actual,
                'original_fee_net_proxy':o['ASK_TO_FUTURE_BID_NET_PROXY'],
                'study_fee_net_proxy':proxy,'study_fee_per_side':fee,'realized_pnl':None,
                'source':'ACTUAL_TOP_OF_BOOK_COUNTERFACTUAL_NOT_FILL_OR_DEPTH_EXECUTION'})
        evaluation=ledger.evaluation()
        statuses=dict(db.execute('SELECT status,count(*) FROM m6_predictions GROUP BY status'))
        quotes=db.execute('SELECT count(*),min(observed_epoch),max(observed_epoch) FROM quotes').fetchone()
        pending_due=db.execute('SELECT min(due) FROM m6_predictions WHERE due>?',(now,)).fetchone()[0]
    finally:db.close()
    decisions=[];all_veto=Counter()
    path=folder/'agentic_decisions.sqlite'
    if path.exists():
        db=sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)
        try:
            for raw,sha in db.execute('SELECT payload,sha256 FROM agentic_decisions_v8 ORDER BY created'):
                p=json.loads(raw)
                if _sha(p)!=sha:raise ValueError('DECISION_HASH_INVALID')
                evidence=p['evidence'];q=evidence.get('prediction',{}).get('quantile_log_returns',{})
                cost=evidence.get('book',{}).get('estimated_roundtrip_log_cost');q10=q.get('q10')
                covers=(q10>cost) if type(q10) in (int,float) and type(cost) in (int,float) else None
                veto=list(p['review']['veto_reasons'])
                if covers is False:veto.append('RAW_Q10_BELOW_OBSERVED_COST')
                all_veto.update(set(veto))
                decisions.append({'symbol':evidence['symbol'],'timestamp':evidence['decision_time'],
                    'raw_q10':q10,'observed_roundtrip_log_cost':cost,'raw_q10_cost_margin':q10-cost if covers is not None else None,
                    'q10_covers_cost':covers,'technical_signal':evidence.get('technical',{}).get('current_signal'),
                    'review_vetoes':p['review']['veto_reasons'],'primary_reason':p['receipt']['reason'],
                    'action':p['intent']['action'],'all_vetoes':sorted(set(veto))})
        finally:db.close()
    return {'schema':'ATLAS_FINANCIAL_DIAGNOSTICS_V1','observed_epoch':now,'session':folder.name,
        'decision_runtime_commit':contract['source_commit'],'contract_sha256':contract['contract_sha256'],
        'quote_count':quotes[0],'first_quote':quotes[1],'last_quote':quotes[2],
        'next_pending_due':pending_due,'forecast_count':len(predictions),'forecast_statuses':statuses,
        'matured_scored_count':len(recost),'forecasts_with_fee_metadata_mismatch':fee_mismatches,
        'original_forecasts_or_outcomes_modified':False,'fee_corrected_proxy':recost,
        'model_quality':evaluation,'decisions':decisions,'all_veto_counts':dict(all_veto),
        'financial':recorded_summary(folder),'financial_edge_proven':False,'LIVE':'HARD_DISABLED',
        'limitations':['Quote target differs from training candle target','Cross-asset and overlapping forecasts are not independent',
            'Costs are pinned observed ordinary-account rates, not certified contest fees',
            'Top-of-book counterfactual is not an exchange fill or realized PnL',
            'Short cohorts cannot establish calibration or economic superiority']}


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',default='atlas_store');p.add_argument('--session')
    p.add_argument('--output',default='reports/financial_followup_diagnostics.json');a=p.parse_args()
    result=diagnose(a.root,a.session);_save_atomic(Path(a.output),result)
    print(json.dumps({k:result[k] for k in ('session','quote_count','forecast_count','matured_scored_count',
        'next_pending_due','forecasts_with_fee_metadata_mismatch','all_veto_counts')}))


if __name__=='__main__':main()
