"""M6 pure structured review, concept: TradingAgents (Apache-2.0).

No third-party code copied. Seven deterministic evidence roles, not seven LLM
calls. No tools, HTTP, broker, state mutation or consensus requirement here.
"""
import copy,math
from .atlas_forward import _sha
PROTOCOL='ATLAS_SHARED_AGENT_WATCH_REVIEW_V1'
ROLES=('Technical Analyst','News Analyst','Forecast Analyst','Market Regime Analyst',
       'Portfolio Analyst','Risk Reviewer','Decision Explanation Agent')

def review(evidence):
    symbol=evidence['symbol'];stamp=evidence['decision_time'];source=evidence['observation_id']
    roles=[];veto=[]
    def add(role,ready,facts,reason):
        roles.append({'role':role,'status':'OBSERVED_EVIDENCE' if ready else 'INSUFFICIENT_EVIDENCE',
            'symbol':symbol,'observation_id':source,'decision_time':stamp,'available_at':evidence.get('available_at',stamp),
            'source_hash':_sha(facts),'facts':facts,'reason':reason,'authority':'ADVISORY_STRUCTURED_NO_TOOLS'})
    technical=evidence.get('technical',{});flag=technical.get('current_signal')
    add(ROLES[0],flag is not None,technical,'existing chronological strategy only')
    if flag is False:veto.append('technical_strategy_veto')
    if flag is None:veto.append('technical_strategy_unverified')
    news=evidence.get('news',{});newsevidence=news.get('advisory_evidence',[])
    add(ROLES[1],bool(newsevidence),{'article_ids':[r.get('article_id') for r in newsevidence],
        'strong_negative_urls':news.get('strong_negative_urls',[]),'policy':'No raw headline can grant authority'},'PIT evidence; optional missing news is not a core veto')
    if news.get('strong_negative_urls'):veto.append('observed_finbert_high_negative_news')
    prediction=evidence.get('prediction',{});q=prediction.get('quantile_log_returns',{})
    finite=all(isinstance(q.get(k),(float,int)) and math.isfinite(q[k]) for k in ('q10','q50','q90'))
    valid=finite and q['q10']<=q['q50']<=q['q90']
    add(ROLES[2],valid,prediction,'Champion only; research models never enter proposal')
    if not valid:veto.append('champion_forecast_invalid')
    regime=evidence.get('regime',{})
    add(ROLES[3],bool(regime),regime,'descriptive actual trailing features, not an inferred future regime')
    portfolio=evidence.get('portfolio',{})
    add(ROLES[4],bool(portfolio),portfolio,'all held symbols require fresh actual bids before action')
    if not evidence.get('readiness',{}).get('ready'):veto.append('asset_data_not_ready')
    book=evidence.get('book',{})
    if book.get('spread_bps',float('inf'))>70:veto.append('wide_spread')
    if not book.get('hypothetical_full_roundtrip_depth_available'):veto.append('insufficient_visible_book_depth')
    add(ROLES[5],bool(portfolio),{'preflight_veto':veto.copy(),'RiskGate':'mandatory again inside existing ShadowBroker transaction'},'Review cannot authorize an order')
    proposal={'protocol':PROTOCOL,'symbol':symbol,'decision_time':stamp,'observation_id':source,
        'source_evidence_hash':_sha(evidence),'proposed_action':'ABSTAIN' if veto else 'EVALUATE_WITH_RISKGATE',
        'veto_reasons':veto,'requires_deterministic_risk_gate':True,'model_promotion':False}
    add(ROLES[6],True,{'proposal':proposal['proposed_action'],'veto_reasons':veto},'deterministic explanation; optional LLM cannot change fields')
    return {'proposal':proposal,'agents':roles,'disagreements':{'technical_signal':flag,'forecast_q50_positive':q.get('q50',0)>0 if valid else None},
        'review_sha256':_sha({'evidence':evidence,'proposal':proposal,'agents':roles})}

def broker_evidence(prediction,result):
    # Only a deterministic stricter veto is allowed. Never promote/override
    # a forecast, side, size, fee, kill switch or RiskGate limits.
    output=copy.deepcopy(prediction)
    if result['proposal']['veto_reasons']:
        output.setdefault('quantile_log_returns',{})['q10']=None
    return output
