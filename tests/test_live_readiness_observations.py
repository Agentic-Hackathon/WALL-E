"""Read-only readiness uses actual local receipts, never invented market data."""
import json
from pathlib import Path
import pytest
from wallex_bot.atlas_live_readiness import discovery_readiness,private_check


def test_missing_key_no_network_no_persistence(tmp_path,monkeypatch):
    import requests
    monkeypatch.delenv('WALLEX_API_KEY',raising=False)
    monkeypatch.setattr(requests,'get',lambda *a,**k:pytest.fail('No private request without key'))
    p=private_check(tmp_path,183)
    assert not p['private_read_performed'] and p['connection']=='READ_NOT_CONFIRMED'
    assert p['LIVE']=='HARD_DISABLED' and not p['automatic_arm_or_order']
    assert list(tmp_path.iterdir())==[]


def test_read_failure_does_not_reuse_previous_success():
    p=discovery_readiness({'requests':0,'errors':[]})
    assert p['observed_account_tmn'] is None and not p['observed_selected_fees']
    assert p['checks']['verified_fee']=='BLOCKED_MISSING_VERIFIED_EVIDENCE'


def test_actual_account_read_is_not_arming_or_scope_proof():
    pointer=Path('atlas_store/operations/account_discovery_latest.json')
    if not pointer.exists():pytest.skip('No actual private receipt')
    actual=json.loads(Path(json.loads(pointer.read_text())['result']).read_text())
    p=discovery_readiness(actual)
    assert p['LIVE']=='HARD_DISABLED' and not p['operator_arm_available']
    assert p['orders_sent']==0 and not p['automatic_arm_or_order']
    assert p['contest_balance_verified'] is False
    assert 'account_client_id' not in p and 'subaccounts' not in p
    if actual.get('account_scoped_fees',{}).get('BTCTMN'):
        assert p['checks']['verified_fee'].startswith('OBSERVED_')
        assert p['observed_selected_fees']['BTCTMN']==actual['account_scoped_fees']['BTCTMN']
    assert 'FINANCIAL_QUALIFICATION' in p['execution_blockers']
