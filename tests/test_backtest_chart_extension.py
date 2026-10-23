"""Real archive chart contracts; never synthesize prices or exchange fills."""
import json
from pathlib import Path
import pytest
from ui_backtest.app import charts,INITIAL
from wallex_bot.atlas_study import source_manifest


def test_missing_archive_does_not_create_prices_or_files(tmp_path):
    p=charts(tmp_path)
    assert p['bars']==[] and p['rules']=={} and p['agent_decisions']==[]
    assert not list(tmp_path.iterdir())


def test_symbol_is_allowlisted(tmp_path):
    with pytest.raises(ValueError):charts(tmp_path,'../account')


def test_extension_does_not_break_running_source_contract():
    root=Path('atlas_store');pointer=root/'operations/financial_current_session.json'
    if not pointer.exists():pytest.skip('No genuine frozen study')
    session=root/json.loads(pointer.read_text())['session']
    contract=json.loads((session/'study_contract.json').read_text())
    assert source_manifest()==contract['source_manifest_LF_sha256']
    assert not any(key.startswith('ui_backtest/') for key in source_manifest())


@pytest.fixture(scope='module')
def actual():
    if not Path('atlas_store/catalog.sqlite').exists():pytest.skip('Real archive absent')
    result=charts('atlas_store')
    if not result['rules']:pytest.skip('Insufficient contiguous genuine history/warmup')
    return result


def test_two_day_real_grid_and_no_fake_champion(actual):
    assert actual['requested_end']-actual['requested_start']==172800
    assert len(actual['bars'])==192
    assert all(b['timestamp']-a['timestamp']==900 for a,b in zip(actual['bars'],actual['bars'][1:]))
    assert actual['status']=='HYPOTHETICAL_FIXED_RULES_NOT_CHAMPION'


def test_costed_scenarios_only_at_real_observed_prices(actual):
    bytime={b['timestamp']:b for b in actual['bars']}
    for rule in actual['rules'].values():
        assert rule['champion_or_riskgate_execution'] is False
        cash=float(INITIAL);qty=0.
        for e in rule['events']:
            assert e['price']==bytime[e['timestamp']]['open'] and e['hypothetical']
            if e['side']=='BUY':
                assert qty==0
                cost=e['price']*1.0005*e['quantity']*1.003
                assert cost<=500000.000001 and cost<=cash*.1+.000001
                cash-=cost;qty=e['quantity']
            else:
                assert e['quantity']==qty
                cash+=qty*e['price']*.9995*.997;qty=0.
        assert qty==0
        assert rule['curve'][-1]['nav_tmn']==pytest.approx(cash)
        assert rule['net_pnl_tmn']==pytest.approx(cash-INITIAL)
        assert all(row['drawdown_pct']<=0 for row in rule['curve'])


def test_recorded_roles_have_no_fabricated_agent_returns(actual):
    for d in actual['agent_decisions']:
        assert actual['requested_start']<=d['timestamp']<=actual['requested_end']
        for a in d['agents']:assert set(a)=={'role','recommendation','status'}


def test_invalid_dates_rejected_when_real_archive_present(actual):
    for start,end in [(0,1000000),(float('nan'),actual['requested_end']),(100,99)]:
        with pytest.raises(ValueError):charts('atlas_store',start=start,end=end)


def test_chart_ui_does_not_add_warning_prose_or_fake_finrl_agents():
    js=Path('ui_backtest/view.js').read_text(encoding='utf-8')
    assert 'pages.backtest' in js and 'type="datetime-local"' in js
    assert '<p>' not in js and 'class="warning"' not in js
    assert 'فرضی' in js and 'N/A' in js


def test_http_is_chart_only_and_checks_host(tmp_path):
    import threading
    from functools import partial
    from http.server import ThreadingHTTPServer
    import requests
    from ui_backtest.app import BacktestHandler
    server=ThreadingHTTPServer(('127.0.0.1',0),partial(BacktestHandler,root=tmp_path))
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    url='http://127.0.0.1:'+str(server.server_port)
    try:
        assert requests.get(url+'/api/backtest-charts',timeout=5).json()['bars']==[]
        assert requests.get(url+'/api/backtest-charts',headers={'Host':'other.invalid'},timeout=5).status_code==403
        assert requests.post(url+'/api/research-control',json={'action':'start'},timeout=5).status_code==405
        assert requests.post(url+'/api/orders',json={},timeout=5).status_code==405
    finally:server.shutdown();server.server_close();thread.join()
