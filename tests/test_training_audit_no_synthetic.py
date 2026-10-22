"""Only integrity/metadata tests; no invented prices, market candles or API responses."""
from pathlib import Path
import pytest
from wallex_bot.challenger_audit import make_folds, safe_archived_train, audit_training_only
from wallex_bot.cli import main


def test_training_audit_cli_help(capsys):
    with pytest.raises(SystemExit) as exc:
        main(['training-audit','--help'])
    assert exc.value.code == 0
    assert '--run' in capsys.readouterr().out


def test_missing_true_wallex_archive_blocked(tmp_path):
    with pytest.raises(FileNotFoundError, match='manifest'):
        safe_archived_train(tmp_path)


def test_disjoint_chronological_training_boundaries():
    assert make_folds(499,72,2) == [(355,427),(427,499)]
    with pytest.raises(ValueError, match='real'):
        make_folds(400,72,2)


def test_live_archive_only_if_provided(monkeypatch):
    import os
    real = os.environ.get('WALLEX_REAL_RUN')
    if not real:
        pytest.skip('Supply actual Wallex archived run as WALLEX_REAL_RUN; never fabricate OHLCV in tests')
    report = audit_training_only(real)
    assert report['n_folds'] == 2
    assert report['train_segment_bars'] >= 474
    assert report['source_claim'] == 'wallex_public_api'
    assert all(len(x['model_metrics']) == 3 for x in report['fold_results'])
