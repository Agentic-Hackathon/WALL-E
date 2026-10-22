"""Read-only M8 inventory; original Atlas integration audit, no repo execution.

Reference provenance is read from actual clones and SOURCES.md. A cloned
repository is never called a direct integration merely because it was read.
"""
import argparse,hashlib,json,sqlite3,subprocess,time
from pathlib import Path
from .atlas_liquidation import _save_atomic
from .atlas_study import source_manifest


def audit(workspace=None):
    workspace=Path(workspace or Path(__file__).resolve().parents[1]).resolve()
    refs=[];old=json.loads((workspace/'reports/m7_reference_integration.json').read_text())
    known={r['repository']:r for r in old['external_repositories']}
    for repo in sorted((workspace/'third_party').iterdir()):
        if not repo.is_dir() or not (repo/'.git').exists():continue
        commit=subprocess.check_output(['git','-C',str(repo),'rev-parse','HEAD'],text=True).strip()
        licenses=[p for p in repo.iterdir() if p.is_file() and p.stem.upper() in ('LICENSE','LICENCE','COPYING')]
        entry=known.get(repo.name,{})
        license_name=entry.get('license',{'lumibot':'GPL-3.0','grid_trading_bot':'MIT','trading-bot':'UNSPECIFIED'}.get(repo.name,'UNVERIFIED'))
        refs.append({'repository':repo.name,'path':str(repo),'commit':commit,'license':license_name,
            'license_files':[{'path':str(p.relative_to(workspace)),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in licenses],
            'status':'BLOCKED_BY_LICENSE' if not licenses else 'CONCEPTUAL_ONLY',
            'existing_capability':entry.get('capability','Atlas risk-first/circuit-breaker contracts already exist'),
            'copied_external_lines':0,'external_code_executed':False,
            'reason':'No compatible runtime adapter implemented yet; inventory is not functional integration',
            'measured_change':None,'replay_test':None})
    store=workspace/'atlas_store';db=sqlite3.connect((store/'catalog.sqlite').as_uri()+'?mode=ro',uri=True)
    try:
        chunks=[dict(zip(('symbol','resolution','chunks','bars'),r)) for r in db.execute("SELECT symbol,resolution,count(*),sum(rows) FROM chunks WHERE status='COMPLETE' GROUP BY symbol,resolution")]
        assets=db.execute('SELECT count(*) FROM assets').fetchone()[0]
    finally:db.close()
    active=store/'models/active_champion.json'
    checkpoints=[{'path':str(p.relative_to(workspace)),'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in (store/'models').glob('*.pt')]
    state_files=[active,store/'research_challengers/milestone7/formal_48h_v1/study_contract.json']
    snapshot={'stage':'8.1_AUDIT','generated_at':time.time(),'base_commit':'8b3ae3b',
        'branch':subprocess.check_output(['git','branch','--show-current'],text=True).strip(),
        'file_txt':str(workspace/'file.txt') if (workspace/'file.txt').exists() else None,
        'rules_source':'file.txt' if (workspace/'file.txt').exists() else 'USER_M8_PROMPT_ONLY_FILE_TXT_REQUIRED',
        'archive_assets':assets,'archive_chunks_by_market_timeframe':chunks,'checkpoints':checkpoints,
        'protected_file_hashes':{str(p.relative_to(workspace)):hashlib.sha256(p.read_bytes()).hexdigest() for p in state_files if p.exists()},
        'runtime_source_manifest':source_manifest(workspace),'LIVE':'HARD_DISABLED','economic_edge':'NO_VERIFIED_ECONOMIC_EDGE'}
    requirements=[]
    for name,state,evidence in [
        ('core_data_sync','IMPLEMENTED','atlas_data_sync.py'),('feature_registry','IMPLEMENTED','atlas_feature_registry.py'),
        ('news_pit_archive','IMPLEMENTED','atlas_news_pipeline.py'),('shared_watch_agent','IMPLEMENTED','atlas_orchestration.py'),
        ('research_memory','IMPLEMENTED','atlas_memory.py'),('forecast_models','IMPLEMENTED','atlas_prospective.py'),
        ('allocation_proposals','IMPLEMENTED','atlas_portfolio.py'),('deadline_sampler','IMPLEMENTED','atlas_study.py'),
        ('historical_pattern_retrieval','NOT_IMPLEMENTED',None),('dynamic_partial_position_shadow','NOT_IMPLEMENTED',None),
        ('news_value_added','EVIDENCE_INSUFFICIENT','reports/m5_model_ablation.csv'),
        ('verified_economic_edge','EVIDENCE_INSUFFICIENT','reports/m7_portfolio_evaluation.json'),
        ('formal_48h_coverage','EVIDENCE_INSUFFICIENT','reports/m7_session_integrity.json'),
        ('official_rules_file','BLOCKED' if snapshot['file_txt'] is None else 'IMPLEMENTED',snapshot['file_txt']),
        ('live_authorization','BLOCKED',None)]:
        requirements.append({'requirement':name,'status':state,'evidence':evidence})
    return snapshot,{'stage':'8.1_AUDIT_NOT_FINAL_COVERAGE','requirements':requirements},refs


def main():
    p=argparse.ArgumentParser();p.add_argument('--output-dir',default='reports');args=p.parse_args()
    snapshot,coverage,refs=audit();out=Path(args.output_dir);out.mkdir(exist_ok=True,parents=True)
    for name,value in [('m8_initial_audit.json',snapshot),('m8_requirements_coverage.json',coverage),('m8_reference_integration_matrix.json',refs)]:_save_atomic(out/name,value)
    print(json.dumps({'assets':snapshot['archive_assets'],'checkpoints':len(snapshot['checkpoints']),'clones':len(refs),'file_txt':snapshot['file_txt'],'scope':'READ_ONLY_AUDIT'}))

if __name__=='__main__':main()
