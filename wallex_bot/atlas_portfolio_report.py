"""M7 auditable reports; reuse Atlas receipts, depth sweeps and M6 metrics.

Original replay glue, not external execution code. Reference licenses and
concept-only provenance: third_party/SOURCES.md. No interpolated prices/fills.
"""
import argparse,csv,hashlib,json,sqlite3,time,subprocess
from pathlib import Path
from collections import Counter
from types import SimpleNamespace
import numpy as np
from .atlas_forward import _sha
from .atlas_study import DeadlineLedger,source_manifest,DEFAULT_SESSION,validate
from .atlas_portfolio import METHODS,cost_audit
from .atlas_prospective import MODEL_NAMES
from .live_scout import _levels,_buy_with_notional,_sell_qty
from .atlas_liquidation import _save_atomic


def real_quotes(directory):
    """Read-only, verify original receipt hashes. Never creates old schemas."""
    path=Path(directory)/'forward_observations.sqlite'
    if not path.exists():return []
    db=sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)
    try:
        rows=[]
        for symbol,observed,bid,ask,mid,raw,sha in db.execute('SELECT symbol,observed_epoch,best_bid,best_ask,mid,raw_book,receipt_sha256 FROM quotes ORDER BY observed_epoch,id'):
            p={'symbol':symbol,'observed_epoch':observed,'best_bid':bid,'best_ask':ask,'mid':mid,'raw_book':json.loads(raw)}
            if _sha(p)!=sha:raise ValueError('QUOTE_HASH_INVALID')
            rows.append({**p,'receipt_sha256':sha})
        return rows
    finally:db.close()


def common_cohorts(quotes,symbols,tolerance=30):
    """Require an actual receipt of each symbol within 30s; no forward fill."""
    pending={};cohorts=[]
    for q in quotes:
        if q['symbol'] not in symbols:continue
        pending[q['symbol']]=q
        if set(pending)==set(symbols):
            stamps=[x['observed_epoch'] for x in pending.values()]
            if max(stamps)-min(stamps)<=tolerance:
                cohorts.append(dict(pending));pending={}
    return cohorts


def depth_replay(cohorts,weights,initial=5_000_000,fee=.001):
    """Counterfactual estimates only; no Fill, Broker, account or memory write.

    Entry notional includes fee; whole displayed ask sweep required. Each NAV
    uses a complete actual bid sweep at a shared cohort. Failed depth is a gap,
    not a substituted price. No quote from a later cohort affects entry.
    """
    result={'status':'INSUFFICIENT_COMMON_REAL_QUOTES','track':'COUNTERFACTUAL_DEPTH_SWEEP_NOT_REALIZED_PNL',
        'weights':weights,'fee_per_side_assumed':fee,'fee_verified':False,'exchange_fills':None,
        'initial_tmn':initial,'nav_path':[],'max_drawdown':None,'win_loss':None,'profit_factor':None,'sharpe':None}
    if any(not np.isfinite(w) or w<0 for w in weights.values()) or sum(weights.values())>1:raise ValueError('INVALID_BENCHMARK_BUDGET')
    if len(cohorts)<2:return result
    holdings={};cash=initial;entry_fees=0.;entry_gross=0.;sources=[]
    for symbol,w in weights.items():
        quote=cohorts[0][symbol];cost_audit(quote,max(1,initial*w),fee)
        gross=initial*w/(1+fee);sweep=_buy_with_notional(_levels(quote['raw_book'],'ask'),gross)
        if sweep is None:return {**result,'status':'INSUFFICIENT_REAL_ENTRY_DEPTH'}
        holdings[symbol]=sweep[0];cash-=initial*w;entry_gross+=gross;entry_fees+=gross*fee;sources.append(quote['receipt_sha256'])
    gaps=[]
    for cohort in cohorts:
        value=0.;exit_fees=0.;hashes=[];valid=True
        for symbol,qty in holdings.items():
            q=cohort[symbol];sweep=_sell_qty(_levels(q['raw_book'],'bid'),qty)
            if sweep is None:valid=False;break
            value+=sweep[0];exit_fees+=sweep[0]*fee;hashes.append(q['receipt_sha256'])
        if not valid:gaps.append(max(q['observed_epoch'] for q in cohort.values()));continue
        gross_pnl=value-entry_gross;net_pnl=gross_pnl-entry_fees-exit_fees
        result['nav_path'].append({'observed_epoch':max(q['observed_epoch'] for q in cohort.values()),'cash_tmn':cash,
            'liquidation_nav_tmn':cash+value-exit_fees,'cash_weight':cash/(cash+value-exit_fees),
            'gross_counterfactual_pnl_tmn':gross_pnl,'net_counterfactual_pnl_tmn':net_pnl,
            'assumed_entry_exit_fees_tmn':entry_fees+exit_fees,'exposure_tmn':value,'quote_sha256':hashes})
    valid_end=bool(result['nav_path']) and result['nav_path'][-1]['observed_epoch']==max(q['observed_epoch'] for q in cohorts[-1].values())
    result.update(status='SHORT_WINDOW_DESCRIPTIVE_ONLY' if valid_end else 'INCOMPLETE_REAL_EXIT_DEPTH',
        entry_receipts=sources,entry_turnover_fraction=sum(weights.values()),entry_gross_tmn=entry_gross,
        entry_fees_tmn=entry_fees,depth_gaps=gaps,partial_fill_generation=False,
        close_price_fill_used=False,execution_eligible=False,market_impact='explicit sweep; spread embedded, no extra spread double count',
        terminal_estimate=result['nav_path'][-1] if valid_end else None)
    if len(result['nav_path'])>=192 and not gaps and result['nav_path'][-1]['observed_epoch']-result['nav_path'][0]['observed_epoch']>=48*3600:
        nav=np.array([p['liquidation_nav_tmn'] for p in result['nav_path']]);result['max_drawdown']=float(np.max(1-nav/np.maximum.accumulate(nav)))
    return result


