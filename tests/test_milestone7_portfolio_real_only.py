"""Original archived quotes/forecasts or non-financial control metadata only."""
import copy,inspect,json,sqlite3,time
from pathlib import Path
from dataclasses import asdict
import pytest
from wallex_bot.atlas_portfolio import allocate,projected_weights,cost_audit,METHODS
from wallex_bot.atlas_portfolio_report import real_quotes,common_cohorts,depth_replay
from wallex_bot.atlas_study import DeadlineLedger,source_manifest,settings,prepare
from wallex_bot.atlas_risk import RiskGate

ROOT=Path(__file__).resolve().parents[1]
OLD=ROOT/'atlas_store/research_challengers/milestone6/forward_v1'

@pytest.fixture(scope='module')
def actual():
    if not (OLD/'forward_observations.sqlite').exists():pytest.skip('Real M6 archive not installed')
    quotes=real_quotes(OLD)
    db=sqlite3.connect((OLD/'forward_observations.sqlite').as_uri()+'?mode=ro',uri=True)
    try:
        row=db.execute('SELECT payload FROM m6_predictions ORDER BY decision LIMIT 1').fetchone()
        if row is None:pytest.skip('DATA_NOT_AVAILABLE: original M6 predictions required')
        p=json.loads(row[0])
    finally:db.close()
    q=min((q for q in quotes if q['symbol']==p['symbol']),key=lambda q:abs(q['observed_epoch']-p['observed_quote_time']))
    return quotes,p,q

def state():return {'cash_tmn':5_000_000,'positions':[],'stopped':False,'high_water_tmn':5_000_000}

def candidates(actual):
    _,p,q=actual
    return {p['symbol']:{'quote':q,'forecast':{'quantile_log_returns':{k:p[k] for k in ('q10','q50','q90')}},
        'prediction_available_at':p['prediction_available_at'],'spot_tmn':True}}

def test_budget_projection_nonfinancial_scores():
    weights=projected_weights({'a':1.,'b':2.},.1,.08)
    assert all(0<=x<=.08 for x in weights.values()) and sum(weights.values())<=.1
    assert 1-sum(weights.values())>=.9

def test_projection_rejects_nonfinite_metadata():
    with pytest.raises(ValueError):projected_weights({'x':float('nan')},.1,.1)

def test_cash_baseline_does_not_need_market_price():
    p=allocate('cash',state(),{})
    assert p['cash_weight']==1 and p['target_weights']=={} and p['estimated_rebalance_cost_tmn']==0
    assert not p['execution_eligible'] and p['nav_tmn']==5_000_000

@pytest.mark.parametrize('method',METHODS)
def test_no_allocation_without_evidence(method):
    p=allocate(method,state(),{})
    assert not p['target_weights'] and p['authority']=='RESEARCH_PROPOSAL_ONLY_NO_BROKER'

def test_real_depth_cost_and_receipt(actual):
    audit=cost_audit(actual[2],500000)
    assert audit['estimated_roundtrip_log_cost']>=0 and not audit['fee_verified']
    assert audit['exchange_fill'] is None and audit['exchange_tick_size'] is None
    assert audit['exchange_quantity_step'] is None

def test_tampered_receipt_rejected_without_altering_price(actual):
    q=copy.deepcopy(actual[2]);q['receipt_sha256']='0'*64
    with pytest.raises(ValueError,match='HASH'):cost_audit(q,500000)

def test_stale_real_quote_blocks_proposal(actual):
    p=allocate('equal_weight',state(),candidates(actual),now=time.time())
    assert p['target_weights']=={} and 'STALE_OR_MISSING_QUOTE' in p['rejections'][actual[1]['symbol']]

def test_original_prediction_no_risk_bypass(actual):
    c=candidates(actual);p=allocate('equal_weight',state(),c,now=actual[1]['prediction_available_at'])
    assert p['risk_limits']==asdict(RiskGate().limits)
    assert sum(p['target_weights'].values())<=.1 and p['cash_weight']>=.9
    assert not p['execution_eligible']

def test_missing_high_water_rejects():
    a=state();del a['high_water_tmn']
    assert allocate('cash',a,{})['status']=='REJECTED_MISSING_EQUITY_STATE'

def test_complex_methods_disabled_not_unvalidated_optimizer(actual):
    for method in ('risk_parity','minimum_variance','volatility_targeting'):
        p=allocate(method,state(),candidates(actual),now=actual[1]['prediction_available_at'])
        assert p['method_status']=='INSUFFICIENT_INDEPENDENT_ALLOCATION_VALIDATION' and not p['target_weights']

