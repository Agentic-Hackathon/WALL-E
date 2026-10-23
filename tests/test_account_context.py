"""Account routing diagnostics: actual local receipts, no invented balances."""
import json
from pathlib import Path
from types import SimpleNamespace
import pytest
from wallex_bot.atlas_account_discovery import compare_balance_contexts,AccountReader


def test_absent_context_never_proves_identity():
    p=compare_balance_contexts(None,None)
    assert p['api_key_matches_sub_account'] is None and not p['trade_authorized']


def test_real_recorded_comparison_does_not_authorize_trade():
    root=Path('atlas_store');pointer=root/'operations/account_discovery_latest.json'
    ordinary=root/'operations/private_account_read.json'
    if not pointer.exists() or not ordinary.exists():pytest.skip('Actual account receipts absent')
    scoped=json.loads(Path(json.loads(pointer.read_text())['result']).read_text())['account_scoped_tmn']
    p=json.loads(ordinary.read_text())
    default={'available':p['tmn_available'],'total':p['tmn_total'],'frozen':p['tmn_frozen']}
    result=compare_balance_contexts(default,scoped)
    assert result['api_key_matches_sub_account'] is None and not result['trade_authorized']
    assert result['comparison_is_not_atomic'] is True


def test_headers_using_actual_response_bytes(tmp_path,monkeypatch):
    import requests
    pointer=Path('atlas_store/operations/account_discovery_latest.json')
    if not pointer.exists():pytest.skip('Actual private receipt absent')
    folder=Path(json.loads(pointer.read_text())['result']).parent
    record=next((r for r in folder.glob('*.receipt') if json.loads(r.read_text())['path']=='/v1/account/balances-detail'),None)
    if record is None:pytest.skip('Actual balance receipt absent; no substitute')
    raw=record.with_suffix('').read_bytes();calls=[]
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
