"""Real asset/source/HTTP contracts. No synthetic market observations."""
import hashlib
import json
from pathlib import Path
import re
import threading
from functools import partial
from http.server import ThreadingHTTPServer
from urllib.request import urlopen
import pytest
from wallex_bot.atlas_console import ConsoleHandler, real_candles

ROOT=Path(__file__).resolve().parents[1]


def test_local_font_license_and_exact_unmodified_bytes():
    font=ROOT/'wallex_bot/static/fonts/Vazirmatn.woff2'
    assert font.read_bytes().startswith(b'wOF2')
    assert hashlib.sha256(font.read_bytes()).hexdigest()=='4e3fa217d38fdafc1fea4414ceb58ca5e662cf0ab5fa735a8c8c20e8b42cad92'
    assert 'SIL OPEN FONT LICENSE Version 1.1' in (font.parent/'OFL.txt').read_text()
    css=(ROOT/'wallex_bot/static/console_v2.css').read_text()
    assert '@font-face' in css and 'Vazirmatn' in css and '@media(max-width:700px)' in css


@pytest.mark.parametrize('name',['README.md','README_FA.md'])
def test_new_readme_local_links_and_screenshots_exist(name):
    text=(ROOT/name).read_text(encoding='utf-8')
    assert '```mermaid' in text
    for target in re.findall(r'\]\(([^\s)]+)\)',text):
        if re.match(r'[a-z]+:|#',target):continue
        assert (ROOT/target.partition('#')[0]).is_file(), target


def test_tracked_root_is_clean_and_historical_bytes_preserved():
    import subprocess
    tracked=subprocess.check_output(['git','ls-files'],cwd=ROOT,text=True).splitlines()
    assert not [p for p in tracked if '/' not in p and p.startswith(('CHANGELOG_','QUICKSTART_'))]
    report=json.loads((ROOT/'reports/repository_cleanup.json').read_text())
    assert len(report['moves'])==67 and all(r['bytes_preserved'] for r in report['moves'])
    assert not report['user_untracked_files_touched'] and not report['history_rewritten']


def test_static_routes_are_exact_and_offline(tmp_path):
    server=ThreadingHTTPServer(('127.0.0.1',0),partial(ConsoleHandler,root=tmp_path))
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    base='http://127.0.0.1:'+str(server.server_address[1])
    try:
        for path,content in [('/static/fonts/Vazirmatn.woff2',b'wOF2'),('/static/console_v2.css',b'@font-face'),('/static/console_v2.js',b'agent_name')]:
            with urlopen(base+path) as r:
                assert r.status==200 and content in r.read()
                if path.endswith(('.js','.css')):assert r.headers['Cache-Control']=='no-store'
        with urlopen(base+'/') as r:
            assert b"script-src 'self'" in r.headers['Content-Security-Policy'].encode()
    finally:
        server.shutdown();server.server_close();thread.join(timeout=3)
    assert not list(tmp_path.iterdir())


def test_indicator_diagnostics_use_real_contiguous_closed_archive():
    if not (ROOT/'atlas_store/catalog.sqlite').is_file():
        pytest.skip('Actual Wallex archive is not installed')
    data=real_candles(ROOT/'atlas_store','BTCTMN','15')
    if not data['bars']:
        pytest.skip('No verified real BTCTMN candles installed')
    bars={r['timestamp']:r for r in data['bars']}
    stamps=[r['timestamp'] for r in data['indicators']]
    assert all(t in bars for t in stamps)
    assert all(b-a==900 for a,b in zip(stamps,stamps[1:]))
    assert data['technical']['champion_features_changed'] is False
    assert data['technical']['decision_authority']=='RESEARCH_EVIDENCE_ONLY'
