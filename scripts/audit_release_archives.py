"""Inspect tracked distribution ZIPs without extracting/executing their contents.

Secret scanner output remains redacted; public report contains counts only.
Nested/encrypted/oversized/unsafe archives fail closed for manual inspection.
"""
import hashlib
import json
from pathlib import Path, PurePosixPath
import subprocess
import zipfile


def main():
    report={'archives':[],'secret_values_exported':False}
    paths=subprocess.check_output(['git','ls-files','*.zip'],text=True).splitlines()
    scanner=Path('.tools/gitleaks/gitleaks.exe').resolve()
    for path in paths:
        pieces=[];unsafe=[]
        with zipfile.ZipFile(path) as archive:
            entries=archive.infolist()
            if sum(e.file_size for e in entries)>50_000_000:
                raise ValueError('ARCHIVE_TOO_LARGE_MANUAL_REVIEW_REQUIRED')
            for entry in entries:
                name=PurePosixPath(entry.filename.replace('\\','/'))
                if (name.is_absolute() or '..' in name.parts or entry.flag_bits&1 or
                    name.name.lower() in ('pass.txt','.env') or name.suffix.lower() in
                    ('.zip','.pt','.pth','.ckpt','.safetensors','.sqlite','.db','.key','.pem')):
                    unsafe.append(entry.filename)
                if not entry.is_dir():pieces.extend([entry.filename.encode(),archive.read(entry)])
        raw=Path('.tools/archive_scan_redacted.json')
        process=subprocess.run([str(scanner),'stdin','--redact=100','--no-banner',
            '--report-format=json','--report-path='+str(raw)],input=b'\n'.join(pieces),capture_output=True)
        findings=json.loads(raw.read_text()) if raw.exists() else []
        report['archives'].append({'path':path,'sha256':hashlib.sha256(Path(path).read_bytes()).hexdigest(),
            'entries':len(entries),'unsafe_path_count':len(unsafe),'scanner_exit':process.returncode,
            'finding_count':len(findings),'status':'PASS' if not unsafe and process.returncode==0 else 'BLOCKED'})
    report['status']='PASS' if all(r['status']=='PASS' for r in report['archives']) else 'BLOCKED'
    Path('reports/archive_security_audit.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report))
    if report['status']!='PASS':raise SystemExit(2)


if __name__=='__main__':main()
