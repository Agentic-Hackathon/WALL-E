"""Dashboard contracts without mocked prices, trades, articles or quote fixtures."""
import json
import threading
from functools import partial
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from wallex_bot.atlas_dashboard import (DashboardHandler,candles,news,forecasts,
                                        shadow,strategies,summary,_existing_api_key)
from wallex_bot.atlas_dashboard_eval import evaluate
from wallex_bot.atlas_archive import Lake


def test_empty_source_never_invents_market_history(tmp_path):
    assert candles(tmp_path,'BTCTMN','15')['reason']=='NO_REAL_CANDLE_ARCHIVE'
    assert candles(tmp_path,'BTCTMN','15')['bars']==[]
    assert forecasts(tmp_path)['rows']==[]
    assert shadow(tmp_path)['events']==[]
    assert news(tmp_path)['rows']==[]
    assert strategies(tmp_path)['rows']==[]
    info=summary(tmp_path)
    assert info['forward']['quotes']==0
    assert info['shadow']['cash_tmn'] is None
    assert not (tmp_path/'shadow.sqlite').exists()
    assert not (tmp_path/'forward_observations.sqlite').exists()


def test_symbol_and_interval_input_are_allowlisted(tmp_path):
    import pytest
    with pytest.raises(ValueError):candles(tmp_path,'../data','15')
    with pytest.raises(ValueError):candles(tmp_path,'BTCTMN','unsafe')


def test_no_historical_evidence_without_real_archive(tmp_path):
    lake=Lake(tmp_path)
    try:
        result=evaluate(lake,top=2)
        assert result['indicator_symbols']==0
        assert result['champion_status']=='NO_VERIFIED_MODEL'
        report=json.loads((tmp_path/'reports'/'dashboard_research_eval.json').read_text())
        assert report['champion']['status']=='NO_VERIFIED_MODEL'
        assert report['indicator_challengers']==[]
    finally:lake.close()


def test_server_is_local_and_read_only(tmp_path):
    server=ThreadingHTTPServer(('127.0.0.1',0),partial(DashboardHandler,root=tmp_path))
    port=server.server_port
    thread=threading.Thread(target=server.serve_forever,daemon=True)
    thread.start()
    try:
        with urlopen(f'http://127.0.0.1:{port}/api/summary',timeout=3) as response:
            assert response.status==200
            assert response.headers['Cache-Control']=='no-store'
            obj=json.loads(response.read())
            assert obj['mode']=='READ_ONLY_RESEARCH_SHADOW'
        with urlopen(f'http://127.0.0.1:{port}/api/candles?symbol=BTCTMN&resolution=15',timeout=3) as response:
            assert json.loads(response.read())['bars']==[]
        try:
            urlopen(Request(f'http://127.0.0.1:{port}/api/summary',headers={'Host':'untrusted.example'}),timeout=3)
            assert False,'Invalid Host should not be accepted'
        except HTTPError as exc:
            assert exc.code==403
    finally:
        server.shutdown();server.server_close();thread.join(timeout=5)


def test_dashboard_does_not_auto_load_unknown_keys(tmp_path,monkeypatch):
    monkeypatch.delenv('WALLEX_API_KEY',raising=False)
    monkeypatch.chdir(tmp_path)
    assert _existing_api_key(tmp_path/'atlas_store')==''
