"""M8 reproducible reporting over actual archived/forward evidence only.

Existing M7 model metrics, actual depth replay, NewsStore/PIT and archive
contracts reused. Missing evidence never becomes a return, fill or neutral
sentiment. No live/private requests, model selection or promotion here.
"""
import argparse,hashlib,json,sqlite3,subprocess,time,os
from pathlib import Path
from collections import Counter
from datetime import datetime,timezone
import xml.etree.ElementTree as ET
from .atlas_study import DeadlineLedger,validate,source_manifest,runtime_packages
from .atlas_intelligence import DEFAULT_SESSION
from .atlas_intelligence_sync import IntelligenceSyncManager
from .atlas_m8_evaluation import evaluate,actual_decisions
from .atlas_archive import Lake
from .atlas_news_pipeline import NewsStore,MODEL_REVISION
from .atlas_news_features import registry as news_registry
from .atlas_news_challenger import evaluate as news_evaluate
from .atlas_technical_evidence import technical_evidence,technical_registry
from .atlas_portfolio_report import model_comparison,write_csv,real_quotes
from .atlas_liquidation import _save_atomic
from .atlas_forward import _sha
from .atlas_agentic_review import ABLATIONS
from .atlas_operational import _read_connection,_table

WORKSPACE=Path(__file__).resolve().parents[1]

def session_snapshot(directory):
    directory=Path(directory).resolve();db=_read_connection(directory/'forward_observations.sqlite')
    if db is None:return {'status':'NOT_STARTED_NO_OBSERVATIONS'}
    try:
        first,last,count=db.execute('SELECT min(observed_epoch),max(observed_epoch),count(*) FROM quotes').fetchone()
        events=[json.loads(raw) for raw, in db.execute("SELECT payload FROM study_events_v7 WHERE kind='INFERENCE_CYCLE'")]
        runtime=db.execute("SELECT payload FROM study_runtime_v7 WHERE key='session'").fetchone();runtime=json.loads(runtime[0]) if runtime else {}
        stops=db.execute("SELECT count(*) FROM study_events_v7 WHERE kind='FOREGROUND_PROCESS_STOPPED'").fetchone()[0]
        failures=[{'kind':kind,'payload':json.loads(raw)} for kind,raw in db.execute("SELECT kind,payload FROM study_events_v7 WHERE kind IN ('M8_RESEARCH_HOOK_FAILED_SAFE','QUOTE_WORKER_STOPPED_SAFE','QUOTE_NETWORK_OR_VALIDATION_ERROR')")]
        return {'directory':str(directory),'quote_count':count,'first_quote':first,'last_quote':last,'quote_span_hours':(last-first)/3600 if first is not None else 0,
            'forecast_statuses':dict(db.execute('SELECT status,count(*) FROM m6_predictions GROUP BY status')),
            'forecast_count':db.execute('SELECT count(*) FROM m6_predictions').fetchone()[0],
            'scored_outcomes':db.execute('SELECT count(*) FROM m6_outcomes').fetchone()[0],
            'runtime':runtime,'foreground_process_stop_events':stops,'failures':failures,
            'successful_sampler_gets':db.execute('SELECT count(*) FROM quote_io_v7').fetchone()[0],
            'actual_sampler_transport_latencies':[b-a for a,b in db.execute('SELECT request_started,response_received FROM quote_io_v7')],
            'inference_cycles':events,'lease_currently_held':bool(db.execute('SELECT 1 FROM m6_lease WHERE expires>?',(time.time(),)).fetchone())}
    finally:db.close()

def tests_report(path):
    node=ET.parse(path).getroot();suite=node if node.tag=='testsuite' else node.find('testsuite')
    counts={k:int(suite.attrib[k]) for k in ('tests','failures','errors','skipped')};counts['passed']=counts['tests']-sum(counts[k] for k in ('failures','errors','skipped'))
    counts.update(seconds=float(suite.attrib['time']),junit_sha256=hashlib.sha256(Path(path).read_bytes()).hexdigest(),
        command="PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 conda run --no-capture-output -n shbk python -m pytest -q --junitxml=reports/m8_pytest.xml",
        skips=[{'test':c.attrib['name'],'reason':c.find('skipped').attrib.get('message')} for c in node.iter('testcase') if c.find('skipped') is not None])
    return counts