def legacy_audit(directory):
    quotes=real_quotes(directory);db=sqlite3.connect((Path(directory)/'forward_observations.sqlite').as_uri()+'?mode=ro',uri=True)
    try:
        rows=[];now=time.time()
        for key,due,state in db.execute('SELECT prediction_id,due,status FROM m6_predictions'):
            rows.append({'prediction_id':key,'due':due,'stored_status':state,'effective_status':state if state!='PENDING' or now<=due+300 else 'UNSCORED_NO_REAL_FUTURE_QUOTE'})
        return {'track':'M6_DEVELOPMENT_NOT_FORMAL_NOT_MERGED','quote_count':len(quotes),'forecast_count':len(rows),
            'states':dict(Counter(x['effective_status'] for x in rows)),'rows':rows,'modified_old_ledger':False}
    finally:db.close()


def model_comparison(ledger,span):
    evaluation=ledger.evaluation();rows=[];comparisons=[]
    for model in MODEL_NAMES:
        total=ledger.db.execute('SELECT count(*) FROM m6_predictions WHERE model=?',(model,)).fetchone()[0]
        latency=[b-a for a,b in ledger.db.execute('SELECT a.started,a.finished FROM inference_audit_v7 a JOIN m6_predictions p USING(prediction_id) WHERE p.model=?',(model,))]
        metric=evaluation['per_model'].get(model,{})
        rows.append({'model':model,'registered':total,'matched_matured':metric.get('n',0),'status':evaluation['status'],
            'mean_asset_batch_prediction_latency_seconds':float(np.mean(latency)) if latency else None,
            'forecast_availability':None,'availability_denominator':'attempted per-asset cycles in study_events_v7',**metric})
    # Predeclared paired contrasts versus Champion. Consecutive 45min block
    # losses aggregate cross-assets; circular moving-block bootstrap (4 blocks)
    # also retains remaining adjacent-block horizon dependence. No selection.
    blocks=evaluation['block_aware']
    for model in MODEL_NAMES[1:]:
        a=blocks.get(model,{}).get('block_pinball',[]);b=blocks.get('champion',{}).get('block_pinball',[])
        eligible=span>=48 and len(a)==len(b) and len(a)>=30
        item={'contrast':model+' minus champion','blocks':len(a),'ci95':None,'status':'INSUFFICIENT_PROSPECTIVE_EVIDENCE',
            'family_size':4,'significance_claim':False,'selection_or_promotion':False}
        if eligible:
            d=np.array(a)-np.array(b);rng=np.random.default_rng(7001);means=[];n=len(d)
            for _ in range(2000):
                starts=rng.integers(0,n,size=(n+3)//4);idx=np.concatenate([(s+np.arange(4))%n for s in starts])[:n];means.append(float(d[idx].mean()))
            item.update(ci95=np.quantile(means,[.025,.975]).tolist(),status='DESCRIPTIVE_PAIRED_BLOCK_BOOTSTRAP_NO_MULTIPLICITY_ADJUSTED_CLAIM',mean_difference=float(d.mean()))
        comparisons.append(item)
    attempted=Counter()
    for raw, in ledger.db.execute("SELECT payload FROM study_events_v7 WHERE kind='INFERENCE_CYCLE'"):
        event=json.loads(raw)
        for asset in event.get('models',{}):
            for model in MODEL_NAMES:attempted[model]+=1
    for row in rows:row['forecast_availability']=row['registered']/attempted[row['model']] if attempted[row['model']] else None
    return rows,{'evaluation':evaluation,'paired_multiple_testing_ledger':comparisons,'threshold_hours':48,'threshold_time_blocks':30}


def write_csv(path,rows,fields=None):
    fields=fields or list(dict.fromkeys(k for r in rows for k in r))
    with Path(path).open('w',newline='',encoding='utf-8-sig') as f:
        writer=csv.DictWriter(f,fieldnames=fields);writer.writeheader();writer.writerows(rows)


def generate(root='atlas_store',directory=DEFAULT_SESSION,out='reports',junit=None):
    from .atlas_shadow import PaperAccount
    from .atlas_orchestration import DecisionLedger
    from .atlas_memory import ResearchMemory
    root=Path(root).resolve();directory=Path(directory).resolve();out=Path(out);out.mkdir(exist_ok=True)
    contract=json.loads((directory/'study_contract.json').read_text());validate(root,contract)
    ledger=DeadlineLedger(directory)
    try:
        ledger.reconcile();status=ledger.status();deadlines=ledger.deadline_report();quotes=real_quotes(directory)
        models,stats=model_comparison(ledger,status['observed_span_hours'])
        runtime=ledger.db.execute("SELECT payload FROM study_runtime_v7 WHERE key='session'").fetchone();runtime=json.loads(runtime[0]) if runtime else {}
        network_errors=ledger.db.execute("SELECT count(*) FROM study_events_v7 WHERE kind='QUOTE_NETWORK_OR_VALIDATION_ERROR'").fetchone()[0]
        io=[dict(zip(('request_started','response_received','observed','stored'),r)) for r in ledger.db.execute('SELECT request_started,response_received,observed,stored FROM quote_io_v7')]
        cycles=[json.loads(r) for r, in ledger.db.execute("SELECT payload FROM study_events_v7 WHERE kind='INFERENCE_CYCLE'")]
    finally:ledger.close()
    legacy=legacy_audit(root/'research_challengers/milestone6/forward_v1')
    cohort=common_cohorts(quotes,contract['settings']['symbols'])
    weights={s:min(.1,.2/len(contract['settings']['symbols'])) for s in contract['settings']['symbols']}
    benchmarks={'cash':depth_replay(cohort,{}),'equal_weight_10pct_each_cash_residual':depth_replay(cohort,weights)}
    benchmarks.update({'buy_hold_'+s+'_10pct':depth_replay(cohort,{s:.1}) for s in weights})
    account=PaperAccount(SimpleNamespace(root=directory));memory=ResearchMemory(directory)
    try:
        proposals=[]
        for raw,sha in account.db.execute('SELECT payload,sha256 FROM allocation_proposals_v7'):
            payload=json.loads(raw)
            if _sha(payload)!=sha:raise ValueError('ALLOCATION_PROPOSAL_HASH_MISMATCH')
            proposals.append(payload)
        paper_actions=dict(account.db.execute('SELECT action,count(*) FROM events GROUP BY action'))
        cash=float(account.get('cash_tmn'));positions=account.db.execute('SELECT symbol,quantity,entry_cost FROM positions').fetchall()
        paper={'cash_tmn':cash,'positions':positions,'cash_only_nav_tmn':cash if not positions else None,'events':paper_actions,
            'paper_trades':sum(paper_actions.get(s,0) for s in ('PAPER_BUY','PAPER_SELL')),'chain_valid':account.verify(),
            'realized_exchange_pnl':None,'paper_cash_pnl_tmn':cash-5_000_000 if not positions else None,
            'zero_cash_return_is_not_edge':True,'model_allocation_pnl':None,'reason':'Research allocations are proposals, never broker instructions'}
        memory_status=memory.status()
        key='m7-nav-'+_sha({'cash':cash,'positions':positions,'contract':contract['contract_sha256'],'last_quote':status['last_quote']})
        stamp=time.time();memory.record(key,'PORTFOLIO',stamp,stamp,'STRATEGY_PERFORMANCE_EVIDENCE',_sha(paper),paper,'PAPER_ACCOUNT_NOT_EXCHANGE_PROFIT')
    finally:account.close();memory.close()
    decisions=DecisionLedger(directory)
    try:replay=decisions.replay();actual_veto=Counter()
    finally:decisions.close()
    db=sqlite3.connect((directory/'agent_evidence.sqlite').as_uri()+'?mode=ro',uri=True)
    try:
        for raw, in db.execute('SELECT risk_replay FROM decisions_v6'):
            p=json.loads(raw)
            if p:actual_veto[p['gate_decision']['reason']]+=1
    finally:db.close()
    reject=Counter(reason for p in proposals for reasons in p['rejections'].values() for reason in reasons)
    ref=json.loads(Path('reports/m6_reference_repositories.json').read_text())
    for row in ref:
        row['license_hash_still_matches']=hashlib.sha256(Path(row['license_file']).read_bytes()).hexdigest()==row['license_sha256']
        row['M7_use']='CONCEPT_ONLY_NO_EXTERNAL_CODE_COPIED_OR_EXECUTED'
    tests={'status':'NOT_EXECUTED_IN_THIS_REPORT_INVOCATION'}
    if junit:
        import xml.etree.ElementTree as ET
        suites=ET.parse(junit).getroot();s=suites if suites.tag=='testsuite' else suites.find('testsuite')
        tests={'tests':int(s.attrib['tests']),'failures':int(s.attrib['failures']),'errors':int(s.attrib['errors']),
            'skipped':int(s.attrib['skipped']),'seconds':float(s.attrib['time']),'junit_sha256':hashlib.sha256(Path(junit).read_bytes()).hexdigest(),
            'command':'PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 conda run --no-capture-output -n shbk python -m pytest -q --junitxml=reports/m7_pytest.xml'}
        tests['passed']=tests['tests']-tests['failures']-tests['errors']-tests['skipped']
    audits=[cost_audit(q,500000) for q in quotes]
    protected=['atlas_risk.py','atlas_broker.py','atlas_shadow.py','atlas_deep.py','atlas_signals.py','atlas_agent.py']
    unchanged=not subprocess.check_output(['git','diff','4fa99cc','--name-only','--',*[f'wallex_bot/{p}' for p in protected]],text=True).strip()
    integrity={'source_matches':source_manifest()==contract['source_manifest_LF_sha256'],'contract_sha256':contract['contract_sha256'],
        'source_commit':contract['source_commit'],'report_commit':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),
        'models_match':True,'protected_runtime_unchanged_from_M6':unchanged,'runtime':runtime,
        'wall_clock_elapsed_hours':max(0,(time.time()-runtime['started_epoch'])/3600) if runtime else 0,
        'continuous_uptime_claimed':False,'session_complete_claimed':False,'status':'PENDING_48_72H_REAL_OBSERVATION',
        'source_manifest_file_count':len(source_manifest()),'memory':memory_status}
    artifacts={
        'm7_portfolio_contract.json':{'formal_contract':contract,'atomic_budget_read':'BEGIN IMMEDIATE in same isolated PaperAccount SQLite transaction',
            'capital_location':str(directory/'shadow.sqlite'),'execution':'unchanged Agent -> ShadowBroker -> PaperAccount -> RiskGate, idempotent client ID',
            'mtm':'actual fresh held bids + cash, no missing bid fallback; sticky existing drawdown gate',
            'exit':'existing RiskGate final TMN liquidation only after actual session deadline; unresolved holdings retained',
            'research_authority':'no broker, no live, no promotion; forecasts/proposals append-only evidence'},
        'm7_forward_maturity.json':{'formal':status,'legacy_development_separate':legacy,'statistics':stats},
        'm7_quote_deadline_coverage.json':{**deadlines,'quote_io':io,'network_errors':network_errors,'old_M6_not_repaired_with_late_quotes':True},
        'm7_cost_and_liquidity_audit.json':{'observations':audits,'verified_account_fee':None,'credentials_used':False,
            'maker_taker_status':'UNVERIFIED; 0.1% per side assumption only','tick_lot_minimum_status':'UNVERIFIED; precision not tick/step',
            'successful_public_quote_requests':len(io),'failed_public_quote_attempts':network_errors,'sync_runs':[c.get('sync') for c in cycles]},
        'm7_portfolio_evaluation.json':{'status':'INSUFFICIENT_PROSPECTIVE_EVIDENCE','economic_edge':'NO_VERIFIED_ECONOMIC_EDGE',
            'paper':paper,'common_cohorts':len(cohort),'benchmarks':benchmarks,'M5_model_policy_returns':None,
            'M5_status':'only forecasts/proposals, not executed policies; no invented PnL attribution',
            'win_loss':None,'profit_factor':None,'risk_adjusted_return':None,'model_selection':False},
        'm7_risk_veto_audit.json':{'actual_agent_risk_reasons':dict(actual_veto),'decision_replay':replay,
            'proposal_count':len(proposals),'proposal_statuses':dict(Counter(p['status'] for p in proposals)),
            'research_rejections':dict(reject),'opportunity_rejection_rate':sum(not p['target_weights'] for p in proposals)/len(proposals) if proposals else None,
            'rejection_denominator':'all model/method proposals including cash and validation-ineligible methods; NOT independent opportunities',
            'liquidity_rejections':{k:v for k,v in reject.items() if 'DEPTH' in k or 'LIQUID' in k}},
        'm7_session_integrity.json':integrity,'m7_reference_integration.json':{'external_repositories':ref,
            'internal_code_reused':['RiskGate','PaperAccount','ShadowBroker','DataSyncManager','ModelObservationLedger','ResearchMemory','measure_book','_buy_with_notional','_sell_qty','DecisionLedger.replay'],
            'new_original_code':['atlas_portfolio.py','atlas_study.py','atlas_portfolio_report.py'],'copied_external_lines':0},
        'm7_test_results.json':tests,
        'm7_remaining_research_gaps.json':{'status':'INSUFFICIENT_PROSPECTIVE_EVIDENCE','open':[
            'Run actual foreground collector for 48/72h; bounded smoke is not completed study',
            'Verify timely future quotes, restart downtime and network gaps over full period',
            'Verified account fees and exchange tick/lot/spot minimum absent',
            'No independent validation of covariance allocators; complex methods disabled',
            'Forecasts trained on candle returns evaluated on quote proxy: not executable calibration',
            'No executed research allocation PnL; no verified economic edge',
            'Partial fills/queue position/hidden liquidity not modeled; no guaranteed execution',
            'No multi-process private order authority; LIVE remains HARD_DISABLED']}}
    for name,value in artifacts.items():_save_atomic(out/name,value)
    write_csv(out/'m7_model_comparison.csv',models)
    write_csv(out/'m7_allocation_methods.csv',[{'method':m,'authority':'RESEARCH_ONLY',
        'status':'DISABLED_INDEPENDENT_VALIDATION_REQUIRED' if m in ('risk_parity','minimum_variance','volatility_targeting') else 'IMPLEMENTED_FAIL_CLOSED',
        'proposal_count':sum(p['method']==m for p in proposals),'executed_allocations':0} for m in METHODS])
    return {'status':status,'paper':paper,'tests':tests,'integrity':integrity,'proposal_count':len(proposals)}


def main():
    p=argparse.ArgumentParser();p.add_argument('--root',default='atlas_store');p.add_argument('--session-dir',default=DEFAULT_SESSION);p.add_argument('--junit');args=p.parse_args()
    print(json.dumps(generate(args.root,args.session_dir,junit=args.junit),ensure_ascii=False,default=str))

if __name__=='__main__':main()
