"""Control metadata / real local receipts only; no synthetic prices or fills."""
import json
from pathlib import Path
from types import SimpleNamespace
import pytest
from wallex_bot.atlas_account_discovery import discover,AccountReader,object_rows,public_summary
from wallex_bot.atlas_broker import BrokerSafetyError
from wallex_bot.atlas_spot_exchange import SpotLedger,RealSpotBroker
from wallex_bot.atlas_spot_runtime import _NetworkPermit,_PERMIT_SECRET


def test_missing_key_discovery_performs_no_network_or_file_write(tmp_path,monkeypatch):
    import requests
    monkeypatch.delenv('WALLEX_API_KEY',raising=False)
    monkeypatch.setattr(requests,'get',lambda *a,**k:pytest.fail('Network forbidden'))
    p=discover(tmp_path)
    assert p['status']=='BLOCKED_KEY_UNSET' and p['requests']==0
    assert p['trade_permission'].startswith('UNVERIFIED') and p['orders_sent']==0
    assert list(tmp_path.iterdir())==[]


@pytest.mark.parametrize('path',['/v1/account/orders','/withdrawal','https://other.invalid','/v1/prop/packages/../orders'])
def test_discovery_has_only_read_allowlist(tmp_path,path):
    with pytest.raises(ValueError,match='READ_PATH_NOT_ALLOWED'):AccountReader(tmp_path).get(path)


def test_account_schema_does_not_guess_or_use_titles():
    control={'clientId':'control_identity_only','type':'prop'}
    assert object_rows(control,'clientId')==[control]
    assert object_rows([control],'clientId')==[control]
    with pytest.raises(ValueError):object_rows({'title':'arbitrary untrusted title'},'clientId')
    p=public_summary({'account_client_id':control['clientId'],'subaccounts':[control],'matching_history':[]})
    assert 'account_client_id' not in p and 'subaccounts' not in p
    assert p['account_id_observed'] is True


def test_one_shot_capability_bound_to_account_and_exact_control_request(monkeypatch):
    calls=[];owner=SimpleNamespace(api=SimpleNamespace(client_id='control_account_a'),_permit=lambda a:calls.append(a))
    permit=_NetworkPermit(owner,'BUY','POST',None,{'control':'metadata_only'},_PERMIT_SECRET)
    with pytest.raises(BrokerSafetyError,match='ACCOUNT_MISMATCH'):
        permit.validate('POST',None,{'control':'metadata_only'},'control_account_b')
    with pytest.raises(BrokerSafetyError,match='REQUEST_CHANGED'):
        permit.validate('POST',None,{'control':'different_metadata'},'control_account_a')
    permit.validate('POST',None,{'control':'metadata_only'},'control_account_a')
    assert calls==['BUY']
    with pytest.raises(BrokerSafetyError,match='USED'):
        permit.validate('POST',None,{'control':'metadata_only'},'control_account_a')


def test_expired_capability_cannot_reach_owner(monkeypatch):
    import wallex_bot.atlas_spot_runtime as m
    clock=[0.];monkeypatch.setattr(m.time,'monotonic',lambda:clock[0])
    owner=SimpleNamespace(api=SimpleNamespace(client_id='control_account'),_permit=lambda _:pytest.fail('Expired permit'))
    permit=_NetworkPermit(owner,'CANCEL','DELETE','control_order',None,_PERMIT_SECRET)
    clock[0]=3.
    with pytest.raises(BrokerSafetyError,match='EXPIRED'):permit.validate('DELETE','control_order',None,'control_account')


def test_acknowledged_is_unknown_on_restart_and_identity_tamper_fails(tmp_path):
    ledger=SpotLedger(tmp_path);p={'client_id':'control_identity','symbol':'BTCTMN','side':'BUY'}
    ledger.register(p)
    with ledger.db:ledger._state(p['client_id'],'ACKNOWLEDGED','CONTROL_ACK_NOT_A_FILL')
    ledger.close();ledger=SpotLedger(tmp_path)
    assert ledger.status(p['client_id'])['state']=='UNKNOWN'
    with ledger.db:ledger.db.execute('UPDATE spot_orders SET side=?',('SELL',))
    with pytest.raises(BrokerSafetyError,match='IDENTITY_COLUMNS'):ledger._require_integrity()
    ledger.close()


