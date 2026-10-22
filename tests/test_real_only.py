"""Never invent market observations or API payloads.

Offline safety tests require no market data. Optional integration tests read ONLY
an actual Wallex CSV and its untouched provenance manifest from the user.
"""
import os
from pathlib import Path
import pytest
from wallex_bot.cli import main, load_verified_recent_csv
from wallex_bot.market import ALLOWED_RESOLUTIONS


def test_fixture_generation_command_not_available(capsys):
    with pytest.raises(SystemExit) as exc:
        main(['make-fixture'])
    assert exc.value.code == 2


def test_unverified_data_is_blocked(tmp_path):
    with pytest.raises(RuntimeError, match='provenance'):
        load_verified_recent_csv(tmp_path / 'unknown.csv','BTCTMN','15')


def test_stale_download_sizes_rejected_before_network(tmp_path):
    with pytest.raises(ValueError, match='5..14'):
        main(['fetch-history','--symbol','BTCTMN','--days','60',
              '--output',str(tmp_path / 'blocked.csv')])


def test_data_frequency_mapping():
    # API time intervals, not fabricated price observations
    assert ALLOWED_RESOLUTIONS['15'] == 15 * 60
    assert ALLOWED_RESOLUTIONS['60'] == 60 * 60


def test_real_wallex_csv_integrity_if_supplied():
    path=os.environ.get('WALLEX_REAL_CSV')
    if not path:
        pytest.skip('Supply WALLEX_REAL_CSV pointing to real downloaded Wallex CSV+provenance')
    symbol=os.environ.get('WALLEX_REAL_SYMBOL','BTCTMN')
    resolution=os.environ.get('WALLEX_REAL_RESOLUTION','15')
    frame, proof=load_verified_recent_csv(path,symbol,resolution)
    assert len(frame) >= 330
    assert proof['source'] == 'wallex_public_api'


def test_no_genuine_integration_data_not_misreported_as_success():
    path=os.environ.get('WALLEX_REAL_CSV')
    if not path:
        pytest.skip('Live Wallex integration requires user-provided real dataset')
    assert Path(path).is_file()
    assert Path(path+'.provenance.json').is_file()
