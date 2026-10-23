"""M6 real archived observations and non-financial orchestration contracts."""
import copy,json,sqlite3,time,inspect
from pathlib import Path
from datetime import datetime,timezone
import pytest
from wallex_bot.atlas_forward import _sha,_canon
from wallex_bot.atlas_review import review,broker_evidence,ROLES
from wallex_bot.atlas_memory import ResearchMemory
from wallex_bot.atlas_prospective import ModelObservationLedger
from wallex_bot.atlas_orchestration import DecisionLedger

ROOT=Path(__file__).resolve().parents[1]
SESSION=ROOT/'atlas_store/research_challengers/milestone6/forward_v1'

@pytest.fixture(scope='module')
def actual():
    if not (SESSION/'agent_evidence.sqlite').exists():pytest.skip('Actual M6 observations not installed')
    db=sqlite3.connect((SESSION/'agent_evidence.sqlite').as_uri()+'?mode=ro',uri=True)
    try:row=db.execute('SELECT evidence,review,risk_replay FROM decisions_v6 ORDER BY created LIMIT 1').fetchone()
    finally:db.close()
    if not row:pytest.skip('No actual decision evidence')
    return tuple(json.loads(x) for x in row)

def test_seven_structured_roles_and_deterministic_replay(actual):
    evidence,result,_=actual
    assert review(evidence)==result
    assert tuple(a['role'] for a in result['agents'])==ROLES
    assert all(a['authority']=='ADVISORY_STRUCTURED_NO_TOOLS' for a in result['agents'])
    assert result['proposal']['requires_deterministic_risk_gate']

def test_watch_and_agent_share_actual_contract():
    from wallex_bot import atlas_shadow,atlas_agent
    assert 'run_assets' in inspect.getsource(atlas_shadow.shadow_cycle)
    assert 'from .atlas_agent import cycle' in inspect.getsource(__import__('wallex_bot.atlas_orchestration',fromlist=['run_assets']).run_assets)
    assert 'from .atlas_review import review' in inspect.getsource(atlas_agent.cycle)

def test_missing_optional_news_does_not_create_core_veto(actual):
    evidence,result,_=actual;missing=copy.deepcopy(evidence);missing['news']={}
    repeated=review(missing)
    assert repeated['proposal']['veto_reasons']==[x for x in result['proposal']['veto_reasons'] if x!='observed_finbert_high_negative_news']
    assert repeated['agents'][1]['status']=='INSUFFICIENT_EVIDENCE'

def test_per_asset_readiness_fail_closed(actual):
    evidence,_,_=actual;bad=copy.deepcopy(evidence);bad['readiness']={'ready':False}
    result=review(bad);prediction=broker_evidence(bad['prediction'],result)
    assert 'asset_data_not_ready' in result['proposal']['veto_reasons']
    assert prediction['quantile_log_returns']['q10'] is None
    assert bad['prediction']['quantile_log_returns']['q10'] is not None

def test_global_risk_replay_uses_unchanged_gate(actual):
    from wallex_bot.atlas_risk import RiskGate,RiskLimits
    from dataclasses import asdict
    inputs=actual[2]
    assert asdict(RiskGate().limits)==inputs['policy_limits']
    assert asdict(RiskGate().evaluate(inputs['symbol'],inputs['forecast'],inputs['book'],inputs['cash_tmn'],inputs['positions'],inputs['stopped'],inputs['fee_assumption']))==inputs['gate_decision']

def test_llm_no_broker_authority_or_promotion():
    import wallex_bot.atlas_review as module
    source=inspect.getsource(module)
    assert 'ShadowBroker(' not in source and 'import requests' not in source
    from wallex_bot.atlas_agent import cycle
    assert inspect.signature(cycle).parameters['enable_llm'].default is False
    assert 'promote_champion(' not in inspect.getsource(cycle)

def test_memory_pit_creation_and_idempotency_with_actual_evidence(actual,tmp_path):
    evidence,_,_=actual;memory=ResearchMemory(tmp_path)
    # Original actual cutoff is unambiguously before this import. Use the
    # original observed/available times, so ONLY actual creation prevents a
    # backdated record leaking. Avoid cross-clock sub-millisecond races.
    before=datetime.fromtimestamp(evidence['decision_time'],timezone.utc).isoformat();stamp=evidence['available_at'];source=_sha(evidence)
    payload={'symbol':evidence['symbol'],'actual_observation_id':evidence['observation_id']}
    try:
        first=memory.record('actual-observation',evidence['symbol'],evidence['decision_time'],stamp,'DECISION_RISK_VETO',source,payload)
        assert memory.record('actual-observation',evidence['symbol'],evidence['decision_time'],stamp,'DECISION_RISK_VETO',source,payload)==first
        assert memory.retrieve(evidence['symbol'],before)==[]
        rows=memory.retrieve(evidence['symbol'],datetime.now(timezone.utc).isoformat())
        assert len(rows)==1 and rows[0]['source_hash']==source and memory.verify()
        for field in ('importance','recency','relevance','availability_time','created_at','evaluation_status'):assert field in rows[0]
    finally:memory.close()
    read=ResearchMemory(tmp_path,mode='BACKTEST')
    try:
        with pytest.raises(Exception):read.record('blocked',evidence['symbol'],stamp,stamp,'RESEARCH_LESSON',source,{})
        assert read.retrieve(evidence['symbol'],before)==[]
    finally:read.close()

