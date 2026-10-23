"""Replay only actual M7 evidence and non-financial authority contracts."""
import copy,inspect,json,math,sqlite3
from pathlib import Path
import pytest
from wallex_bot.atlas_agentic_review import board,ABLATIONS
from wallex_bot.atlas_portfolio_report import real_quotes
from wallex_bot.atlas_portfolio import cost_audit

ROOT=Path(__file__).resolve().parents[1]

@pytest.fixture(scope='module')
def actual():
    if not (ROOT/'atlas_store/research_challengers/milestone7/formal_48h_v1/agent_evidence.sqlite').is_file():
        pytest.skip('DATA_NOT_AVAILABLE: actual M7 decision receipts required')
    db=sqlite3.connect((ROOT/'atlas_store/research_challengers/milestone7/formal_48h_v1/agent_evidence.sqlite').as_uri()+'?mode=ro',uri=True)
    try:e=json.loads(db.execute('SELECT evidence FROM decisions_v6 ORDER BY created LIMIT 1').fetchone()[0])
    finally:db.close()
    q=next(q for q in real_quotes(ROOT/'atlas_store') if q['receipt_sha256']==e['quote_receipt_sha256'])
    e['book']=cost_audit(q,500000);return e

def test_ten_roles_share_explicit_structured_contract(actual):
    r=board(actual);required={'agent_name','decision_timestamp','symbol','evidence_ids','source_hashes','signal','confidence','uncertainty','limitations','recommendation','reasoning_summary'}
    assert len(r['agents'])==10 and all(required<=a.keys() for a in r['agents'])
    assert all(a['decision_timestamp']==actual['decision_time'] for a in r['agents'])

def test_review_reproduces_without_mutating_actual_evidence(actual):
    original=copy.deepcopy(actual);assert board(actual)==board(actual);assert actual==original

def test_original_ai_forecast_contributes_before_explanation(actual):
    r=board(actual)
    message=next(m for m in r['cross_review_messages'] if m['type']=='AI_EDGE_BELOW_OBSERVED_COST')
    assert message['forecast_q10']==actual['prediction']['quantile_log_returns']['q10']
    assert message['contribution']=='MODEL_OUTPUT_REJECTS_ENTRY_BEFORE_EXPLANATION'
    assert r['live_authority'] is False

def test_unvalidated_optional_agents_cannot_become_trading_votes(actual):
    r=board(actual)
    for m in r['cross_review_messages']:
        if m['type']=='EVIDENCE_QUALIFICATION':assert not m['decision_qualified']

@pytest.mark.parametrize('arm',ABLATIONS)
def test_predeclared_ablation_has_no_promotion_authority(actual,arm):
    r=board(actual,arm=arm)
    assert not r['automatic_promotion'] and not r['live_authority']
    assert r['arm']==arm

def test_rule_only_does_not_forge_ai_forecast(actual):
    r=board(actual,arm='rule_only')
    assert r['forecast_for_gate']['quantile_log_returns']['q10'] is None
    assert actual['prediction']['quantile_log_returns']['q10'] is not None

def test_nonfinancial_future_memory_metadata_is_blocked(actual):
    e=copy.deepcopy(actual);stamp=e['decision_time']
    e['research_memory']=[{'event_id':'metadata-only-control','observation_time':stamp,'availability_time':stamp,'created_at':stamp+1}]
    with pytest.raises(ValueError,match='MEMORY_NOT_AVAILABLE'):board(e)

def test_no_llm_or_tool_order_authority():
    source=inspect.getsource(board)
    assert 'requests.' not in source and 'ShadowBroker(' not in source and 'promote_champion(' not in source
