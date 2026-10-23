"""Structural/status-only checks. No invented market candles, prices or fills."""
import json
from datetime import datetime, timezone
import pytest
from wallex_bot.atlas_broker import OrderIntent, BrokerSafetyError
from wallex_bot.atlas_spot_exchange import RealSpotBroker, SpotReadTransport, SpotLedger, decimal, STATES, MODES
from wallex_bot.atlas_deadline_supervisor import DeadlineSupervisor


@pytest.mark.parametrize('value', [float('nan'), float('inf'), True, 'NaN', 'Infinity', '-1', '0', None])
def test_decimal_rejects_nonfinite_float_and_nonpositive(value):
    with pytest.raises(ValueError):
        decimal(value)


def test_decimal_is_exact_arithmetic_not_a_market_observation():
    assert str(decimal('0.1')+decimal('0.2')) == '0.3'


def test_all_requested_states_and_modes_exist():
    assert {'CREATED','CANCEL_PENDING','UNKNOWN','PARTIALLY_FILLED','FILLED','CANCELLED'} <= set(STATES)
    assert {'LIVE_ARMED','HALTED','BLOCKED','EXIT_ONLY'} <= set(MODES)


def test_no_key_no_private_network(monkeypatch):
    monkeypatch.delenv('WALLEX_API_KEY', raising=False)
    import requests
    monkeypatch.setattr(requests, 'get', lambda *a, **k: pytest.fail('Network must not be called'))
    with pytest.raises(BrokerSafetyError, match='UNSET'):
        SpotReadTransport().read('balances')
    with pytest.raises(BrokerSafetyError, match='ENDPOINT'):
        SpotReadTransport().read('withdrawal')


def test_no_order_or_cancel_even_with_environment_key(tmp_path, monkeypatch):
    # Deliberately noncredential control string; never sent anywhere.
    monkeypatch.setenv('WALLEX_API_KEY', 'noncredential_control_value')
    broker = RealSpotBroker(tmp_path)
    try:
        assert broker.mode == 'BLOCKED'
        for side in ('BUY', 'SELL'):
            with pytest.raises(BrokerSafetyError, match='HARD_DISABLED'):
                broker.submit(OrderIntent('control_order_1', 'BTCTMN', side))
        with pytest.raises(BrokerSafetyError, match='NOT_AUTHORIZED'):
            broker.cancel('control_order_1')
        assert broker.ledger.db.execute('SELECT COUNT(*) FROM spot_orders').fetchone()[0] == 0
    finally:
        broker.close()


def test_no_response_no_fill_or_fee(tmp_path):
    ledger = SpotLedger(tmp_path)
    try:
        with pytest.raises(BrokerSafetyError, match='UNVERIFIED'):
            ledger.observe('control_order_id', {'success': False})
        assert ledger.status('control_order_id') is None
    finally:
        ledger.close()


def test_halted_survives_restart_clock_rollback_and_browser_absence(tmp_path, monkeypatch):
    import wallex_bot.atlas_deadline_supervisor as module
    after = datetime(2026, 10, 24, tzinfo=timezone.utc).timestamp()
    monkeypatch.setattr(module.time, 'time', lambda: after)
    s = DeadlineSupervisor(tmp_path)
    assert s.tick({})['halted_latched']
    s.close()
    monkeypatch.setattr(module.time, 'time', lambda: after-86400)
    s = DeadlineSupervisor(tmp_path)
    try:
        state = s.tick({})
        assert state['phase'] == 'HALTED' and not state['allow_new_entry']
        assert state['orders_sent'] == 0 and state['real_residual'] == 'UNKNOWN'
    finally:
        s.close()


def test_network_failure_never_invents_settlement(tmp_path, monkeypatch):
    monkeypatch.setattr(SpotReadTransport, 'read', lambda *a: (_ for _ in ()).throw(BrokerSafetyError('NETWORK')))
    s = DeadlineSupervisor(tmp_path)
    try:
        state = s.tick({}, private_read=True)
        assert state['real_residual'] == 'UNKNOWN_NO_RETRY'
        assert not state['settlement_guaranteed'] and not state['allow_new_entry']
        assert not (tmp_path/'operations/supervisor_private_snapshot.json').exists()
    finally:
        s.close()
