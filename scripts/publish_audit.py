"""Local publish audit. Never prints credentials or scanner secret material.

Git Credential Manager is used only for github.com -> api.github.com metadata.
Gitleaks official binary is supplied by the operator; no key is persisted.
"""
import argparse,hashlib,json,os,subprocess,time,urllib.request
from pathlib import Path

REPO='Agentic-Hackathon/WALL-E'

def save(path,obj):
    Path(path).parent.mkdir(parents=True,exist_ok=True)
    Path(path).write_text(json.dumps(obj,indent=2,ensure_ascii=False),encoding='utf-8')

def github_metadata():
    env=dict(os.environ,GIT_TERMINAL_PROMPT='0',GCM_INTERACTIVE='Never')
    p=subprocess.run(['git','credential','fill'],input='protocol=https\nhost=github.com\n\n',text=True,capture_output=True,env=env)
    fields=dict(line.split('=',1) for line in p.stdout.splitlines() if '=' in line)
    credential=fields.get('password')
    if p.returncode or not credential:return {'status':'BLOCKED_NO_LOCAL_CREDENTIAL'}
    req=urllib.request.Request('https://api.github.com/repos/'+REPO,headers={'Authorization':'Bearer '+credential,'Accept':'application/vnd.github+json','User-Agent':'Atlas-private-publish-audit'})
    try:
        with urllib.request.urlopen(req,timeout=20) as response:body=json.load(response)
    except Exception as exc:return {'status':'BLOCKED_METADATA_UNVERIFIED','error_type':type(exc).__name__}
    return {'status':'VERIFIED' if body.get('private') and body.get('permissions',{}).get('push') else 'BLOCKED_PRIVATE_OR_PUSH_PERMISSION',
        'url':body['html_url'],'private':body.get('private'),'permissions':body.get('permissions'),
        'default_branch':body.get('default_branch'),'size':body.get('size'),'visibility':body.get('visibility'),
        'credential_source':'local Git Credential Manager; never printed or stored'}


def delivery_pr():
    """User-requested draft PR only, never merge/arm; credential stays in memory."""
    branch=subprocess.check_output(['git','branch','--show-current'],text=True).strip()
    if branch!='codex/final-production-readiness':raise ValueError('UNEXPECTED_DELIVERY_BRANCH')
    metadata=github_metadata()
    if metadata.get('status')!='VERIFIED':return metadata
    env=dict(os.environ,GIT_TERMINAL_PROMPT='0',GCM_INTERACTIVE='Never')
    process=subprocess.run(['git','credential','fill'],input='protocol=https\nhost=github.com\n\n',text=True,capture_output=True,env=env)
    fields=dict(line.split('=',1) for line in process.stdout.splitlines() if '=' in line)
    token=fields.get('password')
    if process.returncode or not token:return {'status':'BLOCKED_NO_LOCAL_CREDENTIAL'}
    headers={'Authorization':'Bearer '+token,'Accept':'application/vnd.github+json','User-Agent':'Atlas-private-delivery'}
    # Query first so re-running after a lost response cannot create duplicate PRs.
    query='https://api.github.com/repos/'+REPO+'/pulls?state=open&head=Agentic-Hackathon%3Acodex%2Ffinal-production-readiness'
    with urllib.request.urlopen(urllib.request.Request(query,headers=headers),timeout=25) as response:existing=json.load(response)
    if existing:body=existing[0]
    else:
        payload={'title':'WALL-E: safer Spot preflight, persistent deadline, repository and UI delivery',
            'head':branch,'base':'main','draft':True,
            'body':'## Scope\nReal read-only Spot preflight/recovery, persistent deadline observer, licensed Vazirmatn UI, bilingual documentation, and historical repository organization.\n\n## Not production ready\nLIVE remains HARD_DISABLED. No order/cancel/transfer was sent. Financial POST/DELETE transport, operator arming, verified contest account and positive real-fill E2E remain open. This draft must NOT be merged as a live-trading release.\n\nSee docs/FINAL_LIVE_UI_REPOSITORY_REPORT_FA.md and reports/final_readiness_* for exact test/evidence provenance. No history rewrite; user untracked files and private state preserved.'}
        request=urllib.request.Request('https://api.github.com/repos/'+REPO+'/pulls',data=json.dumps(payload).encode(),headers=headers,method='POST')
        with urllib.request.urlopen(request,timeout=25) as response:body=json.load(response)
    return {'status':'DRAFT_PR_CREATED_OR_VERIFIED','url':body['html_url'],'number':body['number'],
            'head':body['head']['sha'],'base':body['base']['ref'],'draft':body['draft'],'merged':body.get('merged',False)}

