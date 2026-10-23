"""Portable, stdlib-only judge manifest/preflight; tracked inputs only, no orders.

M8 historical source manifests are never modified or validated as today's code.
"""
import argparse,ast,hashlib,importlib.metadata,json,subprocess,sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

def manifest(workspace=ROOT):
    files=subprocess.check_output(['git','ls-files','-z'],cwd=workspace).decode().split('\0')
    return {name:hashlib.sha256((workspace/name).read_bytes().replace(b'\r\n',b'\n')).hexdigest()
        for name in sorted(files) if name and (workspace/name).is_file() and
        (name.startswith(('wallex_bot/','scripts/')) or name.startswith('requirements') or name in ('.gitignore','.gitleaksignore'))}

def tools(workspace=ROOT):
    items=[]
    for path in sorted((workspace/'wallex_bot').glob('*.py')):
        tree=ast.parse(path.read_text(encoding='utf-8-sig'));main=False;commands=[];has_parser=False
        for node in ast.walk(tree):
            if isinstance(node,ast.FunctionDef) and node.name=='main':main=True
            if isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute) and node.func.attr=='ArgumentParser':has_parser=True
            if isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute) and node.func.attr=='add_argument':
                for kw in node.keywords:
                    if kw.arg=='choices':
                        try:value=ast.literal_eval(kw.value)
                        except (ValueError,TypeError):continue
                        if isinstance(value,(tuple,list)) and all(isinstance(v,str) for v in value):commands.extend(value)
        if main:
            items.append({'module':'wallex_bot.'+path.stem,'command':'python -m wallex_bot.'+path.stem+(' --help' if has_parser else ''),
                'help_supported':has_parser,'tool_type':'CLI' if has_parser else 'SERVICE_NO_HELP; starts only by explicit terminal action',
                'options_or_commands':sorted(set(commands)),'description':(ast.get_docstring(tree) or path.stem).splitlines()[0],
                'ui_authority':'DISCOVER_AND_COPY_CLI_ONLY; no arbitrary command execution'})
    return items

def preflight(root='atlas_store',workspace=ROOT):
    root=Path(root);checks=[]
    for name,present in [('source', (workspace/'wallex_bot/atlas_risk.py').is_file()),('catalog',(root/'catalog.sqlite').is_file()),('champion_metadata',(root/'models/active_champion.json').is_file())]:
        checks.append({'check':name,'status':'PASS' if present else 'BLOCKED','reason':None if present else 'DATA_NOT_AVAILABLE'})
    checkpoint_ok=False
    try:
        meta=json.loads((root/'models/active_champion.json').read_text());models=(root/'models').resolve();checkpoint=(models/meta['selected_checkpoint']).resolve()
        checkpoint_ok=checkpoint.is_relative_to(models) and checkpoint.is_file() and hashlib.sha256(checkpoint.read_bytes()).hexdigest()==meta['checkpoint_sha256']
    except (OSError,ValueError,KeyError,TypeError):pass
    checks.append({'check':'champion_checkpoint_sha256','status':'PASS' if checkpoint_ok else 'BLOCKED','reason':None if checkpoint_ok else 'DATA_NOT_AVAILABLE_OR_HASH_INVALID'})
    deps={}
    for name in ('numpy','pandas','scipy','scikit-learn','torch','langgraph','langgraph-checkpoint-sqlite','lightgbm','pytest'):
        try:deps[name]=importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:deps[name]=None
    checks.append({'check':'research_dependencies','status':'PASS' if all(deps.values()) else 'BLOCKED','reason':'MISSING_PACKAGES' if not all(deps.values()) else None})
    return {'status':'PASS' if all(c['status']=='PASS' for c in checks) else 'BLOCKED','checks':checks,'packages':deps,
        'python':sys.version.split()[0],'tracked_source_manifest':manifest(workspace),'LIVE':'HARD_DISABLED','network_requests':0,
        'historical_session_reused':False,'actual_model_inference_validated':False,'missing_asset_policy':'DATA_NOT_AVAILABLE; obtain public archive and approved checkpoint, never fabricate',
        'tools':tools(workspace),'reproduction_scope':'CURRENT_TRACKED_RESEARCH_SOURCE; NOT original M8 forward session'}

def main():
    p=argparse.ArgumentParser();p.add_argument('--root',default='atlas_store');p.add_argument('--output',default='reports/judge_reproducibility.json');a=p.parse_args()
    result=preflight(a.root);Path(a.output).parent.mkdir(parents=True,exist_ok=True);Path(a.output).write_text(json.dumps(result,indent=2,ensure_ascii=False),encoding='utf-8')
    print(json.dumps({'status':result['status'],'checks':result['checks'],'LIVE':result['LIVE'],'tool_modules':len(result['tools'])}))
    if result['status']!='PASS':raise SystemExit(2)

if __name__=='__main__':main()
