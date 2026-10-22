"""Safety-only tests; NO synthetic/mock market prices, orders or articles."""
import pytest
from wallex_bot import market
from wallex_bot.atlas_archive import Lake
from wallex_bot.atlas_deep import sequences, trusted_checkpoints
from wallex_bot.atlas_news import _rss_date


def test_reject_invalid_symbol_before_any_network():
    with pytest.raises(ValueError):
        market.candles_sparse('BTC-TMN', '1', 0, 1)


def test_reject_invalid_interval_before_any_network():
    with pytest.raises(ValueError):
        market.candles_sparse('BTCTMN', 'NOT_REAL', 0, 1)


def test_empty_real_archive_fails_closed(tmp_path):
    lake=Lake(tmp_path)
    try:
        with pytest.raises(RuntimeError, match='No usable continuous genuine'):
            sequences(lake)
    finally:
        lake.close()


def test_empty_checkpoint_directory_not_considered_model(tmp_path):
    assert trusted_checkpoints(tmp_path)==[]


def test_invalid_rss_date_is_not_synthesized():
    assert _rss_date('UNKNOWN') is None