def test_common_actual_cohorts_no_interpolation(actual):
    cohorts=common_cohorts(actual[0],['BTCTMN','PEPETMN'])
    assert cohorts
    for c in cohorts:assert max(q['observed_epoch'] for q in c.values())-min(q['observed_epoch'] for q in c.values())<=30

def test_real_depth_cash_accounting_reproducible(actual):
    cohorts=common_cohorts(actual[0],['BTCTMN','PEPETMN'])
    a=depth_replay(cohorts,{'BTCTMN':.1,'PEPETMN':.1})
    assert a==depth_replay(cohorts,{'BTCTMN':.1,'PEPETMN':.1})
    assert a['exchange_fills'] is None and not a['close_price_fill_used']
    for row in a['nav_path']:
        assert row['cash_tmn']==4_000_000
        assert row['liquidation_nav_tmn']==pytest.approx(5_000_000+row['net_counterfactual_pnl_tmn'])
        assert row['gross_counterfactual_pnl_tmn']-row['net_counterfactual_pnl_tmn']==pytest.approx(row['assumed_entry_exit_fees_tmn'])
    assert a['max_drawdown'] is None and a['sharpe'] is None

def test_cash_benchmark_zero_is_not_strategy_return(actual):
    a=depth_replay(common_cohorts(actual[0],['BTCTMN','PEPETMN']),{})
    assert all(p['liquidation_nav_tmn']==5_000_000 for p in a['nav_path'])

def test_pin_all_runtime_source_and_normalize_line_endings(tmp_path):
    (tmp_path/'wallex_bot').mkdir();(tmp_path/'scripts').mkdir();(tmp_path/'third_party').mkdir()
    p=tmp_path/'wallex_bot/control.py';p.write_bytes(b'# control\r\n');(tmp_path/'third_party/SOURCES.md').write_text('metadata')
    first=source_manifest(tmp_path);p.write_bytes(b'# control\n');assert source_manifest(tmp_path)==first
    p.write_text('# changed control');assert source_manifest(tmp_path)!=first

def test_no_conversion_of_development_session(tmp_path):
    with pytest.raises(ValueError,match='MILESTONE7'):prepare(ROOT/'atlas_store',tmp_path/'milestone6')

def test_formal_contract_no_live_or_promotion():
    c=settings();assert c['LIVE']=='HARD_DISABLED' and c['automatic_promotion'] is False
    assert c['quote_interval_seconds']<c['quote_tolerance_seconds'] and c['allocation_authority']=='PROPOSALS_ONLY'
    import wallex_bot.atlas_portfolio as module
    assert 'ShadowBroker(' not in inspect.getsource(module) and 'requests.' not in inspect.getsource(module)

def test_network_failure_keeps_actual_receipts(actual,tmp_path,monkeypatch):
    import threading
    import wallex_bot.market as market
    from wallex_bot.atlas_study import quote_worker
    source=sqlite3.connect((OLD/'forward_observations.sqlite').as_uri()+'?mode=ro',uri=True)
    dest=sqlite3.connect(tmp_path/'forward_observations.sqlite');source.backup(dest);source.close();dest.close()
    ledger=DeadlineLedger(tmp_path);stop=threading.Event()
    try:
        before=ledger.db.execute('SELECT * FROM quotes ORDER BY id').fetchall();assert ledger.claim()
        def unavailable(symbol):stop.set();raise ConnectionError('non-financial transport outage control')
        monkeypatch.setattr(market,'depth',unavailable)
        contract={'settings':settings(),'source_manifest_LF_sha256':source_manifest(),'model_file_hashes':{}}
        quote_worker(ROOT/'atlas_store',tmp_path,contract,ledger.owner,stop)
        assert ledger.db.execute('SELECT * FROM quotes ORDER BY id').fetchall()==before
        assert ledger.db.execute("SELECT count(*) FROM study_events_v7 WHERE kind='QUOTE_NETWORK_OR_VALIDATION_ERROR'").fetchone()[0]==1
    finally:ledger.release();ledger.close()

def test_deadline_lease_restart_and_no_clock_advancement(tmp_path):
    a=DeadlineLedger(tmp_path);b=DeadlineLedger(tmp_path)
    try:
        assert a.claim() and not b.claim();a.release();assert b.claim()
        with pytest.raises(ValueError,match='ADVANCE'):b.reconcile(now=time.time()+3600)
        assert b.reconcile()['scored_now']==0 and b.reconcile()['scored_now']==0
        assert b.deadline_report()['timely_coverage'] is None
        assert b.next_sample('BTCTMN',last_observed=time.time())>=time.time()-1
    finally:a.close();b.release();b.close()