def reference_matrix():
    initial=json.loads((WORKSPACE/'reports/m8_initial_audit.json').read_text())
    old=json.loads((WORKSPACE/'reports/m7_reference_integration.json').read_text())['external_repositories'];known={r['repository']:r for r in old}
    rows=[]
    for repo in sorted((WORKSPACE/'third_party').iterdir()):
        if not repo.is_dir() or not (repo/'.git').exists():continue
        entry=known.get(repo.name,{});files=[p for p in repo.iterdir() if p.is_file() and p.stem.upper() in ('LICENSE','LICENCE','COPYING')]
        adapted=repo.name in ('TradingAgents','FinMem','FinRL-Trading')
        rows.append({'repository':repo.name,'path':str(repo),'commit':subprocess.check_output(['git','-C',str(repo),'rev-parse','HEAD'],text=True).strip(),
            'license':entry.get('license',{'lumibot':'GPL-3.0','grid_trading_bot':'MIT','trading-bot':'UNSPECIFIED'}.get(repo.name,'UNVERIFIED')),
            'license_files':[{'path':str(p.relative_to(WORKSPACE)),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in files],
            'status':'BLOCKED_BY_LICENSE' if not files else 'ADAPTED_IMPLEMENTATION' if adapted else 'CONCEPTUAL_ONLY',
            'integration_scope':'Independent Atlas workflow adaptation, NOT execution of cloned framework' if adapted else 'Read-only concept review; no runtime import',
            'actual_atlas_adapter':{'TradingAgents':'atlas_agentic_review.board + LangGraph cross-review',
                'FinMem':'existing ResearchMemory retrieved and append-only M8 decision/NAV evidence',
                'FinRL-Trading':'existing capped allocator called before actual dynamic Shadow boundary'}.get(repo.name),
            'measured_effect':'Executed evidence/critique/memory/sizing chain; economic gain NOT demonstrated' if adapted else None,
            'copied_external_source_lines':0,'external_trading_repository_executed':False,
            'test_evidence':'tests/test_milestone8_agentic_real_only.py; tests/test_milestone8_dynamic_shadow_real_only.py' if adapted else None,
            'direct_use_rejected_reason':None if adapted else 'Existing Atlas contract retained; licensing/runtime replacement does not establish net OOS value'})
    rows.append({'repository':'SciPy','version':runtime_packages()['scipy'],'license':'BSD-3-Clause','status':'DIRECT_INTEGRATION',
        'actual_atlas_adapter':'atlas_patterns -> scipy.spatial.distance.cdist','measured_effect':'27041 real indexed windows, Euclidean/structure/DTW costs used in actual retrieval',
        'test_evidence':'tests/test_milestone8_patterns_real_only.py','copied_external_source_lines':0})
    rows.append({'repository':'librosa','version':'0.10.2.post1','license':'ISC','status':'REJECTED',
        'reason':'Local import/inspection probe did not finish within several minutes; interrupted. No successful DTW runtime integration claimed',
        'fallback':'small independently authored banded recurrence over SciPy costs'})
    return rows

def generate(root='atlas_store',directory=DEFAULT_SESSION,*,junit='reports/m8_pytest.xml',out='reports'):
    root=Path(root).resolve();directory=Path(directory).resolve();out=Path(out);out.mkdir(parents=True,exist_ok=True)
    contract=json.loads((directory/'study_contract.json').read_text());validate(root,contract)
    observer=DeadlineLedger(directory)
    try:
        observer.reconcile();forward=observer.status();deadlines=observer.deadline_report();models,stats=model_comparison(observer,forward['observed_span_hours'])
    finally:observer.close()
    session=session_snapshot(directory);dev=session_snapshot(root/'research_challengers/milestone8/development_smoke_v1')
    dev['track']='DEVELOPMENT_SMOKE_NOT_FORMAL_NOT_MERGED';dev['source_revised_after_smoke']=True
    decisions=actual_decisions(directory);replay_report=evaluate(directory);lake=Lake(root)
    try:
        sync=IntelligenceSyncManager(lake).intelligence_status(directory,index_dir=contract['settings']['intelligence']['pattern_index_dir'])
        technical=[technical_evidence(lake,s) for s in contract['settings']['symbols']]
        with NewsStore(root) as news:
            news_probe=news_evaluate(lake,news,tuple(contract['settings']['symbols']));news_summary=news.summary()
            processing=dict(news.db.execute('SELECT processing_status,count(*) FROM news_article_status GROUP BY processing_status'))
    finally:lake.close()
    initial=json.loads((WORKSPACE/'reports/m8_initial_audit.json').read_text())
    preserved={p:hashlib.sha256((WORKSPACE/p).read_bytes()).hexdigest()==h for p,h in initial['protected_file_hashes'].items()}
    preserved.update({r['path']:hashlib.sha256((WORKSPACE/r['path']).read_bytes()).hexdigest()==r['sha256'] for r in initial['checkpoints']})
    unchanged=not subprocess.check_output(['git','diff','8b3ae3b','--name-only','--',*[f'wallex_bot/{p}' for p in ('atlas_risk.py','atlas_broker.py','atlas_shadow.py','atlas_agent.py','atlas_deep.py','atlas_signals.py')]],text=True).strip()
    card=root/'news_models/models--ProsusAI--finbert/snapshots'/MODEL_REVISION/'README.md'
    reason_counts=Counter(code for p in decisions for code in p['intent'].get('reason_codes',[]));broker_gates=[p['receipt']['gate'] for p in decisions if p['receipt']['gate'] is not None]
    previews=Counter(g['reason'] for p in decisions for g in p['allocation'].get('risk_previews',{}).values())
    architecture={'logical_agent_roles':10,'existing_seven_roles_preserved':True,
        'physical_langgraph_nodes':['specialists_and_cross_review','portfolio_manager','unchanged_risk_and_shadow_boundary','explanation_and_pit_memory'],
        'actual_graph_decisions':len(decisions),'actual_cross_review_messages':sum(len(p['review']['cross_review_messages']) for p in decisions),
        'role_contract':['agent_name','decision_timestamp','symbol','evidence_ids','source_hashes','signal','confidence','uncertainty','limitations','recommendation','reasoning_summary'],
        'LLM_calls':0,'real_forecast_models':list(contract['models']),'AI_contribution':'Actual model quantiles constrain net-edge acceptance and sizing BEFORE explanation',
        'economic_ablation_status':'INSUFFICIENT_INDEPENDENT_ECONOMIC_ABLATION','LLM_order_authority':False,
        'pattern_or_news_auto_promotion':False,'checkpoint':'agentic_checkpoints.sqlite / SqliteSaver'}
    readiness={'status':'LIVE_NOT_AUTHORIZED_OR_NOT_READY','LIVE':'HARD_DISABLED','private_connection_status':'KEY_PRESENT_PRIVATE_CHECK_NOT_ATTEMPTED' if bool(os.environ.get('WALLEX_API_KEY')) else 'WALLEX_API_KEY_UNSET_NO_PRIVATE_REQUESTS',
        'verified_contest_balance':None,'hypothetical_shadow_initial_tmn':5_000_000,'ordinary_balance_is_contest_credit':False,
        'gates':{k:False for k in ('verified_contest_account','organizer_market_allowlist','verified_package_restrictions','verified_account_fee',
            'verified_tick_lot_spot_minimum','verified_real_broker_transport','validated_partial_cancel_recovery','sufficient_net_oos_evidence','independent_user_live_authorization')},
        'tested_controls':['hard-disabled live adapter','persisted ID/fingerprint','state-transition metadata invariants','kill switch/drawdown guard','source/model/dependency pinning'],
        'not_proven':['real partial fills/cancellation/network recovery','cross-account self-trade prevention at exchange','48h uptime','actual terminal liquidation'],
        'settlement_contracts':{'file_txt':'mentions net account value including open assets AND realized TMN requirement; clarify with organizer',
            'research_protocol':'attempt gated exit to TMN from last hour; never assume fill or delete residual holdings'}}
    requirements=[]
    for name,status,evidence,limitation in [
        ('archive_and_demand_sync','TESTED','atlas_data_sync.py','not full catalog backfill'),
        ('pattern_retrieval_7_10','TESTED','m8_pattern_retrieval_results.json','not proven predictive edge'),
        ('pattern_16_24','IMPLEMENTED','atlas_patterns.PatternIndex.build','not selected/evaluated as beneficial'),
        ('multi_timeframe_1_5_15_60_240','TESTED','m8_pattern_index_build.json','actual 4h analogues/validation insufficient; check counts'),
        ('euclidean_dtw_structure','TESTED','test_milestone8_patterns_real_only.py','DTW prefilter is approximate'),
        ('pattern_hash_embargo_prefix','TESTED','test_milestone8_patterns_real_only.py','de-overlap not proof of independent samples'),
        ('pattern_value_added','EVIDENCE_INSUFFICIENT','m8_pattern_retrieval_ablation.csv','not activated in primary decision path'),
        ('learned_encoder_faiss','NOT_IMPLEMENTED','atlas_patterns.py','optional; no independent evidence or performance need established'),
        ('agent_contract_cross_review','TESTED','m8_agent_architecture.json','structured deterministic specialists, not ten LLMs'),
        ('news_startup_lease_resume','TESTED','m8_startup_sync_audit.json','poll history cannot be reconstructed retrospectively'),
        ('news_forecast_four_arm_pipeline','IMPLEMENTED','atlas_news_challenger.py','zero shared historical PIT samples; no news model trained'),
        ('news_incremental_predictive_value','EVIDENCE_INSUFFICIENT','m8_news_model_integration.json','no imputed neutral values'),
        ('finbert_competition_license','BLOCKED','m8_news_model_integration.json','NC weights not operationalized for contest'),
        ('fibonacci_confirmed_swings','TESTED','test_milestone8_technical_real_only.py','descriptive levels, not return forecast'),
        ('ichimoku_and_supertrend','TESTED','m8_technical_indicator_audit.json','legacy approximations preserved and identified'),
        ('buy_and_exit_shadow_adapter','IMPLEMENTED','atlas_dynamic_shadow.py','no approved actual entry/held-position financial branch observed'),
        ('add_to_existing_position','BLOCKED','atlas_risk.py','unchanged RiskGate does not authorize ADD; no position omitted to bypass gate'),
        ('reduce_sell_rebalance_economics','EVIDENCE_INSUFFICIENT','m8_portfolio_decision_audit.json','requires real authorized positions/exit evidence; no fabricated scenario'),
        ('cash_exposure_turnover_cost','TESTED','test_milestone8_dynamic_shadow_real_only.py','positive-entry financial execution not validated'),
        ('quote_freshness_and_receipts','TESTED','test_milestone8_dynamic_shadow_real_only.py','no guaranteed exchange fills'),
        ('explainability_and_memory_pit','TESTED','m8_explainability_samples.json','unvalidated memory cannot grant permission'),
        ('backtest_saved_evidence_isolation','TESTED','m8_backtest_results.json','saved-evidence replay, not complete independent historical policy PnL'),
        ('full_independent_historical_economic_backtest','BLOCKED','m8_backtest_results.json','missing historical PIT news/books/authorized entries'),
        ('source_model_environment_pin','TESTED','m8_submission_manifest.json','new source requires new session'),
        ('formal_48_72h_study','EVIDENCE_INSUFFICIENT','m8_shadow_results.json','bounded foreground runs only; offline gaps retained'),
        ('net_economic_edge','EVIDENCE_INSUFFICIENT','m8_shadow_results.json','NO_VERIFIED_ECONOMIC_EDGE'),
        ('contest_account_allowlist_fees','BLOCKED','m8_live_readiness.json','not inferred from public spot catalog or 5M text'),
        ('live_transport_and_authorization','BLOCKED','m8_live_readiness.json','no actual order/cancel/withdrawal, no LIVE activation'),
        ('terminal_tmn_protocol','IMPLEMENTED','docs/PORTFOLIO_DECISION_POLICY_FA.md','no future clock advancement; no actual held exit demonstrated'),
        ('submission_readmes_demo_script','IMPLEMENTED','docs/HACKATHON_SUBMISSION_README_FA.md','video NOT recorded or publicly submitted here')]:
        requirements.append({'requirement':name,'status':status,'evidence':evidence,'limitation':limitation})
    rubric=[]
    for criterion,maximum,status in [('final_net_return',90,'EVIDENCE_INSUFFICIENT'),('drawdown_control',30,'EVIDENCE_INSUFFICIENT'),
        ('reasonable_algorithm_activity',15,'EVIDENCE_INSUFFICIENT'),('operational_stability',15,'TESTED'),('strategy_logic',40,'TESTED'),
        ('actual_AI_contribution',35,'TESTED'),('risk_and_capital',30,'TESTED'),('reproducibility',25,'TESTED'),('backtest_and_shadow',20,'TESTED')]:
        rubric.append({'criterion':criterion,'maximum_from_rules':maximum,'evidence_status':status,'awarded_or_estimated_score':None,
            'scope':'engineering evidence readiness only; economic ablation/48h/live outcomes insufficient'})
    submission={'source_commit':contract['source_commit'],'report_generation_commit':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),
        'session_id':contract['session_id'],'contract_sha256':contract['contract_sha256'],'source_manifest_LF_sha256':source_manifest(),
        'model_hashes_only_no_weights':contract['model_file_hashes'],'runtime_packages':runtime_packages(),
        'source_matches_frozen_contract':True,'protected_m7_and_champion_files_preserved':preserved,'core_champion_risk_broker_unchanged':unchanged,
        'credentials_or_private_model_weights_committed':False,'github_publish_performed':False,'actual_video_recorded':False}
    artifacts={
        'm8_requirements_coverage.json':{'requirements':requirements,'rules_file':'file.txt','rules_sha256':hashlib.sha256((WORKSPACE/'file.txt').read_bytes()).hexdigest(),
            'overall':'ENGINEERING_IMPLEMENTED_WITH_EXPLICIT_BLOCKED_OR_INSUFFICIENT_REQUIREMENTS; NOT_FULL_ECONOMIC_OR_LIVE_READINESS'},
        'm8_reference_integration_matrix.json':reference_matrix(),'m8_agent_architecture.json':architecture,
        'm8_news_model_integration.json':{'probe':news_probe,'news_store':news_summary,'processing_statuses':processing,'registry':news_registry(),
            'finbert':{'revision':MODEL_REVISION,'cached_card_sha256':hashlib.sha256(card.read_bytes()).hexdigest(),'cached_card_license':'CC-BY-NC-SA-4.0',
                'new_competition_facing_inference':False,'decision_use_authorized':False},
            'alternative_review':{'model':'mrm8488/distilroberta-finetuned-financial-news-sentiment-analysis','model_card_license':'Apache-2.0',
                'model_card_url':'https://huggingface.co/mrm8488/distilroberta-finetuned-financial-news-sentiment-analysis/blob/main/README.md',
                'training_dataset_card':'https://huggingface.co/datasets/takala/financial_phrasebank','dataset_license':'CC-BY-NC-SA-3.0',
                'status':'NOT_ASSUMED_CONTEST_CLEARED_RIGHTSHOLDER_REVIEW_REQUIRED','weights_downloaded_or_executed':False},
            'news_accuracy_or_profit_claimed':False,'neutral_imputation':False},
        'm8_technical_indicator_audit.json':{'registry':technical_registry(),'per_asset':technical,'champion_input_unchanged':True},
        'm8_startup_sync_audit.json':{'current':sync,'formal_inference_cycle_sync':[c.get('intelligence_sync') for c in session['inference_cycles']],
            'development_sync_separate':[c.get('intelligence_sync') for c in dev.get('inference_cycles',[])]},
        'm8_portfolio_decision_audit.json':{'decision_count':len(decisions),'actions':dict(Counter(p['intent']['action'] for p in decisions)),
            'reason_codes':dict(reason_counts),'actual_broker_gate_calls':len(broker_gates),'broker_gate_reasons':dict(Counter(g['reason'] for g in broker_gates)),
            'advisory_gate_preview_reasons_not_orders':dict(previews),'realized_exchange_pnl':None,
            'paper_mutations':sum(p['receipt']['status']=='PAPER_ESTIMATE_RECORDED' for p in decisions),
            'ADD':'BLOCKED_BY_UNCHANGED_RISKGATE','REBALANCE':'separate verified exit then fresh independently gated entry; no synthetic atomic fill',
            'financial_branches_without_actual_approved_evidence':'BUY/ADD/REDUCE/SELL not claimed financially validated by zero-trade smoke'},
        'm8_explainability_samples.json':{'source':'actual agentic_decisions.sqlite','samples':decisions[:4],'replay_checks':replay_report['replay_checks']},
        'm8_backtest_results.json':replay_report,
        'm8_shadow_results.json':{'formal':session,'development_separate':dev,'forward':forward,'deadline_coverage':deadlines,'model_statistics':stats,
            'paper_cash_and_nav':replay_report['nav_path'][-1] if replay_report['nav_path'] else None,
            'exchange_fills':None,'realized_exchange_pnl':None,'study_complete_claimed':False,'continuous_uptime_claimed':False,
            'economic_edge':'NO_VERIFIED_ECONOMIC_EDGE','status':'INSUFFICIENT_PROSPECTIVE_EVIDENCE'},
        'm8_hackathon_rubric.json':{'rules_file_sha256':hashlib.sha256((WORKSPACE/'file.txt').read_bytes()).hexdigest(),'criteria':rubric,
            'sum_maximum':sum(r['maximum_from_rules'] for r in rubric),'judge_assigns_actual_score':True,'estimated_score':None,
            'rule_ambiguities':['final NAV including remaining assets vs realized TMN requirement','example 6.25M minus 5M equals 1.25M, not the example stated 1.5M']},
        'm8_live_readiness.json':readiness,'m8_test_results.json':tests_report(junit),'m8_submission_manifest.json':submission,
        'm8_development_incidents.json':{'observed_not_hidden':[
            'initial pattern build rejected unsupported local 5m verifier grid; fixed without changing API resolutions',
            'next pattern build rejected actual conflicting PEPETMN/1 candles; now excluded independently, no winner/overwrite',
            'librosa import probe interrupted after minutes; explicit independent bounded recurrence fallback',
            'first new agent test fixture lacked quote hash in older M6 schema: 13 setup errors; corrected to actual M7 receipt-bearing evidence',
            'development smoke used c80d5b0 and is NOT merged into later frozen formal study',
            'no positive-entry real evidence or existing held positions; no fabricated financial branch tests'],
            'current_financial_or_model_success_inferred_from_these':False}
    }
    for name,value in artifacts.items():_save_atomic(out/name,value)
    write_csv(out/'m8_model_agent_ablation.csv',replay_report['component_ablation'])
    write_csv(out/'m8_model_comparison.csv',models)
    return {'formal_quotes':forward['quote_count'],'forecasts':sum(forward['by_model'].values()),'scored':forward['matured_scored'],
        'decisions':len(decisions),'paper_mutations':artifacts['m8_portfolio_decision_audit.json']['paper_mutations'],
        'tests':artifacts['m8_test_results.json'],'source_preserved':all(preserved.values()) and unchanged,'status':'INSUFFICIENT_PROSPECTIVE_EVIDENCE'}

def main():
    p=argparse.ArgumentParser();p.add_argument('--root',default='atlas_store');p.add_argument('--session-dir',default=DEFAULT_SESSION);p.add_argument('--junit',default='reports/m8_pytest.xml');p.add_argument('--output-dir',default='reports');a=p.parse_args()
    print(json.dumps(generate(a.root,a.session_dir,junit=a.junit,out=a.output_dir),ensure_ascii=False))

if __name__=='__main__':main()
