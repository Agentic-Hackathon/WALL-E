"""M7 versioned RESEARCH allocation, no broker or account mutation.

Reuse Atlas RiskGate and live_scout depth sweeps. FinRL-X risk/portfolio
separation is conceptual only (Apache-2.0, SOURCES.md); no external code copied.
Complex covariance allocators remain disabled without independent validation.
"""
from dataclasses import dataclass,asdict
import math,time
import numpy as np
from .atlas_forward import _sha
from .atlas_risk import RiskGate
from .live_scout import measure_book,_levels,_buy_with_notional,_sell_qty

VERSION='ATLAS_RESEARCH_ALLOCATION_V1'
METHODS=('cash','equal_weight','inverse_volatility','confidence_aware','volatility_targeting','risk_parity','minimum_variance')

@dataclass(frozen=True)
class AllocationLimits:
    max_asset_weight:float=.10
    min_cash_weight:float=.80
    max_turnover_fraction:float=.10
    max_rebalance_cost_fraction:float=.001
    max_correlated_weight:float=.10
    correlation_threshold:float=.80
    quote_max_age_seconds:int=30

def projected_weights(scores,budget,cap):
    """Pure bounded simplex projection; scores are abstract ranking metadata."""
    if not 0<=budget<=1 or not 0<=cap<=1 or any(not math.isfinite(v) or v<0 for v in scores.values()):raise ValueError('INVALID_WEIGHT_CONTRACT')
    total=sum(scores.values())
    return {key:min(cap,budget*value/total) if total else 0. for key,value in scores.items()}

def cost_audit(quote,notional_tmn,fee=.001,metadata=None):
    payload={k:quote[k] for k in ('symbol','observed_epoch','best_bid','best_ask','mid','raw_book')}
    if _sha(payload)!=quote['receipt_sha256']:raise ValueError('QUOTE_RECEIPT_HASH_INVALID')
    if not 0<=fee<.05:raise ValueError('INVALID_ASSUMED_FEE')
    result=measure_book(quote['raw_book'],notional_tmn,fee)
    if result['best_bid_tmn']!=quote['best_bid'] or result['best_ask_tmn']!=quote['best_ask']:raise ValueError('BOOK_RECEIPT_PRICE_MISMATCH')
    metadata=metadata or {}
    result.update(symbol=quote['symbol'],quote_sha256=quote['receipt_sha256'],observed_at=quote['observed_epoch'],
        fee_verified=False,fee_status='EXPLICIT_RESEARCH_ASSUMPTION_NOT_ACCOUNT_FEE',
        price_precision_observed=metadata.get('price_precision'),amount_precision_observed=metadata.get('amount_precision'),
        exchange_tick_size=None,exchange_quantity_step=None,exchange_min_notional=None,
        precision_status='PUBLIC_DECIMAL_PRECISION_IS_NOT_VERIFIED_TICK_OR_LOT_RULE',
        paper_min_notional_tmn=RiskGate().limits.min_order_notional_tmn,exchange_fill=None,
        partial_fill_policy='NO_PARTIAL_FILL_GENERATION; insufficient displayed sweep rejects estimate')
    avg=result['hypothetical_buy_avg_price']
    result['buy_impact_fraction']=avg/result['best_ask_tmn']-1 if avg is not None else None
    result['estimated_roundtrip_log_cost']=-math.log1p(result['hypothetical_instant_roundtrip_net_pct']/100) if result['hypothetical_instant_roundtrip_net_pct'] is not None else None
    result['research_only']=True
    return result