def scan(executable):
    folder=Path('.tools');folder.mkdir(exist_ok=True);raw=folder/'gitleaks-redacted.json'
    result=subprocess.run([str(Path(executable).resolve()),'git','--log-opts=HEAD','--redact=100','--no-banner','--report-format=json','--report-path='+str(raw),'.'],capture_output=True,text=True)
    findings=json.loads(raw.read_text()) if raw.exists() else []
    # Raw report is already redacted, nevertheless only location/rule is released.
    clean=[{k:r.get(k) for k in ('RuleID','File','StartLine','Commit','Fingerprint')} for r in findings]
    names=subprocess.check_output(['git','rev-list','--objects','HEAD'],text=True).splitlines()
    forbidden=[]
    for row in names:
        path=row.partition(' ')[2];name=Path(path).name.lower()
        if name=='pass.txt' or name=='.env' or (name.startswith('.env.') and name!='.env.example') or path.lower().endswith(('.pt','.pth','.ckpt','.safetensors','.sqlite','.db')):forbidden.append(path)
    return {'scanner':'gitleaks','version':subprocess.check_output([str(Path(executable).resolve()),'version'],text=True).strip(),
        'binary_sha256':hashlib.sha256(Path(executable).read_bytes()).hexdigest(),'scope':'every commit reachable from HEAD; selected publication files must be committed then rescanned',
        'head':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),'exit_code':result.returncode,
        'status':'PASS' if result.returncode==0 and not forbidden else 'BLOCKED','findings':clean,'forbidden_historical_paths':sorted(set(forbidden)),
        'secret_values_exported':False,'history_rewritten':False,'scanned_at':time.time()}

def inspect_locations():
    findings=json.loads(Path('reports/secrets_scan.json').read_text())['findings'];keys={}
    for f in findings:
        lines=subprocess.check_output(['git','show',f['Commit']+':'+f['File']],text=True).splitlines()
        try:
            entry=json.loads('{'+lines[f['StartLine']-1].strip().rstrip(',')+'}')
            key,value=next(iter(entry.items()))
            shape='HEX64' if isinstance(value,str) and len(value)==64 and all(c in '0123456789abcdef' for c in value) else 'OTHER'
        except (ValueError,IndexError):key,shape='UNPARSED','UNKNOWN'
        label=key+'|'+shape;keys[label]=keys.get(label,0)+1
    return keys

def verified_false_positives():
    findings=json.loads(Path('reports/secrets_scan.json').read_text())['findings'];verified=[]
    snapshot=Path('atlas_store/news_models/models--ProsusAI--finbert/snapshots/0bc2ac10dda6929bcb1f77ccc43c7ec5c424f031')
    for f in findings:
        lines=subprocess.check_output(['git','show',f['Commit']+':'+f['File']],text=True).splitlines()
        entry=json.loads('{'+lines[f['StartLine']-1].strip().rstrip(',')+'}');key,value=next(iter(entry.items()))
        if key in ('wallex_bot\\wallex_api.py','wallex_bot/wallex_api.py'):
            data=subprocess.check_output(['git','show',f['Commit']+':wallex_bot/wallex_api.py']).replace(b'\r\n',b'\n')
        elif key in ('special_tokens_map.json','tokenizer_config.json'):data=(snapshot/key).read_bytes()
        else:raise ValueError('UNREVIEWED_FINDING_NO_ALLOWLIST')
        if hashlib.sha256(data).hexdigest()!=value:raise ValueError('FINDING_NOT_VERIFIED_AS_PUBLIC_ARTIFACT_DIGEST')
        verified.append(f['Fingerprint'])
    return verified

def main():
    p=argparse.ArgumentParser();p.add_argument('command',choices=['github','scan','inspect','verify-digests','delivery-pr']);p.add_argument('--gitleaks',default='.tools/gitleaks.exe');p.add_argument('--output');a=p.parse_args()
    if a.command=='delivery-pr':
        obj=delivery_pr();save(a.output or 'reports/final_readiness_pr.json',obj);print(json.dumps(obj));return
    if a.command=='inspect':print(json.dumps(inspect_locations()));return
    if a.command=='verify-digests':print(json.dumps(verified_false_positives()));return
    obj=github_metadata() if a.command=='github' else scan(a.gitleaks)
    output=a.output or ('reports/github_access_audit.json' if a.command=='github' else 'reports/secrets_scan.json')
    save(output,obj);print(json.dumps({k:v for k,v in obj.items() if k!='findings'},ensure_ascii=False))
    if obj['status'] not in ('PASS','VERIFIED'):raise SystemExit(2)

if __name__=='__main__':main()
