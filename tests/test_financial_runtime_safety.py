"""Control metadata and actual local receipts only. No fake prices or fills."""
import json
from pathlib import Path
import pytest
from wallex_bot.atlas_broker import BrokerSafetyError,IdempotencyConflict
from wallex_bot.atlas_spot_exchange import SpotLedger
from wallex_bot.atlas_spot_runtime import AccountSpotTransport,ControlledSpotBroker,_NetworkPermit
from wallex_bot.atlas_finance import status,fee_contract,recorded_summary,current_session
from wallex_bot.atlas_finance_control import FinanceControl


@pytest.mark.parametrize('method',['POST','DELETE'])
@pytest.mark.parametrize('permit',[None,lambda *_:True,True])
def test_no_mutation_with_missing_or_callable_permission(monkeypatch,method,permit):
    import requests
    monkeypatch.setattr(requests,'request',lambda *a,**k:pytest.fail('No network allowed'))
    with pytest.raises(BrokerSafetyError,match='NO_PROCESS_LOCAL'):
        AccountSpotTransport('control_account').request(method,'order',permit=permit)


def test_no_withdrawal_endpoint_and_no_capability_forgery():
    with pytest.raises(BrokerSafetyError,match='ENDPOINT'):
        AccountSpotTransport('control_account').request('POST','withdrawal')
    with pytest.raises(BrokerSafetyError,match='INVALID_EXECUTION'):
        _NetworkPermit(None,'BUY','POST',None,None,object())


def test_metadata_idempotency_restart_and_audit(tmp_path):
    # Pure identity/control record, deliberately no price/quantity/market data.
    payload={'client_id':'control_identity_1','symbol':'BTCTMN','side':'BUY'}
    ledger=SpotLedger(tmp_path)
    assert ledger.register(payload)
    assert not ledger.register(payload)
    with pytest.raises(IdempotencyConflict):ledger.register({**payload,'side':'SELL'})
    with ledger.db:ledger._state(payload['client_id'],'SUBMITTED','CONTROL_METADATA_NO_NETWORK')
    ledger.close();ledger=SpotLedger(tmp_path)
    assert ledger.status(payload['client_id'])['state']=='UNKNOWN'
    assert not ledger.register(payload)
    with ledger.db:ledger.db.execute("UPDATE spot_orders SET state='FILLED'")
    with pytest.raises(BrokerSafetyError,match='INTEGRITY'):ledger._require_integrity()
    ledger.close()


def test_restart_default_disarms_and_missing_proofs_block(tmp_path,monkeypatch):
    import requests
    monkeypatch.setattr(requests,'request',lambda *a,**k:pytest.fail('No network allowed'))
    operations=tmp_path/'operations';operations.mkdir()
    approval=operations/'approval.json'
    approval.write_text(json.dumps({'account_client_id':'control_account'}))
    for _ in range(2):
        broker=ControlledSpotBroker(tmp_path,approval,tmp_path/'research_challengers/control')
        try:
            assert broker.arm_state is None
            with pytest.raises(BrokerSafetyError,match='DISARMED'):broker._permit('BUY')
            with pytest.raises(BrokerSafetyError,match='SCHEMA'):
                broker.arm_interactive(input_fn=lambda *_:pytest.fail('No confirmation without proofs'))
        finally:broker.close()


def test_empty_status_creates_no_files_or_zero_profit(tmp_path):
    result=status(tmp_path)
    assert result['real']['balance_tmn'] is None
    assert result['real']['realized_exchange_pnl'] is None
    assert list(tmp_path.iterdir())==[]


def test_no_fee_assumption_without_real_read(tmp_path):
    with pytest.raises(ValueError,match='REAL_FEE_READ'):fee_contract(tmp_path,['BTCTMN'])


def test_control_rejects_live_arbitrary_shell_and_paths(tmp_path):
    control=FinanceControl(tmp_path)
    for action in ('live','arm','submit','cancel','start;whoami','../'):
        with pytest.raises(ValueError,match='NOT_ALLOWED'):control.command(action)
    assert not control.state()['running_in_this_server']
    assert list(tmp_path.iterdir())==[]


def test_existing_real_receipt_replay_is_not_exchange_profit():
    folder=Path('atlas_store/research_challengers/milestone8/formal_48h_v1')
    if not (folder/'agentic_decisions.sqlite').exists():pytest.skip('Actual local decision receipts absent')
    p=recorded_summary(folder)
    assert p['decision_count']>0
    assert p['orders_sent_to_exchange']==0 and p['realized_exchange_pnl'] is None
    assert all(not d['actual_exchange_fill'] for d in p['decisions'])


def test_real_fee_import_is_exactly_actual_receipt():
    root=Path('atlas_store');path=root/'operations/private_account_read.json'
    if not path.exists():pytest.skip('Actual private read receipt absent; no substitute')
    p=json.loads(path.read_text())
    if not all(s in p.get('verified_read_fee_rates',{}) for s in ('BTCTMN','ETHTMN')):pytest.skip('Required real fee fields absent')
    contract=fee_contract(root,['BTCTMN','ETHTMN'])
    assert contract['fee_per_side_assumed']==p['verified_read_fee_rates']['BTCTMN']['takerFeeRate']
    assert contract['fee_evidence']['historical_fee_attribution'] is False


def test_real_exchange_fill_contract_requires_authorized_recordings():
    # Absence is an explicit evidence gap, never a fabricated positive fill test.
    pytest.skip('No authorized, sanitized real exchange fill recordings supplied')
