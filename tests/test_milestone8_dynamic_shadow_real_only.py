"""Existing real quote/forecast receipts; no manufactured financial scenario."""
import copy,json,sqlite3
from pathlib import Path
import pytest
from wallex_bot.atlas_agentic_review import board
from wallex_bot.atlas_dynamic_shadow import DynamicShadowBroker,account_snapshot,replay,ACTIONS
from wallex_bot.atlas_portfolio_report import real_quotes
from wallex_bot.atlas_forward import _sha

ROOT=Path(__file__).resolve().parents[1]
OLD=ROOT/'atlas_store/research_challengers/milestone7/formal_48h_v1'

@pytest.fixture
def actual(tmp_path):
    if not (OLD/'study_contract.json').is_file():pytest.skip('DATA_NOT_AVAILABLE: original M7 contract required')
    contract=json.loads((OLD/'study_contract.json').read_text());contract['settings']['research_profile']='ATLAS_M8_AGENTIC_V1'
    directory=tmp_path/'research_challengers/milestone8/unit-control';directory.mkdir(parents=True)
    db=sqlite3.connect((OLD/'agent_evidence.sqlite').as_uri()+'?mode=ro',uri=True)
    try:e=json.loads(db.execute('SELECT evidence FROM decisions_v6 ORDER BY created LIMIT 1').fetchone()[0])
    finally:db.close()
    q=next(q for q in real_quotes(ROOT/'atlas_store') if q['receipt_sha256']==e['quote_receipt_sha256'])
    broker=DynamicShadowBroker(directory,contract)
    try:yield broker,e,q
    finally:broker.close()

def test_noop_cash_conservation_and_idempotency(actual):
    broker,e,q=actual;r=board(e)
    intent={'action':'STAY_IN_CASH','symbol':e['symbol'],'intent_id':_sha({'nonfinancial_control':'cash-only'}),'prediction_id':None}
    before=account_snapshot(broker.account,{e['symbol']:q})
    result=broker.submit(intent,forecast=r['forecast_for_gate'],quotes={e['symbol']:q},review=r,cycle_id='metadata-control')
    assert result['before']['cash_tmn']==result['after']['cash_tmn']==before['cash_tmn']
    assert result['trade_estimate'] is None and result['exchange_fill'] is None
    assert result==broker.submit(intent,forecast=r['forecast_for_gate'],quotes={e['symbol']:q},review=r,cycle_id='metadata-control')
    assert broker.db.execute('SELECT count(*) FROM dynamic_intents_v8').fetchone()[0]==1
    assert broker.account.verify() and replay(result)['cash_conserved']

@pytest.mark.parametrize('action',['BUY','ADD','REDUCE','SELL','REBALANCE'])
def test_stale_real_data_cannot_authorize_any_resize(actual,action):
    broker,e,q=actual;r=board(e)
    intent={'action':action,'symbol':e['symbol'],'intent_id':_sha({'action_control':action}),'prediction_id':None}
    before=account_snapshot(broker.account,{e['symbol']:q})
    with pytest.raises(ValueError,match='FRESH_REAL_QUOTE'):broker.submit(intent,forecast=r['forecast_for_gate'],quotes={e['symbol']:q},review=r,cycle_id='metadata-control')
    assert account_snapshot(broker.account,{e['symbol']:q})==before
    assert not broker.db.execute('SELECT count(*) FROM dynamic_intents_v8').fetchone()[0]

def test_all_required_actions_have_explicit_contract():
    assert set(ACTIONS)=={'BUY','ADD','HOLD','REDUCE','SELL','REBALANCE','STAY_IN_CASH','REJECT'}

def test_old_session_cannot_be_reused_for_new_policy(tmp_path):
    if not (OLD/'study_contract.json').is_file():pytest.skip('DATA_NOT_AVAILABLE: original M7 contract required')
    c=json.loads((OLD/'study_contract.json').read_text())
    with pytest.raises(ValueError,match='SEPARATE_OPT_IN'):DynamicShadowBroker(OLD,c)

def test_no_live_profile_can_construct_broker(tmp_path):
    c={'settings':{'research_profile':'ATLAS_M8_AGENTIC_V1','LIVE':'ENABLED'}}
    with pytest.raises(ValueError,match='HARD_DISABLED'):DynamicShadowBroker(tmp_path/'milestone8',c)

def test_nonfinite_proposal_amount_rejected_before_account_mutation(actual):
    broker,e,q=actual;r=board(e)
    with pytest.raises(ValueError,match='AMOUNT'):
        broker.submit({'action':'BUY','symbol':e['symbol'],'intent_id':'0'*64,'notional_tmn':float('nan')},
            forecast=r['forecast_for_gate'],quotes={e['symbol']:q},review=r,cycle_id='metadata-control')
    assert broker.account.verify()

def test_review_cannot_change_forecast_or_grant_authority(actual):
    broker,e,q=actual;r=board(e);broken=copy.deepcopy(r);broken['recommendation']='EVALUATE_WITH_UNCHANGED_RISKGATE'
    broken['live_authority']=True
    with pytest.raises(ValueError,match='REVIEW_HASH'):
        broker.submit({'action':'STAY_IN_CASH','symbol':e['symbol'],'intent_id':'0'*64},forecast=r['forecast_for_gate'],quotes={e['symbol']:q},review=broken,cycle_id='metadata-control')