def test_original_pending_deadlines_survive_restart(actual,tmp_path):
    src=sqlite3.connect((OLD/'forward_observations.sqlite').as_uri()+'?mode=ro',uri=True)
    dst=sqlite3.connect(tmp_path/'forward_observations.sqlite');src.backup(dst);src.close();dst.close()
    a=DeadlineLedger(tmp_path)
    try:
        first=a.deadline_report();assert first['rows'];a.reconcile();count=a.db.execute('SELECT count(*) FROM deadline_queue_v7').fetchone()[0]
    finally:a.close()
    b=DeadlineLedger(tmp_path)
    try:
        assert b.db.execute('SELECT count(*) FROM deadline_queue_v7').fetchone()[0]==count
        assert b.reconcile()['scored_now']==0
        assert all(r['effective_status']!='SCORED_REAL_FUTURE_QUOTE' for r in b.deadline_report()['rows'])
    finally:b.close()

def test_required_runtime_is_unchanged_from_m6():
    import subprocess
    files=['atlas_risk.py','atlas_broker.py','atlas_agent.py','atlas_shadow.py','atlas_deep.py','atlas_signals.py']
    assert not subprocess.check_output(['git','diff','4fa99cc','--name-only','--',*[str(ROOT/'wallex_bot'/p) for p in files]],text=True).strip()

def test_timely_actual_legacy_outcome_deadline_memory_and_idempotency(tmp_path):
    if not (ROOT/'atlas_store/forward_observations.sqlite').is_file():pytest.skip('DATA_NOT_AVAILABLE: original quote ledger required')
    from wallex_bot.atlas_forward import _canon,_sha
    from wallex_bot.atlas_memory import ResearchMemory
    db=sqlite3.connect((ROOT/'atlas_store/forward_observations.sqlite').as_uri()+'?mode=ro',uri=True)
    try:
        row=db.execute('''SELECT f.symbol,f.q10,f.q50,f.q90,f.fee_per_side,f.due_epoch,f.origin_quote_id,o.future_quote_id,o.actual_mid_log_return
            FROM forecasts f JOIN outcomes o ON o.forecast_id=f.id JOIN quotes q ON q.id=o.future_quote_id
            WHERE q.observed_epoch BETWEEN f.due_epoch AND f.due_epoch+300 ORDER BY f.id LIMIT 1''').fetchone()
        if row is None:pytest.skip('No actual original timely forecast pair')
        symbol,q10,q50,q90,fee,due,origin,future,expected=row
        quotes=[db.execute('SELECT * FROM quotes WHERE id=?',(i,)).fetchone() for i in (origin,future)]
    finally:db.close()
    ledger=DeadlineLedger(tmp_path)
    try:
        payload={'q10':q10,'q50':q50,'q90':q90,'expected_cost':{'fee_per_side_assumed':fee},'track':'ORIGINAL_LEGACY_REPLAY_NOT_PROSPECTIVE'}
        with ledger.db:
            for q in quotes:ledger.db.execute('INSERT INTO quotes VALUES(?,?,?,?,?,?,?,?)',q)
            ledger.db.execute('INSERT INTO m6_predictions VALUES(?,?,?,?,?,?,?,?,?,?,?)',('original',symbol,'legacy',quotes[0][2],int(quotes[0][2]),due,origin,'original','PENDING',_canon(payload),_sha(payload)))
        assert ledger.next_sample(symbol,last_observed=due-10,now=due-10)==due
        assert ledger.reconcile()['scored_now']==1
        raw=ledger.db.execute('SELECT payload FROM m6_outcomes').fetchone()[0]
        assert json.loads(raw)['MID_TO_MID_RETURN']==pytest.approx(expected)
        assert ledger.reconcile()['scored_now']==0
        assert ledger.db.execute('SELECT payload FROM m6_outcomes').fetchone()[0]==raw
        row=ledger.deadline_report()['rows'][0];assert 0<=row['future_quote_latency_seconds']<=300
        memory=ResearchMemory(tmp_path)
        try:assert memory.verify() and memory.status()['layers']['MATURED_FORECAST_OUTCOME']==1
        finally:memory.close()
    finally:ledger.close()

def test_fast_source_pin_failure_stops_before_request(monkeypatch):
    import wallex_bot.atlas_study as module
    monkeypatch.setattr(module,'source_manifest',lambda:{'control':'changed'})
    with pytest.raises(RuntimeError,match='PINNED_SOURCE'):module.fast_validate({'source_manifest_LF_sha256':{'control':'original'}})
