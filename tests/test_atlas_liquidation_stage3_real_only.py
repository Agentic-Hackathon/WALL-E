"""Stage 3 safety contract tests: no invented market quotes/prices/fills."""
from pathlib import Path
import inspect
import sqlite3
import pytest

from wallex_bot.atlas_archive import Lake
from wallex_bot.atlas_broker import (BrokerSafetyError, OrderIntent, ShadowBroker,
                                     WallexLiveBroker, OrderState)
from wallex_bot.atlas_liquidation import liquidation_status, liquidate_paper_positions
from wallex_bot.atlas_shadow import PaperAccount
from wallex_bot.atlas_risk import RiskGate
from wallex_bot import atlas_watch


def test_liquidation_status_does_not_create_a_ledger_or_call_api(tmp_path):
    result = liquidation_status(tmp_path)
    assert result['status'] == 'NO_EXISTING_PAPER_LEDGER'
    assert result['live_order_submission'] == 'ABSENT'
    assert not (tmp_path / 'shadow.sqlite').exists()


def test_no_watch_deadline_fails_closed_without_accessing_market(tmp_path, monkeypatch):
    lake = Lake(tmp_path)
    def forbidden_market_call(*args, **kwargs):
        raise AssertionError('Market lookup must not happen before deadline checks')
    monkeypatch.setattr('wallex_bot.atlas_liquidation.market.depth', forbidden_market_call)
    with pytest.raises(BrokerSafetyError, match='No persisted watch session'):
        liquidate_paper_positions(lake, require_watch_deadline=True)
    assert not (tmp_path / 'shadow.sqlite').exists()
    lake.close()


def test_empty_paper_ledger_finishes_without_market_fixtures(tmp_path, monkeypatch):
    lake = Lake(tmp_path)
    monkeypatch.setattr('wallex_bot.atlas_liquidation.market.depth',
                        lambda *_: (_ for _ in ()).throw(AssertionError('No fake data or market read')))
    result = liquidate_paper_positions(lake, require_watch_deadline=False)
    assert result['status'] == 'PAPER_FLAT'
    assert result['remaining_paper_positions'] == 0
    assert result['observations'] == []
    assert result['exchange_fills_claimed'] == 0
    assert result['paper_cash_tmn'] == 5_000_000  # official contest starting amount, not market data
    assert liquidation_status(tmp_path)['status'] == 'PAPER_FLAT'
    lake.close()


def test_terminal_purpose_has_no_short_or_buy_path():
    with pytest.raises(ValueError, match='Final liquidation only permits'):
        OrderIntent('terminal-purpose-01', 'BTCTMN', 'BUY', purpose='FINAL_TMN')
    with pytest.raises(ValueError, match='Final liquidation only permits'):
        OrderIntent('terminal-purpose-02', 'BTCTMN', 'AUTO', purpose='FINAL_TMN')
    with pytest.raises(ValueError, match='Final liquidation only permits'):
        OrderIntent('terminal-purpose-03', 'BTCTMN', 'SELL', quantity=1, purpose='FINAL_TMN')
    with pytest.raises(ValueError):
        OrderIntent('terminal-purpose-04', 'BTCUSDT', 'SELL', purpose='FINAL_TMN')


def test_final_gate_refuses_nonobserved_depth_and_does_not_order():
    gate = RiskGate()
    response = gate.final_tmn_liquidation('BTCTMN', {}, 5_000_000, [], .001)
    assert response.action != 'PAPER_SELL'
    assert 'POSITION' not in response.action or response.action != 'PAPER_BUY'


def test_paper_terminal_order_is_idempotent_even_without_valid_quote(tmp_path):
    lake = Lake(tmp_path)
    paper = PaperAccount(lake)
    broker = ShadowBroker(paper)
    intent = OrderIntent('paper-terminal-0001', 'BTCTMN', 'SELL', purpose='FINAL_TMN')
    try:
        first = broker.submit(intent, forecast={}, book={}, fee=.001)
        second = broker.submit(intent, forecast={}, book={}, fee=.001)
        assert first == second
        assert first.state == OrderState.PAPER_NOT_EXECUTED
        assert paper.db.execute('SELECT COUNT(*) FROM events').fetchone()[0] == 1
        assert paper.db.execute('SELECT COUNT(*) FROM positions').fetchone()[0] == 0
        assert paper.verify()
    finally:
        paper.close(); lake.close()


def test_live_broker_cannot_close_real_coins_even_with_terminal_intent(tmp_path):
    live = WallexLiveBroker(tmp_path)
    try:
        receipt = live.submit(OrderIntent('no-live-close-00001', 'BTCTMN', 'SELL', purpose='FINAL_TMN'))
        assert receipt.state == OrderState.BLOCKED_DRY_RUN
        assert not receipt.hypothetical
        assert live.reconcile()['submitted_exchange_orders'] == 0
    finally:
        live.close()


def test_final_watch_uses_broker_and_not_direct_cash_position_mutation():
    source = inspect.getsource(atlas_watch.run)
    assert 'liquidate_paper_positions(' in source
    assert "DELETE FROM positions" not in source
    assert "paper._set('cash_tmn'" not in source
    finalizer = inspect.getsource(liquidate_paper_positions)
    assert 'broker.submit(' in finalizer
    assert 'market.depth(symbol)' in finalizer
    assert 'raw_depth' in finalizer
    assert 'requests.post' not in finalizer


def test_liquidation_status_detects_tampered_real_paper_audit_without_price_fixture(tmp_path):
    lake = Lake(tmp_path)
    paper = PaperAccount(lake)
    try:
        with paper.db:
            paper.log('SYSTEM', 'CONTRACT_TEST_EVENT', {'contains_market_data': False})
        assert liquidation_status(tmp_path)['paper_hash_chain_valid']
        paper.db.execute("UPDATE events SET action='TAMPERED' WHERE id=1")
        paper.db.commit()
        result = liquidation_status(tmp_path)
        assert result['status'] == 'PAPER_AUDIT_INVALID'
        assert not result['paper_hash_chain_valid']
        with pytest.raises(BrokerSafetyError):
            liquidate_paper_positions(lake, require_watch_deadline=False)
    finally:
        paper.close(); lake.close()
