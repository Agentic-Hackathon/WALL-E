"""Tracked-only historical organization, default dry-run; never touches user files.

git mv preserves bytes/history. Markdown links are mechanically rebased against
their original location. Historical patches/installers are archival, not run.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def plan():
    mapping = {}
    for name in subprocess.check_output(['git','ls-files','-z'], cwd=ROOT).decode().split('\0'):
        if not name:
            continue
        if '/' not in name and name.startswith('CHANGELOG_'):
            mapping[name] = 'legacy/changelogs/'+name
        elif '/' not in name and name.startswith('QUICKSTART_'):
            mapping[name] = 'legacy/quickstarts/'+name
        elif name == 'README_STAGE4_PACKAGE_FA.md':
            mapping[name] = 'legacy/quickstarts/'+name
        elif '/' not in name and name.endswith('.zip'):
            mapping[name] = 'legacy/archives/'+name
        elif name.startswith('patches/') and name.endswith('.patch'):
            mapping[name] = 'legacy/'+name
        elif name.startswith('scripts/apply_stage'):
            mapping[name] = 'legacy/'+name
    return mapping


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--apply',action='store_true');a=parser.parse_args()
    mapping=plan();report={'moves':[], 'user_untracked_files_touched':False,'history_rewritten':False}
    for old,new in mapping.items():
        source=ROOT/old;target=ROOT/new
        if not target.resolve().is_relative_to(ROOT) or target.exists():
            raise ValueError('UNSAFE_OR_EXISTING_MOVE_TARGET')
        before=hashlib.sha256(source.read_bytes()).hexdigest()
        if a.apply:
            target.parent.mkdir(parents=True,exist_ok=True)
            subprocess.run(['git','mv','--',old,new],cwd=ROOT,check=True)
        report['moves'].append({'from':old,'to':new,'sha256_before':before,
            'bytes_preserved':hashlib.sha256(target.read_bytes()).hexdigest()==before if a.apply else None})
    if a.apply:
        tracked=subprocess.check_output(['git','ls-files','-z'],cwd=ROOT).decode().split('\0')
        reverse={v:k for k,v in mapping.items()}
        for name in tracked:
            if not name.endswith('.md') or name.startswith('third_party/'):
                continue
            path=ROOT/name;old=reverse.get(name,name);text=path.read_text(encoding='utf-8-sig')
            def replace(match):
                target=match.group(2)
                if re.match(r'[a-z]+:|#|/',target):return match.group(0)
                rel,mark,anchor=target.partition('#')
                resolved=(ROOT/old).parent/rel
                if not resolved.resolve().is_relative_to(ROOT):return match.group(0)
                prior=resolved.resolve().relative_to(ROOT).as_posix()
                new=mapping.get(prior,prior)
                rebased=os.path.relpath(ROOT/new,path.parent).replace('\\','/')
                return match.group(1)+rebased+(mark+anchor if mark else '')+')'
            updated=re.sub(r'(\[[^\]]*\]\()([^\s)]+)\)',replace,text)
            if updated!=text:path.write_text(updated,encoding='utf-8')
        (ROOT/'reports/repository_cleanup.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps({'move_count':len(mapping),'applied':a.apply,'history_rewritten':False}))


if __name__=='__main__':main()
