"""M8 evidence board: real model contribution, bounded cross-review, no tools.

Adapted TradingAgents critique workflow idea on Atlas's existing seven-role
review (Apache-2.0 reference e8f5503, SOURCES.md). FinMem-inspired retrieval
reuses Atlas's timestamped product ranking, never auto-tunes trading policy.
No third-party source copied and no LLM text authorizes an order.
"""
import copy,math
from .atlas_forward import _sha
from .atlas_review import review,ROLES

VERSION='ATLAS_AGENTIC_EVIDENCE_BOARD_V1'
ABLATIONS=('rule_only','forecast_only','forecast_technical','forecast_news','forecast_patterns','forecast_memory','full')


def board(evidence,*,arm='full'):
    if arm not in ABLATIONS:raise ValueError('UNKNOWN_PREDECLARED_ABLATION')
    stamp=evidence['decision_time'];symbol=evidence['symbol'];base=review(evidence)
    agents=[];messages=[];votes=[]
    def agent(name,facts,signal,recommendation,limitations,status='OBSERVED_EVIDENCE'):
        ids=facts.get('evidence_ids',[]) if isinstance(facts,dict) else []
        item={'agent_name':name,'decision_timestamp':stamp,'symbol':symbol,'evidence_ids':ids,
            'source_hashes':[_sha(facts)],'signal':signal,'confidence':None,'uncertainty':'UNVALIDATED_CONTRIBUTION_NOT_EMPIRICAL_PROBABILITY',
            'limitations':limitations,'recommendation':recommendation,'reasoning_summary':facts,
            'status':status,'authority':'STRUCTURED_EVIDENCE_NO_BROKER_OR_LLM_AUTHORITY'}
        agents.append(item);return item
    for old in base['agents']:
        agent(old['role'],old['facts'],old['status'],base['proposal']['proposed_action'],[old['reason']],old['status'])
    pattern=evidence.get('pattern',{});memory=evidence.get('research_memory',[]);tech=evidence.get('technical_extended',{})
    for event in memory:
        if any(event.get(k,float('inf'))>stamp for k in ('observation_time','availability_time','created_at')):raise ValueError('MEMORY_NOT_AVAILABLE_AT_DECISION')
    if any(p.get('available_at',float('inf'))>stamp or p.get('outcome_end',float('inf'))>stamp for p in pattern.get('matches',[])):raise ValueError('PATTERN_OUTCOME_NOT_AVAILABLE_AT_DECISION')
    pattern_ids=[p['pattern_id'] for p in pattern.get('matches',[])]
    agent('Historical Pattern Retrieval Agent',{'evidence_ids':pattern_ids,'index_sha256':pattern.get('index_sha256'),
        'status':pattern.get('status'),'effective_count':pattern.get('effective_independent_match_count'),
        'empirical_quantiles':pattern.get('empirical_quantiles')},pattern.get('status','INSUFFICIENT_HISTORICAL_ANALOGUES'),
        'RESEARCH_ONLY_NOT_ACTIONABLE',['No independent economic validation; cannot replace Champion or grant entry'])
    agent('Research Memory Agent',{'evidence_ids':[r.get('event_id') for r in memory],
        'source_hashes':[r.get('source_hash') for r in memory],'evaluation_statuses':[r.get('evaluation_status') for r in memory]},
        'OBSERVED_PIT_MEMORY' if memory else 'NO_PIT_MEMORY','RESEARCH_ONLY',
        ['Creation, observation and availability must all precede cutoff; no hypothetical profit becomes real profit'])
    agent('Market Data Agent',{'evidence_ids':[evidence['observation_id']],
        'readiness':evidence.get('readiness'),'quote_sha256':evidence.get('quote_receipt_sha256')},
        'READY' if evidence.get('readiness',{}).get('ready') else 'NOT_READY','REQUIRE_VERIFIED_FRESH_DATA',
        ['Missing core evidence always rejects; no sibling market can grant readiness'])
    q=evidence.get('prediction',{}).get('quantile_log_returns',{})
    finite=all(type(q.get(k)) in (float,int) and math.isfinite(q[k]) for k in ('q10','q50','q90'))
    if finite and not q['q10']<=q['q50']<=q['q90']:finite=False
    forecast_used=arm!='rule_only'
    technical_used=arm in ('rule_only','forecast_technical','full')
    veto=[]
    if not evidence.get('readiness',{}).get('ready'):veto.append('asset_data_not_ready')
    portfolio=evidence.get('portfolio',{})
    if not portfolio.get('all_held_assets_valued',portfolio.get('all_held_assets_marked_from_real_bids',False)):veto.append('portfolio_nav_unverified')
    if forecast_used and not finite:veto.append('required_forecast_invalid')
    flag=evidence.get('technical',{}).get('current_signal')
    if technical_used and flag is not True:veto.append('technical_not_confirmed')
    # Only actual stamped/validated news could veto. NC-licensed FinBERT is
    # explicitly not authorized for competition-derived decisions here.
    news=evidence.get('news',{});news_used=arm in ('forecast_news','full')
    news_eligible=bool(news.get('decision_use_licensed')) and bool(news.get('value_added_validated'))
    if news_used and news_eligible and news.get('strong_negative_evidence'):veto.append('validated_negative_news')
    for role,enabled,validated in [('News Analyst',news_used,news_eligible),
        ('Historical Pattern Retrieval Agent',arm in ('forecast_patterns','full'),bool(pattern.get('decision_path_eligible'))),
        ('Research Memory Agent',arm in ('forecast_memory','full'),False)]:
        messages.append({'from':role,'to':'Portfolio Analyst','type':'EVIDENCE_QUALIFICATION',
            'enabled_in_arm':enabled,'decision_qualified':validated,'reason':'No value-added validation means no fabricated numerical vote'})
    if flag is not None and finite and flag!=(q['q50']>0):
        messages.append({'from':'Technical Analyst','to':'Forecast Analyst','type':'DISAGREEMENT',
            'evidence_ids':[evidence['observation_id']],'technical_signal':flag,'forecast_q50':q['q50']})
    book=evidence.get('book',{});cost=book.get('estimated_roundtrip_log_cost')
    if forecast_used and finite and cost is not None and q['q10']<=cost:
        messages.append({'from':'Forecast Analyst','to':'Risk Reviewer','type':'AI_EDGE_BELOW_OBSERVED_COST',
            'forecast_q10':q['q10'],'observed_assumed_cost':cost,'contribution':'MODEL_OUTPUT_REJECTS_ENTRY_BEFORE_EXPLANATION'})
    if not forecast_used:proposal='REJECT_NO_AI_FORECAST_AUTHORITY'
    elif veto:proposal='ABSTAIN'
    else:proposal='EVALUATE_WITH_UNCHANGED_RISKGATE'
    result={'version':VERSION,'symbol':symbol,'decision_timestamp':stamp,'arm':arm,'agents':agents,'cross_review_messages':messages,
        'disagreements':[m for m in messages if m['type']=='DISAGREEMENT'],'veto_reasons':veto,'recommendation':proposal,
        'forecast_for_gate':copy.deepcopy(evidence.get('prediction',{})),'technical_extended_sha256':tech.get('evidence_sha256'),
        'source_evidence_hash':_sha(evidence),'base_seven_role_review':base,'live_authority':False,'automatic_promotion':False,
        'ablation_status':'PREDECLARED_ARMS_REQUIRE_COMMON_CHRONOLOGICAL_ECONOMIC_EVIDENCE'}
    if veto or not forecast_used:result['forecast_for_gate'].setdefault('quantile_log_returns',{})['q10']=None
    result['review_sha256']=_sha(result);return result
