"""No invented market prices, candles, fills or simulated returns are used."""
from pathlib import Path
import pytest

from wallex_bot.atlas_challenger_v2 import prepare, train, _assert_chronological_purge, _canonical_sha
from wallex_bot.atlas_mode import cli_mode, ExecutionMode, ModeSafetyError
from wallex_bot.atlas_cli import main


def test_absent_archive_is_fail_closed_without_creation(tmp_path):
    result=prepare(tmp_path).public_report
    assert result['status']=='NO_EXISTING_GENUINE_CATALOG'
    assert not list(tmp_path.iterdir())
    other=train(tmp_path,epochs=1)
    assert other['training_performed'] is False
    assert not list(tmp_path.iterdir())


def test_research_mode_cannot_be_shadow_or_live():
    assert cli_mode('challenger-preflight',None)==ExecutionMode.BACKTEST
    assert cli_mode('train-challenger-v2','BACKTEST')==ExecutionMode.BACKTEST
    with pytest.raises(ModeSafetyError):cli_mode('train-challenger-v2','LIVE')
    with pytest.raises(ModeSafetyError):cli_mode('train-challenger-v2','SHADOW')


def test_strict_timestamp_purge_without_any_price_data():
    # These are hypothetical integer boundaries ONLY, not fabricated market observations.
    train=[{'key':('metadata',1),'t':1000,'label_end_ts':1100}]
    valid=[{'key':('metadata',2),'t':1300,'label_end_ts':1400}]
    _assert_chronological_purge(train,valid,1200)
    with pytest.raises(RuntimeError,match='TRAIN_LABEL_OVERLAPS'):
        _assert_chronological_purge([{'key':('metadata',1),'t':1000,'label_end_ts':1200}],valid,1200)
    with pytest.raises(RuntimeError,match='VALIDATION_FEATURE'):
        _assert_chronological_purge(train,[{'key':('metadata',2),'t':1100,'label_end_ts':1400}],1200)
    with pytest.raises(RuntimeError,match='DUPLICATE'):
        _assert_chronological_purge(train,[{'key':('metadata',1),'t':1300,'label_end_ts':1400}],1200)


def test_preflight_cli_has_no_archive_writes(tmp_path,monkeypatch,capsys):
    monkeypatch.setenv('WALLEX_ATLAS_HOME',str(tmp_path))
    main(['challenger-preflight','--mode','BACKTEST','--top','8','--hours','24'])
    out=capsys.readouterr().out
    assert 'NO_EXISTING_GENUINE_CATALOG' in out
    assert not list(tmp_path.iterdir())


def test_training_invalid_config_is_rejected_before_torch_or_archive(tmp_path):
    with pytest.raises(ValueError,match='epochs'):
        train(tmp_path,epochs=0)
    with pytest.raises(ValueError,match='architecture'):
        train(tmp_path,architecture='live')
    assert not list(tmp_path.iterdir())


def test_provenance_digest_is_order_sensitive_and_stable():
    assert _canonical_sha({'list':['a','b']})==_canonical_sha({'list':['a','b']})
    assert _canonical_sha({'list':['a','b']})!=_canonical_sha({'list':['b','a']})


def test_research_train_requires_explicit_architecture(capsys):
    with pytest.raises(SystemExit) as exc:
        main(['train-challenger-v2','--mode','BACKTEST'])
    assert exc.value.code==2
    assert 'explicit --model' in capsys.readouterr().err
