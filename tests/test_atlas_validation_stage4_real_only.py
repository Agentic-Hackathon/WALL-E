"""Contract tests only: no simulated market quotes, prices, candles or fills."""
import inspect
import json
from pathlib import Path

import pytest

from wallex_bot.atlas_validation import validate_archive, deflated_sharpe, pbo_cscv, store_report
from wallex_bot.atlas_archive import Lake
from wallex_bot.atlas_liquidation import liquidate_paper_positions
from wallex_bot.atlas_broker import BrokerSafetyError


def test_empty_real_archive_fails_closed(tmp_path):
    lake=Lake(tmp_path/'real_archive_empty')
    try:
        result=validate_archive(lake)
        assert result['status']=='INSUFFICIENT_EVIDENCE_NO_CONTIGUOUS_GENUINE_HISTORY'
        assert result['symbols']==[]
        assert result['fee_verified_with_exchange'] is False
        assert result['real_order_submission'] is False
        assert result['nominal_selected_trial_count'] is None
        assert 'NOT_SUPPORTED' in result['champion_backtest']
        file=store_report(lake,result)
        assert json.loads(file.read_text(encoding='utf8'))['status']==result['status']
    finally:lake.close()


def test_invalid_fees_denied_without_market_data(tmp_path):
    lake=Lake(tmp_path/'empty')
    try:
        for fee,slip in [(-.01,0),(.001,-.5),(float('nan'),0),(.001,float('inf')),(True,0)]:
            with pytest.raises(ValueError):validate_archive(lake,fee=fee,slippage=slip)
        with pytest.raises(ValueError):validate_archive(lake,resolution='1D')
        with pytest.raises(ValueError):validate_archive(lake,max_symbols=0)
    finally:lake.close()


def test_statistical_tests_abstain_without_real_return_series():
    assert deflated_sharpe([],[],None)['status']=='INSUFFICIENT_EVIDENCE'
    assert pbo_cscv([])['status']=='INSUFFICIENT_EVIDENCE'


def test_stage4_does_not_contain_order_route():
    import wallex_bot.atlas_validation as v
    code=inspect.getsource(v)
    assert 'WALLEX_API_KEY' not in code
    assert 'createorder' not in code.lower()
    assert 'market.depth' not in code


def test_early_liquidation_reports_already_flat_without_market_api(tmp_path,monkeypatch):
    from wallex_bot.atlas_shadow import PaperAccount
    lake=Lake(tmp_path/'empty_paper')
    try:
        paper=PaperAccount(lake)
        assert paper.verify()
        paper.close()
        # An existing persisted watch session was observed, not fabricated market data.
        (lake.root/'watch_session.json').write_text('{"started_epoch": 1, "deadline_epoch": 2, "hours": 48}')
        import wallex_bot.market as market
        def forbidden(*a,**kw):
            raise AssertionError('No market API request for an already-flat paper portfolio')
        monkeypatch.setattr(market,'depth',forbidden)
        report=liquidate_paper_positions(lake,require_watch_deadline=True)
        assert report['status']=='ALREADY_FLAT'
        assert report['remaining_paper_positions']==0
        assert report['exchange_orders_submitted']==0
    finally:lake.close()


def test_report_uses_held_out_and_no_promote_path():
    import wallex_bot.atlas_validation as v
    code=inspect.getsource(v.validate_archive)
    assert "'holdout'" in code
    assert 'promote_champion' not in code
    assert 'PaperAccount' not in code
