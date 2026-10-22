"""Stage14 metadata and safety contracts, without invented market observations."""
import hashlib
import json
from pathlib import Path

import pytest

from wallex_bot.atlas_challenger_eval import (evaluate, _run_directory,
    _load_saved_run, _frozen_segments, _metrics, ARMS)
from wallex_bot.atlas_challenger_v2 import _canonical_sha
from wallex_bot.atlas_mode import cli_mode, ExecutionMode, ModeSafetyError


def test_stage14_absent_checkpoints_are_read_only(tmp_path):
    before=set(tmp_path.iterdir())
    out=evaluate(tmp_path)
    assert out['status']=='EXPLICIT_STAGE13_RUN_DIRECTORY_REQUIRED'
    assert out['orders'] is False and out['network_requests'] is False
    assert out['db_mutation'] is False and out['training_or_model_promotion'] is False
    assert before==set(tmp_path.iterdir())


def test_stage14_missing_explicit_valid_directory(tmp_path):
    out=evaluate(tmp_path,'research_challengers/stage13_paired_v2/20261022T113152Z_a71cb63c')
    assert out['status']=='RESEARCH_RUN_NOT_FOUND'
    assert not list(tmp_path.iterdir())


def test_stage14_only_accepts_isolated_research_folder(tmp_path):
    run='20261022T113152Z_a71cb63c'
    good='research_challengers/stage13_paired_v2/'+run
    assert _run_directory(tmp_path,good).name==run
    with pytest.raises(ValueError,match='UNTRUSTED_RESEARCH_RUN_PATH'):
        _run_directory(tmp_path,'models/'+run)
    with pytest.raises(ValueError,match='UNTRUSTED_RESEARCH_RUN_PATH'):
        _run_directory(tmp_path,'research_challengers/stage13_paired_v2/../../models/'+run)


def test_stage14_enforces_backtest_and_blocks_live():
    assert cli_mode('challenger-evaluate','BACKTEST') is ExecutionMode.BACKTEST
    with pytest.raises(ModeSafetyError):
        cli_mode('challenger-evaluate','LIVE')
    with pytest.raises(ModeSafetyError):
        cli_mode('challenger-evaluate','SHADOW')


def test_stage14_cannot_treat_untrusted_manifest_as_usable(tmp_path):
    run=tmp_path/'research_challengers'/'stage13_paired_v2'/'20261022T113152Z_a71cb63c'
    run.mkdir(parents=True)
    manifest=[]
    (run/'source_manifest.json').write_text(json.dumps(manifest))
    (run/'report.json').write_text(json.dumps({'status':'COMPLETED_RESEARCH_ONLY_NOT_OOS_ECONOMICS',
         'policy':'STAGE13_PAIRED_GLOBAL_PURGED_V1_V2_COMPARISON',
         'feature_recipe_v2':'EXPERIMENTAL_CHALLENGER_FEATURE_RECIPE_V2_ZERO_DENOMINATOR_CONVENTIONS',
         'risk_or_champion_changed':False,'real_order_submission':False,
         'source_manifest_sha256':_canonical_sha(manifest),
         'arms':[{'arm':a} for a in ARMS]}))
    out=evaluate(tmp_path,'research_challengers/stage13_paired_v2/'+run.name)
    assert out['status']=='FAIL_CLOSED_SAVED_RUN_OR_PROVENANCE_MISMATCH'
    assert not (tmp_path/'catalog.sqlite').exists()


def test_stage14_rejects_source_path_escape_without_reading_it(tmp_path):
    with pytest.raises(ValueError):
        _frozen_segments(tmp_path,[{'symbol':'BTCTMN','resolution':'15',
            'relative_file':'../../private.txt','sha256':'0'*64,'begin':1,'end':2}])


def test_stage14_empty_evaluation_is_not_fabricated():
    assert _metrics([],[])=={'n':0}
    assert len(ARMS)==3


def test_stage14_no_checkpoint_autodiscovery_or_orders():
    import inspect
    from wallex_bot import atlas_challenger_eval
    src=inspect.getsource(atlas_challenger_eval.evaluate)
    assert 'train(' not in src
    assert '_recover_split' in src and '_load_models' in src
    assert 'run_dir is None' in src
