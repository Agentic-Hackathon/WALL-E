"""Non-financial clock/status/UI contracts; no invented prices or fills."""
import hashlib,json,threading
from datetime import datetime,timezone
from functools import partial
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.request import Request,urlopen
from urllib.error import HTTPError
import pytest
from wallex_bot.atlas_deadline import schedule,permission,DEADLINE,TEHRAN
from wallex_bot.atlas_order_protocol import OrderProtocol
from wallex_bot.atlas_console import ConsoleHandler,overview,real_candles,public_report,inventory
from wallex_bot.atlas_dashboard import _existing_api_key
from wallex_bot.atlas_live_readiness import readiness

@pytest.mark.parametrize('stamp,phase,entry,exit_',[
 ('2026-10-23T19:19:59+00:00','COLLECTING',True,True),
 ('2026-10-23T19:20:00+00:00','ENTRY_DISABLED',False,True),
 ('2026-10-23T19:30:00+00:00','EXIT_ONLY',False,True),
 ('2026-10-23T20:20:00+00:00','HALTED',False,False),
 ('2026-10-24T00:00:00+00:00','HALTED',False,False)])
def test_deadline_timezone_boundaries(stamp,phase,entry,exit_):
    p=schedule(datetime.fromisoformat(stamp),clock_verified=True,clock_skew_seconds=0)
    assert p['phase']==phase and p['allow_new_entry']==entry and p['allow_exit']==exit_
    assert p['LIVE']=='HARD_DISABLED' and p['settlement_guaranteed'] is False

def test_tehran_and_berlin_dst_conversion():
    from zoneinfo import ZoneInfo
    assert DEADLINE.astimezone(timezone.utc).isoformat()=='2026-10-23T20:20:00+00:00'
    assert DEADLINE.astimezone(ZoneInfo('Europe/Berlin')).hour==22
    assert datetime(2026,10,26,23,50,tzinfo=TEHRAN).astimezone(timezone.utc).hour==20

@pytest.mark.parametrize('skew',[None,6,-6,float('nan'),float('inf')])
def test_bad_clock_never_grants_permission(skew):
    p=schedule(datetime(2026,10,23,12,tzinfo=timezone.utc),clock_verified=True,clock_skew_seconds=skew)
    assert not p['allow_new_entry'] and not p['allow_exit']

def test_naive_clock_is_rejected():
    with pytest.raises(ValueError,match='TIMEZONE'):schedule(datetime(2026,10,23))

def test_residual_after_halt_is_warning_not_automatic_order():
    p=schedule(datetime(2026,10,24,tzinfo=timezone.utc),residual_assets=['non-financial-asset-id'],open_orders=['status-id'])
    assert p['residual_status']=='UNLIQUIDATED_RESIDUAL_MANUAL_REVIEW'
    assert not p['after_deadline_automatic_liquidation']

def test_missing_clock_receipt_blocks_boundary(tmp_path):
    with pytest.raises(RuntimeError,match='CLOCK_BLOCK'):permission(tmp_path,'BUY')
    assert not list(tmp_path.iterdir())

def test_later_server_clock_blocks_exit_even_if_local_clock_is_before_deadline(tmp_path,monkeypatch):
    import wallex_bot.atlas_deadline as module
    stamp=DEADLINE.timestamp()-2;folder=tmp_path/'operations';folder.mkdir()
    (folder/'clock_receipt.json').write_text(json.dumps({'observed_epoch':stamp,'server_epoch':stamp+4,'verified':True,'skew_seconds':4,'rtt_seconds':.1}))
    monkeypatch.setattr(module.time,'time',lambda:stamp)
    with pytest.raises(RuntimeError,match='HALTED'):permission(tmp_path,'SELL')

def test_order_metadata_unknown_cannot_be_retried_or_offset(tmp_path):
    tracker=OrderProtocol(tmp_path/'metadata.sqlite');evidence=hashlib.sha256(b'non-financial-transport-status-control').hexdigest()
    try:
        tracker.register('control-order-1','BTCTMN','BUY');tracker.register('control-order-1','BTCTMN','BUY')
        with pytest.raises(ValueError,match='IDEMPOTENCY'):tracker.register('control-order-1','ETHTMN','BUY')
        tracker.transition('control-order-1','UNKNOWN',evidence)
        assert not tracker.retry_allowed('control-order-1')
        with pytest.raises(ValueError,match='OPPOSING'):tracker.register('control-order-2','BTCTMN','SELL')
        tracker.transition('control-order-1','ACKNOWLEDGED',evidence)
        tracker.transition('control-order-1','PARTIALLY_FILLED',evidence)
        tracker.transition('control-order-1','CANCELED',evidence)
        with pytest.raises(ValueError,match='TRANSITION'):tracker.transition('control-order-1','SUBMITTED',evidence)
        tracker.register('control-order-2','BTCTMN','SELL')
        assert tracker.db.execute('SELECT count(*) FROM order_metadata').fetchone()[0]==2
    finally:tracker.close()

def test_console_empty_source_has_no_fabricated_account_or_db(tmp_path):
    p=overview(tmp_path)
    assert p['real_account']['balance'] is None and p['observations']['forecasts']==[]
    assert real_candles(tmp_path,'BTCTMN','15')['bars']==[]
    assert not list(tmp_path.iterdir())
    with pytest.raises(ValueError):public_report('../../private_account_read')

def test_env_only_key_no_file_discovery(tmp_path,monkeypatch):
    monkeypatch.delenv('WALLEX_API_KEY',raising=False)
    monkeypatch.setattr(Path,'read_text',lambda *a,**k:(_ for _ in ()).throw(AssertionError('No key file may be read')))
    assert _existing_api_key(tmp_path)==''
    assert readiness()['key_environment_present'] is False

def test_tool_inventory_is_real_module_help_not_execution():
    rows=inventory();assert any(r['module']=='wallex_bot.atlas_cli' for r in rows)
    assert all((r['command'].endswith(' --help') if r['help_supported'] else 'SERVICE_NO_HELP' in r['tool_type']) and 'COPY_CLI_ONLY' in r['ui_authority'] for r in rows)

def test_console_http_host_export_and_mutation_boundaries(tmp_path):
    server=ThreadingHTTPServer(('127.0.0.1',0),partial(ConsoleHandler,root=tmp_path));thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    base='http://127.0.0.1:'+str(server.server_address[1])
    try:
        with urlopen(base+'/') as r:assert b'WALL-E' in r.read()
        with urlopen(base+'/api/overview') as r:assert json.load(r)['mode']=='READ_ONLY'
        for req,code in [(Request(base+'/api/overview',headers={'Host':'hostile.invalid'}),403),
            (Request(base+'/api/orders',method='POST',data=b''),405),(Request(base+'/api/report?name=../../pass.txt'),400)]:
            with pytest.raises(HTTPError) as exc:urlopen(req)
            assert exc.value.code==code
    finally:server.shutdown();server.server_close();thread.join(timeout=3)
    assert not list(tmp_path.iterdir())
