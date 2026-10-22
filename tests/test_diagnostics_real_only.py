"""No market observations or fake API responses in these tests."""
import os
from pathlib import Path
import pytest
from wallex_bot.cli import main
from wallex_bot.diagnostics import analyze


def test_cli_exposes_evidence_only_diagnostics(capsys):
    with pytest.raises(SystemExit) as error:
        main(['diagnose-run','--help'])
    assert error.value.code == 0
    assert '--run' in capsys.readouterr().out


def test_missing_real_run_fails(tmp_path):
    with pytest.raises(FileNotFoundError, match='manifest'):
        analyze(tmp_path/'missing_genuine_audit')


def test_real_integration_when_user_supplies_actual_run():
    path=os.environ.get('WALLEX_REAL_RUN')
    if not path:
        pytest.skip('Set WALLEX_REAL_RUN to an authentic, archived Wallex segment-eval run to exercise numeric diagnostics')
    assert Path(path,'manifest.json').is_file()
    report=analyze(path)
    assert report['audit_hash_chain_valid']
    assert report['decision_count'] > 0
    assert report['forecast_skill_on_observed_real_future']['scored_predictions'] > 0
