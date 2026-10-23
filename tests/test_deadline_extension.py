"""Operator deadline revision: time/control metadata only, no market fixtures."""
from datetime import datetime,timezone
import json
import pytest
from wallex_bot.atlas_deadline import DEADLINE,ENTRY_STOP,UNWIND_START,TEHRAN,schedule,permission
from wallex_bot.atlas_deadline_supervisor import DeadlineSupervisor
from wallex_bot.atlas_spot_exchange import RealSpotBroker
from wallex_bot.atlas_broker import BrokerSafetyError


def test_explicit_third_aban_schedule_and_no_live_authorization():
    assert DEADLINE.isoformat()=='2026-10-25T23:50:00+03:30'
    assert ENTRY_STOP.isoformat()=='2026-10-25T22:50:00+03:30'
    assert UNWIND_START.isoformat()=='2026-10-25T23:00:00+03:30'
    assert DEADLINE.weekday()==6 # Sunday, not Friday.
    old_cutoff=datetime(2026,10,23,23,50,tzinfo=TEHRAN)
    p=schedule(old_cutoff,clock_verified=True,clock_skew_seconds=0)
    assert p['phase']=='COLLECTING' and p['LIVE']=='HARD_DISABLED' and not p['live_armed']
    assert not p['settlement_guaranteed']


def test_pre_extension_supervisor_halt_is_never_reset(tmp_path,monkeypatch):
    import wallex_bot.atlas_deadline_supervisor as module
    old_epoch=datetime(2026,10,23,23,50,tzinfo=TEHRAN).timestamp()
    s=DeadlineSupervisor(tmp_path)
    with s.db:s.db.execute('INSERT INTO supervisor VALUES(1,?,?,?)',(old_epoch+1,1,json.dumps({'deadline_tehran':'2026-10-23T23:50:00+03:30'})))
    s.close()
    monkeypatch.setattr(module.time,'time',lambda:old_epoch+3600)
    s=DeadlineSupervisor(tmp_path)
    try:
        p=s.tick({})
        assert p['phase']=='HALTED' and p['halted_latched'] and p['orders_sent']==0
        for action in ('BUY','SELL','CANCEL'):
            with pytest.raises(RuntimeError,match='HALTED_LATCHED'):permission(tmp_path,action)
    finally:s.close()


def test_old_spot_halt_requires_review_not_automatic_arm(tmp_path):
    folder=tmp_path/'operations';folder.mkdir()
    auth=folder/'control.json';auth.write_text(json.dumps({'account_client_id':'control_identity_only'}))
    broker=RealSpotBroker.with_operator_evidence(tmp_path,auth,tmp_path/'research_challengers/control')
    halt=broker.directory/'operations/spot_halt.json';broker.close()
    halt.write_text(json.dumps({'halted':True,'deadline_epoch':datetime(2026,10,23,23,50,tzinfo=TEHRAN).timestamp()}))
    with pytest.raises(BrokerSafetyError,match='INVALID_PERSISTENT_SPOT_HALT_MANUAL_REVIEW'):
        RealSpotBroker.with_operator_evidence(tmp_path,auth,tmp_path/'research_challengers/control')
    assert json.loads(halt.read_text())['halted'] is True
