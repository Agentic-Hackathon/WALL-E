"""M5 acceptance: real archive/checkpoints or non-financial control metadata."""
import copy,hashlib,json,sqlite3
from pathlib import Path
import numpy as np
import pytest
from wallex_bot.atlas_m5_data import prepare,digest,four_way_split,feature_groups,freeze,SEEDS
from wallex_bot.atlas_m5_research import load_bundle
from wallex_bot.atlas_m5_models import EarlyStop,ordered_logits,fit_calibration,apply_calibration,metrics,train
from wallex_bot.atlas_m5_inference import replay,smoke,ProspectiveLedger

ROOT=Path(__file__).resolve().parents[1]
RUN=ROOT/'atlas_store/research_challengers/milestone5/m5_20261022_frozen_v1'

@pytest.fixture(scope='module')
def bundle():
    if not (RUN/'dataset_15_0.75/inputs.npz').exists():pytest.skip('M5 real frozen dataset not installed')
    return load_bundle(RUN/'dataset_15_0.75')

def test_split_reproducible_and_globally_purged(bundle):
    assert four_way_split(bundle.rows,2700)==bundle.split
    ids=bundle.split['indices'];seen=set()
    for name,indices in ids.items():
        assert not seen.intersection(indices);seen.update(indices)
        assert indices
    for left,right in zip(list(ids),list(ids)[1:]):
        assert max(bundle.rows[i]['target_end'] for i in ids[left]) < min(bundle.rows[i]['feature_cutoff'] for i in ids[right])-bundle.split['embargo_seconds']

def test_sample_contract_and_no_invented_receipts(bundle):
    for r in bundle.rows:
        assert r['target_end']-r['feature_cutoff']==2700
        assert r['target_start']==r['feature_cutoff']
        assert r['label_type']=='CLOSE_TO_CLOSE_RETURN'
        assert 'RETROSPECTIVE' in r['data_quality_status']
        assert r['feature_available_at'] is None or 'T' in r['feature_available_at']
        assert len(r['history_close_log'])==96

def test_hashes_and_source_files(bundle):
    assert digest(bundle.rows)==bundle.config['dataset_sha256']
    assert digest(bundle.manifest)==bundle.config['source_manifest_sha256']
    for source in bundle.manifest:
        path=(ROOT/'atlas_store'/source['relative_file']).resolve()
        assert path.is_relative_to((ROOT/'atlas_store').resolve())
        assert hashlib.sha256(path.read_bytes()).hexdigest()==source['sha256']

def test_no_optional_imputation_and_recipe_isolation(bundle):
    assert np.array_equal(bundle.arrays['A'],bundle.arrays['B'])
    assert bundle.arrays['C'].shape[-1]==bundle.arrays['A'].shape[-1]+4
    assert all(np.isfinite(x).all() for x in bundle.arrays.values())
    definitions=feature_groups()
    assert set(definitions)==set('ABCDEFG')
    for g,spec in definitions.items():
        assert spec['definition_sha256'] and spec['missing_policy'] and spec['availability']
    assert not any(k in bundle.arrays for k in 'DEFG')

def test_actual_feature_prefix_does_not_look_ahead():
    from wallex_bot.atlas_feature_health import _verified_segments
    from wallex_bot.atlas_feature_recipe import challenger_features
    from wallex_bot.atlas_feature_registry import compute_ohlcv_features
    dbpath=ROOT/'atlas_store/catalog.sqlite'
    if not dbpath.exists():pytest.skip('No actual archive')
    db=sqlite3.connect(dbpath.as_uri()+'?mode=ro',uri=True)
    try:parts,_=_verified_segments(ROOT/'atlas_store',db,'BTCTMN','15')
    finally:db.close()
    real=next((p for p in parts if len(p)>200),None)
    if real is None:pytest.skip('Insufficient real BTC prefix')
    for function in (lambda f:challenger_features(f)[0],lambda f:challenger_features(f)[1],compute_ohlcv_features):
        a=function(real.iloc[:190].copy());b=function(real)
        np.testing.assert_allclose(a.iloc[-1].to_numpy(float),b.iloc[189].to_numpy(float),equal_nan=True)

def test_empty_history_declines_without_network(tmp_path):
    b=prepare(tmp_path)
    assert b.split['status']=='INSUFFICIENT_REAL_TRAINING_HISTORY'
    assert not b.rows and not b.arrays
    with pytest.raises(ValueError,match='INSUFFICIENT'):train(b,'A','patchtst','ordered',17,tmp_path/'model')

def test_frozen_roundtrip_and_no_overwrite(bundle,tmp_path):
    freeze(bundle,tmp_path/'frozen');loaded=load_bundle(tmp_path/'frozen')
    assert loaded.rows==bundle.rows
    assert np.array_equal(loaded.arrays['A'],bundle.arrays['A'])
    with pytest.raises(FileExistsError):freeze(bundle,tmp_path/'frozen')

def test_nonfinancial_early_stop_state():
    stop=EarlyStop(patience=2,min_delta=.01)
    assert stop.observe(1,1)==(True,False)
    assert stop.observe(.999,2)==(False,False)
    assert stop.observe(.998,3)==(False,True)
    assert stop.best_epoch==1
    with pytest.raises(ValueError):stop.observe(float('nan'),4)

