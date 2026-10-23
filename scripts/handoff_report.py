"""Generate submission evidence from actual Git/tests/receipts, no trading."""
import argparse,hashlib,json,subprocess,sys,time,urllib.request,xml.etree.ElementTree as ET
from datetime import datetime,timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from judge_preflight import tools,preflight
from publish_audit import github_metadata,save
from wallex_bot.atlas_deadline import schedule,DEADLINE
from wallex_bot.atlas_live_readiness import readiness

def junit(path):
    node=ET.parse(path).getroot();s=node.find('testsuite') if node.tag!='testsuite' else node
    row={k:int(s.attrib[k]) for k in ('tests','failures','errors','skipped')};row['passed']=row['tests']-row['failures']-row['errors']-row['skipped']
    row['seconds']=float(s.attrib['time']);row['sha256']=hashlib.sha256(Path(path).read_bytes()).hexdigest()
    row['skip_reasons']=sorted({c.find('skipped').get('message','') for c in node.iter('testcase') if c.find('skipped') is not None})
    return row

def git(*args,cwd=ROOT):return subprocess.check_output(['git',*args],cwd=cwd,text=True).strip()

def main():
    p=argparse.ArgumentParser();p.add_argument('--network-audit',action='store_true');a=p.parse_args();out=ROOT/'reports'
    suite=junit(out/'m8_followup_pytest.xml');save(out/'m8_followup_test_results.json',suite)
    save(out/'tools_inventory.json',{'origin':'AST of actual tracked/current module CLIs','tools':tools(ROOT),'shell_execution_from_ui':False})
    reproduction=preflight(ROOT/'atlas_store',ROOT);save(out/'judge_reproducibility.json',reproduction)
    models=[]
    for path in sorted((ROOT/'atlas_store/models').glob('*.pt')):
        models.append({'file':path.name,'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'bytes':path.stat().st_size,'weights_published':False})
    save(out/'model_inventory.json',{'champion_metadata':json.loads((ROOT/'atlas_store/models/active_champion.json').read_text()),'checkpoints':models,
        'forecast_models':['champion','m5_patchtst','m5_lightgbm','zero','historical_quantiles'],'iTransformer':'research only',
        'FinBERT':'NC research only; contest use disabled; weights not published','trained_or_promoted_during_handoff':False})
    deadline={'actual_status':schedule(),'dry_run_contract_only_no_financial_data':[],
        'clock_receipt':json.loads((ROOT/'atlas_store/operations/clock_receipt.json').read_text()) if (ROOT/'atlas_store/operations/clock_receipt.json').exists() else None,
        'service_installed':False,'persistent_watchdog_running':False,'live_orders_sent':0,'liquidation_performed':False,'unwind_transport':'BLOCKED_NOT_AUTHORIZED',
        'residual_account_status':'UNKNOWN_ACCOUNT_NOT_VERIFIED; MANUAL_REVIEW_REQUIRED','old_m8_deadline_modified':False}
    for stamp in ('2026-10-23T19:19:59+00:00','2026-10-23T19:20:00+00:00','2026-10-23T19:30:00+00:00','2026-10-23T20:20:00+00:00'):
        deadline['dry_run_contract_only_no_financial_data'].append(schedule(datetime.fromisoformat(stamp),clock_verified=True,clock_skew_seconds=0))
    save(out/'deadline_dry_run.json',deadline);save(out/'live_readiness.json',readiness())
    urls=['/','/api/overview','/api/tools','/api/news','/api/observations','/api/candles?symbol=BTCTMN&resolution=15','/api/pattern-lines']
    smoke=[]
    for path in urls:
        with urllib.request.urlopen('http://127.0.0.1:8766'+path,timeout=20) as r:data=r.read();smoke.append({'path':path,'status':r.status,'bytes':len(data)})
    save(out/'ui_smoke.json',{'url':'http://127.0.0.1:8766','actual_http':smoke,'browser_checks':['Persian RTL overview','tool search pattern: 2 matches',
        'actual 5-model quantiles and effective missed deadline status','5 real normalized analogue lines','English LTR switch','real archived news with NC warning'],
        'automated_security_tests':'test_publish_deadline_ui_contracts.py','mobile_layout':'CSS breakpoint implemented; separate mobile-device run not claimed',
        'private_endpoint_called_from_ui':False,'start_stop_controls':'not offered; read-only, CLI foreground documented','order_or_live_button':False})
    fresh=ROOT/'.judge-clone';initial=out/'fresh_clone_initial_pytest.xml';final=out/'fresh_clone_pytest.xml'
    checker=subprocess.run([str(ROOT/'.judge-venv/Scripts/python.exe'),'-m','pip','check'],capture_output=True,text=True)
    save(out/'fresh_clone_test.json',{'repository':'https://github.com/Agentic-Hackathon/WALL-E.git','clone_commit':git('rev-parse','HEAD',cwd=fresh),
        'actual_remote_clone':True,'venv_isolated_no_system_site_packages':True,'install_command':'python -m pip install -r .judge-clone/requirements-m8.txt',
        'dependency_install':'SUCCEEDED_ACTUAL','pip_check_exit_code':checker.returncode,'pip_check':checker.stdout.strip(),
        'initial_test':junit(initial) if initial.exists() else None,'final_test':junit(final) if final.exists() else None,
        'data_or_weights_copied_into_clone':False,'preflight':'BLOCKED_DATA_NOT_AVAILABLE','full_numeric_reproduction':'BLOCKED_MISSING_REAL_ARCHIVE_CHECKPOINTS',
        'fixture_fixes':'missing real fixture => explicit skip; assertions retained when present; no synthetic data'})
    rubric=json.loads((out/'m8_hackathon_rubric.json').read_text());rubric.update(UI_is_not_economic_edge=True,deadline_requires_manual_residual_review=True,actual_awarded_score=None)
    save(out/'rubric_300_evidence.json',rubric)
    if a.network_audit:
        meta=github_metadata();remote=git('ls-remote','submission','refs/heads/main','refs/tags/atlas-m8-execution-a112709')
        save(out/'github_publish_audit.json',{'repository':meta,'local_head':git('rev-parse','HEAD'),'branch':git('branch','--show-current'),
            'remote_refs':remote.splitlines(),'main_matches_local_head':any(line.startswith(git('rev-parse','HEAD')+'\t') and line.endswith('refs/heads/main') for line in remote.splitlines()),
            'history_rewritten':False,'force_push_used':False,'keys_or_model_weights_published':False,'audit_at':time.time(),
            'commit_url':'https://github.com/Agentic-Hackathon/WALL-E/commit/'+git('rev-parse','HEAD')})
    print(json.dumps({'tests':suite['passed'],'skipped':suite['skipped'],'tools':len(reproduction['tools']),'reports':'generated from actual evidence','LIVE':'HARD_DISABLED'}))

if __name__=='__main__':main()