def test_actual_news_reference_cutoff_is_verified(actual,tmp_path):
    from wallex_bot.atlas_news_pipeline import NewsStore
    evidence=actual[0]
    # Query-only from an isolated copy; never rescore or backdate news.
    source=sqlite3.connect((ROOT/'atlas_store/news.sqlite').as_uri()+'?mode=ro',uri=True)
    dest=sqlite3.connect(tmp_path/'news.sqlite');source.backup(dest);source.close();dest.close()
    with NewsStore(tmp_path) as store:
        articles=store.evidence_at(evidence['symbol'],datetime.fromtimestamp(evidence['decision_time'],timezone.utc).isoformat())
    for article in articles:
        assert datetime.fromisoformat(article['available_at']).timestamp()<=evidence['decision_time']
        assert datetime.fromisoformat(article['analysis_available_at']).timestamp()<=evidence['decision_time']

def test_real_prospective_registration_schema_and_shared_timestamp(actual):
    ledger=ModelObservationLedger(SESSION)
    try:
        rows=ledger.db.execute('SELECT payload,payload_sha FROM m6_predictions').fetchall()
        assert len(rows)>=10
        groups={}
        for raw,sha in rows:
            p=json.loads(raw);assert _sha(p)==sha
            assert p['data_cutoff']<=p['decision_time']==p['prediction_available_at']
            assert p['decision_time']-p['observed_quote_time']<=60
            assert p['q10']<=p['q50']<=p['q90'] and p['forecast_horizon']==2700
            assert p['trained_target']!=p['evaluated_target'] and p['source_receipts']
            groups.setdefault((p['symbol'],p['data_cutoff'],p['decision_time']),set()).add(p['model_version'])
        assert any(len(g)==5 for g in groups.values())
    finally:ledger.close()

def test_process_lease_prevents_duplicate_collectors(tmp_path):
    first=ModelObservationLedger(tmp_path);second=ModelObservationLedger(tmp_path)
    try:
        assert first.claim() and not second.claim();first.release();assert second.claim()
    finally:second.release();first.close();second.close()

def test_restart_keeps_real_pending_forecasts():
    first=ModelObservationLedger(SESSION);before=first.status();first.close()
    second=ModelObservationLedger(SESSION)
    try:assert second.status()['by_model']==before['by_model']
    finally:second.close()

def test_no_clock_advancement_or_fake_future_quote(tmp_path):
    ledger=ModelObservationLedger(tmp_path)
    try:
        with pytest.raises(ValueError,match='ADVANCE'):ledger.reconcile(now=time.time()+3600)
        assert ledger.reconcile()['scored_now']==0 and ledger.status()['matured_scored']==0
        assert ledger.evaluation()['status']=='PENDING_NO_SHARED_MATURED_QUOTES'
        with pytest.raises(ValueError,match='REAL_QUOTE'):ledger.quote(1)
    finally:ledger.close()

def test_reconcile_using_original_real_legacy_prediction_and_future_receipts(tmp_path):
    source=ROOT/'atlas_store/forward_observations.sqlite'
    if not source.is_file():pytest.skip('DATA_NOT_AVAILABLE: original quote ledger required')
    db=sqlite3.connect(source.as_uri()+'?mode=ro',uri=True)
    try:
        row=db.execute('''SELECT f.symbol,f.q10,f.q50,f.q90,f.fee_per_side,f.due_epoch,f.origin_quote_id,o.future_quote_id,o.actual_mid_log_return
            FROM forecasts f JOIN outcomes o ON o.forecast_id=f.id JOIN quotes q ON q.id=o.future_quote_id
            WHERE q.observed_epoch BETWEEN f.due_epoch AND f.due_epoch+300 ORDER BY f.id LIMIT 1''').fetchone()
        if row is None:pytest.skip('No actual original forecast with a timely actual future quote')
        symbol,q10,q50,q90,fee,due,origin,future,expected=row
        quotes=[db.execute('SELECT * FROM quotes WHERE id=?',(i,)).fetchone() for i in (origin,future)]
    finally:db.close()
    # COPY an already recorded ORIGINAL forecast and its real quote receipts.
    # This is a labelled legacy-replay fixture, NEVER a new prospective record.
    ledger=ModelObservationLedger(tmp_path)
    try:
        with ledger.db:
            for quote in quotes:ledger.db.execute('INSERT INTO quotes VALUES(?,?,?,?,?,?,?,?)',quote)
            payload={'q10':q10,'q50':q50,'q90':q90,'expected_cost':{'fee_per_side_assumed':fee},'track':'ORIGINAL_LEGACY_RECORD_REPLAY_ONLY'}
            ledger.db.execute('INSERT INTO m6_predictions VALUES(?,?,?,?,?,?,?,?,?,?,?)',('original-real-forecast',symbol,'legacy_original',quotes[0][2],int(quotes[0][2]),due,origin,'original','PENDING',_canon(payload),_sha(payload)))
        assert ledger.reconcile()['scored_now']==1
        result=json.loads(ledger.db.execute('SELECT payload FROM m6_outcomes').fetchone()[0])
        assert result['MID_TO_MID_RETURN']==pytest.approx(expected)
        assert result['realized_PnL'] is None and result['CLOSE_TO_CLOSE_RETURN'] is None
        assert ledger.reconcile()['scored_now']==0
    finally:ledger.close()

def test_decision_replay_never_changes_account_or_memory():
    from wallex_bot.atlas_m5_inference import logical_hash
    before=logical_hash(SESSION/'shadow.sqlite');memory=logical_hash(ROOT/'atlas_store/context_memory.sqlite')
    ledger=DecisionLedger(SESSION)
    try:
        outputs=ledger.replay()
        if not outputs:pytest.skip('DATA_NOT_AVAILABLE: actual saved decisions required')
        assert outputs
        assert all(r['receipt_valid'] and r['review_identical'] and r['risk_gate_identical'] for r in outputs)
    finally:ledger.close()
    assert before==logical_hash(SESSION/'shadow.sqlite') and memory==logical_hash(ROOT/'atlas_store/context_memory.sqlite')