def allocate(method,account,candidates,*,now=None,correlations=None,limits=None):
    """Return weights and delta ONLY. All book/forecast inputs must be actual.

    Cash is the residual budget, never inferred asset liquidity. Existing
    holdings require actual bids in candidates. Missing mandatory evidence
    rejects an allocation, including tempting but unverified forecasts.
    """
    if method not in METHODS:raise ValueError('UNKNOWN_ALLOCATION_METHOD')
    now=time.time() if now is None else float(now);limits=limits or AllocationLimits();gate=RiskGate()
    cash=float(account['cash_tmn']);positions=[tuple(p) for p in account['positions']]
    if not math.isfinite(cash) or cash<0:raise ValueError('INVALID_CASH')
    result={'version':VERSION,'method':method,'decision_time':now,'authority':'RESEARCH_PROPOSAL_ONLY_NO_BROKER',
        'target_weights':{},'cash_weight':1.,'delta_weights':{},'estimated_rebalance_cost_tmn':0.,
        'rejections':{},'risk_previews':{},'status':'CASH_ONLY','execution_eligible':False,
        'exchange_execution_missing':['verified account fee','verified exchange tick/lot/minimum rules'],
        'risk_limits':asdict(gate.limits),'allocation_limits':asdict(limits)}
    nav=cash;current={};missing=[]
    for symbol,qty,cost in positions:
        candidate=candidates.get(symbol);q=candidate.get('quote') if candidate else None
        if q is None or not 0<=now-q['observed_epoch']<=limits.quote_max_age_seconds:missing.append(symbol);continue
        # Verify source before valuing held assets; no fallback to entry/close.
        cost_audit(q,max(gate.limits.min_order_notional_tmn,cost));current[symbol]=qty*q['best_bid']*(1-candidate.get('fee',.001));nav+=current[symbol]
    if missing:
        result.update(status='REJECTED_UNVALUED_POSITIONS',cash_weight=None,nav_tmn=None,rejections={s:['NO_FRESH_REAL_BID_FOR_NAV'] for s in missing});return result
    if not nav>0:raise ValueError('NONPOSITIVE_NAV')
    current={s:v/nav for s,v in current.items()};result['nav_tmn']=nav
    result['nav_policy']='cash + actual held bid liquidation less explicit assumed exit fee'
    if 'high_water_tmn' not in account:
        result.update(status='REJECTED_MISSING_EQUITY_STATE',cash_weight=None);return result
    assessment=gate.assess_equity(nav,account['high_water_tmn'],account['stopped'])
    result['equity_assessment']=asdict(assessment)
    scores={};audits={};eligible={}
    for symbol,c in sorted(candidates.items()):
        reasons=[];q=c.get('quote');forecast=c.get('forecast',{});quant=forecast.get('quantile_log_returns',{})
        try:
            if not symbol.endswith('TMN') or c.get('spot_tmn') is not True:raise ValueError('UNVERIFIED_SPOT_TMN')
            if q is None or q['symbol']!=symbol or not 0<=now-q['observed_epoch']<=limits.quote_max_age_seconds:raise ValueError('STALE_OR_MISSING_QUOTE')
            if not c.get('prediction_available_at') or c['prediction_available_at']>now:raise ValueError('FORECAST_NOT_YET_AVAILABLE')
            if now-c['prediction_available_at']>2700:raise ValueError('STALE_FORECAST')
            if not all(type(quant.get(k)) in (float,int) and math.isfinite(quant[k]) for k in ('q10','q50','q90')) or not quant['q10']<=quant['q50']<=quant['q90']:raise ValueError('INVALID_QUANTILES')
            audit=cost_audit(q,min(nav*limits.max_asset_weight,gate.limits.max_order_notional_tmn),c.get('fee',.001),c.get('metadata'))
            audits[symbol]=audit
            preview=gate.evaluate(symbol,forecast,audit,cash,positions,assessment.stopped,c.get('fee',.001));result['risk_previews'][symbol]=preview.audit_payload()
            if preview.action not in ('PAPER_BUY','HOLD_POSITION'):reasons.append(preview.reason)
            if not audit['hypothetical_full_roundtrip_depth_available']:reasons.append('INSUFFICIENT_DISPLAYED_ROUNDTRIP_DEPTH')
            if audit['estimated_roundtrip_log_cost'] is None or quant['q10']<=audit['estimated_roundtrip_log_cost']+gate.limits.edge_safety_log_return:reasons.append('Q10_BELOW_FULL_SWEEP_COST_AND_SAFETY')
            if preview.action=='HOLD_POSITION':reasons.append('EXISTING_POSITION_REBALANCE_NOT_AUTHORIZED')
            if not reasons:eligible[symbol]=c
        except (ValueError,TypeError,KeyError,OverflowError) as exc:reasons.append(str(exc)[:120])
        if reasons:result['rejections'][symbol]=reasons
    if method in ('risk_parity','minimum_variance','volatility_targeting'):
        result['method_status']='INSUFFICIENT_INDEPENDENT_ALLOCATION_VALIDATION';eligible={}
    elif method=='cash':eligible={};result['method_status']='PREDECLARED_CASH_BASELINE'
    else:result['method_status']='RESEARCH_ONLY_NOT_VALIDATED_STRATEGY'
    for symbol,c in eligible.items():
        quant=c['forecast']['quantile_log_returns']
        if method=='inverse_volatility':
            vol=c.get('volatility');n=c.get('volatility_observations',0)
            if n<96 or not isinstance(vol,(float,int)) or not math.isfinite(vol) or vol<=0:
                result['rejections'][symbol]=['INSUFFICIENT_REAL_TRAILING_VOLATILITY'];continue
            scores[symbol]=1/vol
        elif method=='confidence_aware':scores[symbol]=max(0,quant['q10']-audits[symbol]['estimated_roundtrip_log_cost'])/max(quant['q90']-quant['q10'],1e-8)
        else:scores[symbol]=1.
    # Unknown correlation is NOT zero correlation: prohibit a multi-asset
    # recommendation until aligned history is available and controls pass.
    if len(scores)>1:
        for symbol in list(scores):
            peers=[p for p in scores if p!=symbol]
            if correlations is None or any((symbol,p) not in correlations or not math.isfinite(correlations[(symbol,p)]) or abs(correlations[(symbol,p)])>1 for p in peers):
                result['rejections'][symbol]=['MISSING_ALIGNED_CORRELATION_CONTROL'];scores={};break
        if scores and any(abs(correlations[(a,b)])>=limits.correlation_threshold for a in scores for b in scores if a!=b):
            best=max(scores,key=scores.get)
            for symbol in list(scores):
                if symbol!=best:result['rejections'][symbol]=['CORRELATED_CLUSTER_CAP'];scores.pop(symbol)
    budget=min(1-limits.min_cash_weight,gate.limits.max_open_notional_tmn/nav,limits.max_turnover_fraction)
    weights=projected_weights(scores,max(0,budget),min(limits.max_asset_weight,gate.limits.max_cash_fraction_per_entry,gate.limits.max_order_notional_tmn/nav))
    # Respect unchanged minimum order rather than rounding up a proposal.
    weights={s:w for s,w in weights.items() if w*nav>=gate.limits.min_order_notional_tmn}
    cost=sum(nav*w*(candidates[s].get('fee',.001)+max(0,audits[s]['buy_impact_fraction'] or 0)+audits[s]['spread_bps']/20000) for s,w in weights.items())
    for symbol,weight in current.items():
        decrease=max(0,weight-weights.get(symbol,0))
        if not decrease:continue
        q=candidates[symbol]['quote'];quantity=decrease*nav/(q['best_bid']*(1-candidates[symbol].get('fee',.001)))
        sweep=_sell_qty(_levels(q['raw_book'],'bid'),quantity)
        if sweep is None:
            result.update(status='REJECTED_EXIT_LIQUIDITY',cash_weight=None,rejections={symbol:['INSUFFICIENT_REAL_EXIT_DEPTH']});return result
        cost+=decrease*nav*(candidates[symbol].get('fee',.001)+max(0,1-sweep[1]/q['best_bid'])+(q['best_ask']-q['best_bid'])/(2*q['mid']))
    if cost>nav*limits.max_rebalance_cost_fraction:
        if positions:
            result.update(status='REJECTED_REBALANCE_COST',cash_weight=None,estimated_rebalance_cost_tmn=cost,
                rejections={'PORTFOLIO':['REBALANCE_COST_CAP']});return result
        result['rejections']['PORTFOLIO']=['REBALANCE_COST_CAP'];weights={};cost=0.
    # When holdings exist, a cash target is only a proposed exit, never a
    # fabricated sale. Existing RiskGate/liquidation must separately approve.
    turnover=sum(abs(weights.get(s,0)-current.get(s,0)) for s in set(weights)|set(current))
    if turnover>limits.max_turnover_fraction+1e-12:
        result.update(status='REJECTED_TURNOVER_LIMIT',cash_weight=None);return result
    result.update(target_weights=weights,cash_weight=1-sum(weights.values()),
        delta_weights={s:weights.get(s,0)-current.get(s,0) for s in set(weights)|set(current)},
        estimated_rebalance_cost_tmn=cost,turnover_fraction=turnover,status='PROPOSED' if weights else 'CASH_ONLY',
        liquidation_required=bool(positions and not weights),cash_target_is_not_realized_cash=True)
    result['source_sha256']=_sha({'account':account,'receipts':{s:c.get('quote',{}).get('receipt_sha256') for s,c in candidates.items()},'result':result})
    return result
