"""Contract tests only. No fabricated exchange prices, books, or server replies."""
from pathlib import Path
import os
import pytest

from wallex_bot.cli import main
from wallex_bot.live_scout import report_scout
from wallex_bot.wallex_api import read_organizer_allowlist


def test_scout_command_is_explicitly_read_only_and_rejects_missing_required_fields(capsys):
    for command in ('live-scout','live-scout-report'):
        with pytest.raises(SystemExit) as exc:
            main([command, '--help'])
        assert exc.value.code == 0
        help_text = capsys.readouterr().out
        assert '--audit' in help_text
        assert 'orders' not in help_text.lower()


def test_unproven_list_cannot_enable_organizer_market():
    # The repository's intentionally EMPTY organizer list cannot authorize trading.
    with pytest.raises(ValueError, match='Organizer allowlist'):
        read_organizer_allowlist(Path(__file__).resolve().parents[1]/'examples'/'organizer_allowlist_FILL_ME.json')


def test_report_refuses_to_invent_or_load_missing_exchange_history(tmp_path):
    with pytest.raises(FileNotFoundError):
        report_scout(tmp_path/'no_genuine_orderbook.sqlite')
    assert not list(tmp_path.iterdir())


def test_live_exchange_integration_only_if_user_opted_in():
    """Needs actual Wallex API and real organizer/package IDs; never a price mock."""
    if os.environ.get('WALLEX_SCOUT_LIVE_INTEGRATION') != 'YES':
        pytest.skip('Real API integration requires explicit opt-in and organizer market allowlist')
    from wallex_bot.live_scout import capture_once
    symbol = os.environ['WALLEX_SCOUT_SYMBOL']
    package = int(os.environ['WALLEX_SCOUT_PACKAGE_ID'])
    organizer = os.environ['WALLEX_SCOUT_ALLOWLIST']
    audit = os.environ['WALLEX_SCOUT_AUDIT']
    fee = float(os.environ['WALLEX_SCOUT_FEE'])
    report = capture_once([symbol],organizer,package,audit,250000,fee)
    assert report['trade_execution_enabled'] is False
    assert report['records'][0]['symbol'] == symbol
