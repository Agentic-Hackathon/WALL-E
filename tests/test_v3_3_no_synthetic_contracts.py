"""Structural/empty-state tests ONLY: no fake market prices, fixtures or orders."""
import ast
import inspect
from pathlib import Path
from wallex_bot.atlas_forward import ForwardLedger, report
from wallex_bot import atlas_forward, atlas_readiness


def test_clean_forward_ledger_is_no_evidence(tmp_path):
    result=report(tmp_path)
    assert result['quote_receipts']==0
    assert result['scored']==0
    assert result['receipt_hashes_valid']
    assert result['mode']=='PROSPECTIVE_REAL_QUOTES_NO_TRADES'


def test_forecast_must_have_real_quote_receipt():
    # Inspect actual production code; no fabricated prices or forecasts in tests.
    src=inspect.getsource(ForwardLedger.record_forecast)
    assert 'origin_quote_id' in src
    assert 'Forecast cannot exist without its actual Wallex quote' in src
    assert 'SELECT observed_epoch,symbol FROM quotes' in src


def test_forward_module_has_no_market_mock_or_order_submit():
    src=inspect.getsource(atlas_forward)
    assert 'market.depth(' not in src
    assert 'submit_order' not in src
    assert 'numpy.random' not in src
    assert 'random.normal' not in src


def test_readiness_never_claims_live_trade_enabled():
    src=inspect.getsource(atlas_readiness)
    assert "'trade_execution_enabled':False" in src
    assert 'NO_CONFIRMED_REALIZED_TMN_CONTEST_PNL' in src
    assert 'model_uses_news_features' in src


def test_shadow_records_own_model_and_actual_depth():
    src=Path(inspect.getfile(atlas_forward)).with_name('atlas_shadow.py').read_text(encoding='utf8')
    assert 'observer.record_real_quote(symbol,raw,measured' in src
    assert 'observer.record_forecast(' in src
    assert 'model_digest=hashlib.sha256' in src
