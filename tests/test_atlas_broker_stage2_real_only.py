"""Broker safety contracts: NO mocked prices, invented candles or pretend fills."""
from dataclasses import FrozenInstanceError
import inspect
import json
from pathlib import Path
import sqlite3
import pytest

from wallex_bot.atlas_archive import Lake
from wallex_bot.atlas_shadow import PaperAccount
from wallex_bot.atlas_broker import (
    BrokerSafetyError, IdempotencyConflict, OrderIntent, OrderState,
    ShadowBroker, WallexLiveBroker, allowed_transition, broker_status,
)


def test_live_broker_is_non_executing_even_with_explicit_enable(tmp_path, monkeypatch):
    monkeypatch.setenv('WALLEX_API_KEY', 'NEVER_USED_BY_BROKER')
    with pytest.raises(BrokerSafetyError, match='NOT IMPLEMENTED'):
        WallexLiveBroker(tmp_path, live_enabled=True)
    source = inspect.getsource(WallexLiveBroker)
    assert 'requests.post' not in source
    assert 'WALLEX_API_KEY' not in source
    assert 'subprocess' not in source
    assert 'fetch(' not in source
    assert broker_status(tmp_path)['broker_control_database_exists'] is False


def test_live_dry_run_is_durable_idempotent_and_never_a_fill(tmp_path):
    intent = OrderIntent('distinct-client-order-001', 'BTCTMN', 'BUY')
    broker = WallexLiveBroker(tmp_path)
    try:
        first = broker.submit(intent)
        same = broker.submit(intent)
        assert first == same
        assert first.state == OrderState.BLOCKED_DRY_RUN
        assert first.exchange_order_id is None
        assert first.hypothetical is False
        assert broker.verify()
        assert broker.reconcile()['order_state_counts'] == {'BLOCKED_DRY_RUN': 1}
        assert broker.db.execute('SELECT COUNT(*) FROM broker_events').fetchone()[0] == 1
        with pytest.raises(IdempotencyConflict):
            broker.submit(OrderIntent(intent.client_order_id, 'ETHTMN', 'BUY'))
        assert broker.db.execute('SELECT COUNT(*) FROM broker_events').fetchone()[0] == 1
    finally:
        broker.close()
    resumed = WallexLiveBroker(tmp_path)
    try:
        assert resumed.status(intent.client_order_id) == first
        assert resumed.reconcile()['submitted_exchange_orders'] == 0
        assert resumed.cancel(intent.client_order_id).state == OrderState.BLOCKED_DRY_RUN
        assert resumed.balances()['balances'] is None
    finally:
        resumed.close()


def test_kill_switch_is_persistent_and_audit_detects_tampering(tmp_path):
    broker = WallexLiveBroker(tmp_path)
    try:
        assert broker.kill()['kill_switch'] == 'ENGAGED'
        with pytest.raises(ValueError):
            broker.kill('include arbitrary user text / injection')
        assert broker.verify()
        broker.db.execute('UPDATE broker_events SET payload_json=? WHERE id=1',
                          ('{"corrupted":true}',))
        broker.db.commit()
        assert broker.verify() is False
        with pytest.raises(BrokerSafetyError, match='corrupted'):
            broker.submit(OrderIntent('another-client-order-002', 'BTCTMN', 'SELL'))
    finally:
        broker.close()


def test_order_states_do_not_turn_unknown_into_retry_permission():
    assert allowed_transition(OrderState.NEW, OrderState.OPEN)
    assert allowed_transition(OrderState.PARTIAL, OrderState.FILLED)
    assert allowed_transition(OrderState.NEW, OrderState.UNKNOWN)
    assert not allowed_transition(OrderState.FILLED, OrderState.NEW)
    assert not allowed_transition(OrderState.BLOCKED_DRY_RUN, OrderState.FILLED)
    assert not allowed_transition(OrderState.UNKNOWN, OrderState.BLOCKED_DRY_RUN)
    with pytest.raises(ValueError):
        OrderIntent('not-valid-and-unique', 'BTCUSDT', 'BUY')
    with pytest.raises(ValueError):
        OrderIntent('not-valid-and-unique', 'BTCTMN', 'SHORT')


def test_shadow_broker_uses_existing_gate_and_atomic_idempotency_without_market_data(tmp_path):
    lake = Lake(tmp_path)
    paper = PaperAccount(lake)
    broker = ShadowBroker(paper)
    try:
        # An EMPTY observed book fails closed; no fake prices/fills or invented trades.
        intent = OrderIntent('shadow-request-0000001', 'BTCTMN', 'AUTO')
        first = broker.submit(intent, forecast={}, book={}, fee=.001)
        assert first.state == OrderState.PAPER_NOT_EXECUTED
        assert first.reason == 'REJECTED'
        cash_before = broker.balances()['cash_tmn']
        second = broker.submit(intent, forecast={}, book={}, fee=.001)
        assert second == first
        assert broker.balances()['cash_tmn'] == cash_before
        assert paper.db.execute('SELECT COUNT(*) FROM events').fetchone()[0] == 1
        assert paper.verify()
        assert broker.status(intent.client_order_id) == first
        assert broker.reconcile()['intent_count'] == 1
        with pytest.raises(ValueError, match='Idempotency conflict'):
            broker.submit(intent, forecast={'different_nonprice_evidence': True}, book={}, fee=.001)
        assert paper.verify()
        assert paper.db.execute('SELECT COUNT(*) FROM events').fetchone()[0] == 1
    finally:
        paper.close()
        lake.close()


def test_shadow_receipts_are_not_real_exchange_order_states(tmp_path):
    lake = Lake(tmp_path)
    paper = PaperAccount(lake)
    try:
        assert paper.db.execute('SELECT count(*) FROM broker_intents').fetchone()[0] == 0
        assert 'broker_intents' in inspect.getsource(PaperAccount)
        assert 'self.risk.evaluate(' in inspect.getsource(PaperAccount)
    finally:
        paper.close(); lake.close()