def test_operator_factory_does_not_arm_and_halt_survives_clock_rollback(tmp_path,monkeypatch):
    from wallex_bot import atlas_spot_runtime as m
    from wallex_bot.atlas_deadline import DEADLINE
    folder=tmp_path/'operations';folder.mkdir();approval=folder/'control.json'
    approval.write_text(json.dumps({'account_client_id':'control_identity_only'}))
    monkeypatch.setattr(m.time,'time',lambda:DEADLINE.timestamp()+1)
    broker=RealSpotBroker.with_operator_evidence(tmp_path,approval,tmp_path/'research_challengers/control')
    assert broker.arm_state is None
    with pytest.raises(BrokerSafetyError,match='HALTED_LATCHED'):broker._permit('BUY')
    broker.close()
    monkeypatch.setattr(m.time,'time',lambda:DEADLINE.timestamp()-3600)
    broker=RealSpotBroker.with_operator_evidence(tmp_path,approval,tmp_path/'research_challengers/control')
    try:
        for action in ('BUY','SELL','CANCEL'):
            with pytest.raises(BrokerSafetyError,match='HALTED_LATCHED'):broker._permit(action)
        with pytest.raises(BrokerSafetyError,match='HALTED_LATCHED'):
            broker.arm_interactive(input_fn=lambda _:pytest.fail('Must not ask for ARM after halt'))
    finally:broker.close()


def test_any_changed_authorization_disarms_without_financial_inputs(tmp_path,monkeypatch):
    import os,time
    operations=tmp_path/'operations';operations.mkdir()
    file=operations/'control.json';file.write_text(json.dumps({'account_client_id':'control_identity'}))
    broker=RealSpotBroker.with_operator_evidence(tmp_path,file,tmp_path/'research_challengers/control')
    try:
        # Nonfinancial process identity only; this does NOT satisfy proofs/ARM.
        broker.arm_state={'pid':os.getpid(),'monotonic_deadline':time.monotonic()+1,'key_sha':'not_a_key_hash'}
        file.write_text(json.dumps({'account_client_id':'control_identity','changed':True}))
        with pytest.raises(BrokerSafetyError,match='AUTHORIZATION_CHANGED'):broker._permit('BUY')
        assert broker.arm_state is None
    finally:broker.close()


def test_new_forecast_registration_explicitly_passes_frozen_fee():
    # AST contract, not fabricated forecasts or market observations.
    import ast
    tree=ast.parse(Path('wallex_bot/atlas_study.py').read_text(encoding='utf-8'))
    calls=[n for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and n.func.attr=='register']
    assert calls and all(any(k.arg=='fee' and 'fee_per_side_assumed' in ast.unparse(k.value) for k in c.keywords) for c in calls)


def test_missing_balance_context_never_proves_key_identity():
    from wallex_bot.atlas_account_discovery import compare_balance_contexts
    r=compare_balance_contexts(None,None)
    assert r['api_key_matches_sub_account'] is None and not r['trade_authorized']


def test_actual_recorded_context_comparison_is_not_trade_authorization():
    from wallex_bot.atlas_account_discovery import compare_balance_contexts
    root=Path('atlas_store');pointer=root/'operations/account_discovery_latest.json'
    ordinary=root/'operations/private_account_read.json'
    if not pointer.exists() or not ordinary.exists():pytest.skip('Actual account receipts absent')
    scoped=json.loads(Path(json.loads(pointer.read_text())['result']).read_text())['account_scoped_tmn']
    p=json.loads(ordinary.read_text())
    default={'available':p['tmn_available'],'total':p['tmn_total'],'frozen':p['tmn_frozen']}
    result=compare_balance_contexts(default,scoped)
    assert result['api_key_matches_sub_account'] is None and not result['trade_authorized']
    assert result['comparison_is_not_atomic'] is True


def test_private_get_header_contract_replays_real_body_only(tmp_path,monkeypatch):
    import requests
    root=Path('atlas_store');pointer=root/'operations/account_discovery_latest.json'
    if not pointer.exists():pytest.skip('Actual private receipt absent; no fake balance response')
    folder=Path(json.loads(pointer.read_text())['result']).parent
    record=next((r for r in folder.glob('*.receipt') if json.loads(r.read_text())['path']=='/v1/account/balances-detail'),None)
    if record is None:pytest.skip('Actual balance receipt absent')
    raw=record.with_suffix('').read_bytes();calls=[]
    # Replay actual bytes to test HEADER SELECTION only, not live ownership.
    monkeypatch.setenv('WALLEX_API_KEY','noncredential_transport_control')
    def get(url,**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(status_code=200,content=raw,json=lambda **_:json.loads(raw))
    monkeypatch.setattr(requests,'get',get)
    reader=AccountReader(tmp_path)
    reader.get('/v1/account/balances-detail')
    reader.get('/v1/account/balances-detail',account='control_account_identity')
    assert 'sub-account-client-id' not in calls[0]['headers']
    assert calls[1]['headers']['sub-account-client-id']=='control_account_identity'
    assert all(c['allow_redirects'] is False for c in calls)
    assert all(b'noncredential_transport_control' not in p.read_bytes() for p in tmp_path.iterdir())