def test_ordered_parameterization_with_actual_saved_logits(bundle):
    import torch
    # Input is a real forecast, not fabricated market data.
    p=np.load(RUN/'A_itransformer_raw_17/predictions.npz')['test_raw']
    ordered=ordered_logits(torch.tensor(p)).numpy()
    assert np.all(ordered[:,0]<=ordered[:,1]) and np.all(ordered[:,1]<=ordered[:,2])
    assert SEEDS==(17,29,43)

def test_calibration_independent_and_rejects_leakage(bundle):
    p=np.load(RUN/'baselines/zero_predictions.npz')['test_raw']
    # Actual calibration forecasts/labels produced by a trained saved model.
    cp=np.load(RUN/'A_patchtst_ordered_17/predictions.npz')['calibration']
    y=np.array([r['y'] for r in bundle.rows]);ids=bundle.split['indices']
    fitted=fit_calibration(y[ids['calibration']],cp,bundle.rows,bundle.split)
    assert fitted['samples']==len(ids['calibration'])
    bad=copy.deepcopy(bundle.split);bad['indices']['train']+=ids['calibration'][:1]
    with pytest.raises(ValueError,match='LEAKAGE'):fit_calibration(y[ids['calibration']],cp,bundle.rows,bad)
    calibrated=apply_calibration(p,fitted)
    assert metrics(y[ids['test']],calibrated)['crossing_rate']==0

def test_real_checkpoint_restore_and_auditable_replay(bundle):
    result=replay(RUN)
    assert result['q10']<=result['q50']<=result['q90']
    assert result['authority']=='RESEARCH_ONLY_NO_ORDER'
    assert result['data_readiness']=='FROZEN_RETROSPECTIVE_REPLAY_NOT_LIVE_PIT'
    selection=json.loads((RUN/'research_selection.json').read_text())
    saved=np.load(Path(selection['directory'])/'predictions.npz')['test_calibrated'][-1]
    np.testing.assert_allclose([result[k] for k in ('q10','q50','q90')],saved,rtol=1e-4,atol=1e-7)

def test_no_promotion_and_backtest_graph_isolation(bundle):
    result=smoke(ROOT/'atlas_store',RUN)
    assert result['operational_stores_unchanged'] and result['champion_manifest_unchanged']
    assert not result['broker_imported'] and not result['external_LLM_called']

def test_research_ledger_rejects_retrospective_replay(bundle,tmp_path):
    with pytest.raises(ValueError):ProspectiveLedger(tmp_path/'operational.sqlite')
    ledger=ProspectiveLedger(tmp_path/'research_challengers/forward.sqlite')
    try:
        with pytest.raises(ValueError,match='NO_ELIGIBLE'):ledger.record(replay(RUN))
        assert ledger.status()['counts']=={}
        assert ledger.reconcile(ROOT/'atlas_store')['resolved']==0
    finally:ledger.close()

def test_real_interruption_resume_and_best_restore(bundle):
    import torch
    # Real training, not a fabricated checkpoint. Keep evidence in its own
    # versioned research run; repeated tests reuse the completed acceptance.
    directory=RUN/'resume_acceptance'
    if not (directory/'result.json').exists():
        if not (directory/'resume.pt').exists():
            with pytest.raises(InterruptedError):
                train(bundle,'A','itransformer','ordered',17,directory,pause_after_epoch=1)
        result=train(bundle,'A','itransformer','ordered',17,directory,resume=True)
    else:result=json.loads((directory/'result.json').read_text())
    state=torch.load(directory/'resume.pt',map_location='cpu',weights_only=True)
    best=torch.load(directory/'best.pt',map_location='cpu',weights_only=True)
    assert state['epoch']>=16 and state['stopper']['wait']==15
    assert best['best_epoch']==result['best_epoch']<state['epoch']
    assert result['restored_best_checkpoint']
    reference=json.loads((RUN/'A_itransformer_ordered_17/result.json').read_text())
    # CPU/GPU kernel reproducibility is assessed, not promised bit-for-bit.
    assert result['best_epoch']==reference['best_epoch']
    np.testing.assert_allclose([x['validation_loss'] for x in result['history']],
        [x['validation_loss'] for x in reference['history']],rtol=1e-5,atol=1e-7)
    wrong=copy.copy(bundle);wrong.config={**bundle.config,'dataset_sha256':'tampered-nonfinancial-metadata'}
    with pytest.raises(ValueError,match='MISMATCH'):train(wrong,'A','itransformer','ordered',17,directory,resume=True)

def test_three_real_seeds_and_research_checkpoint_isolation(bundle):
    directories=set()
    for group in 'AC':
        for architecture in ('patchtst','itransformer'):
            observed=set()
            for seed in SEEDS:
                path=RUN/f'{group}_{architecture}_ordered_{seed}'
                result=json.loads((path/'result.json').read_text())
                observed.add(result['config']['seed']);directories.add(path)
                assert result['config']['no_automatic_promotion']
                assert result['config']['dataset_sha256']==bundle.config['dataset_sha256']
                assert hashlib.sha256((path/'best.pt').read_bytes()).hexdigest()==result['checkpoint_sha256']
                assert 'research_challengers' in path.parts and 'models' not in path.parts
            assert observed==set(SEEDS)
    assert len(directories)==12

def test_dataset_switch_cannot_reuse_completed_run_or_overwrite_reports(bundle):
    from wallex_bot.atlas_m5_research import execute
    report=ROOT/'reports/m5_model_comparison.csv'
    before=report.read_bytes()
    with pytest.raises(ValueError,match='CONTRACT_MISMATCH'):
        execute(ROOT/'atlas_store',RUN,ROOT/'reports',dataset_key='60_48')
    assert report.read_bytes()==before
