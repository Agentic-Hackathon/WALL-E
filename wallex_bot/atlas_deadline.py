"""Competition deadline permission gate, independent of GUI/LLM/RiskGate.

Original Atlas implementation. Stops permission, NEVER promises settlement.
No live transport or fabricated fills. Historical M8 contracts are untouched.
"""
import argparse,json,math,time,urllib.request,sqlite3
from datetime import datetime,timedelta,timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from zoneinfo import ZoneInfo

TEHRAN=ZoneInfo('Asia/Tehran')
DEADLINE=datetime(2026,10,23,23,50,tzinfo=TEHRAN)
ENTRY_STOP=DEADLINE-timedelta(hours=1)
UNWIND_START=DEADLINE-timedelta(minutes=50)

def schedule(now=None,*,clock_verified=False,clock_skew_seconds=None,residual_assets=None,open_orders=None):
    now=now or datetime.now(timezone.utc)
    if now.tzinfo is None or now.utcoffset() is None:raise ValueError('TIMEZONE_AWARE_CLOCK_REQUIRED')
    local=now.astimezone(TEHRAN)
    phase='HALTED' if local>=DEADLINE else 'EXIT_ONLY' if local>=UNWIND_START else 'ENTRY_DISABLED' if local>=ENTRY_STOP else 'COLLECTING'
    safe=clock_verified and clock_skew_seconds is not None and math.isfinite(clock_skew_seconds) and abs(clock_skew_seconds)<=5
    residual=bool(residual_assets) or bool(open_orders)
    return {'phase':phase,'now_tehran':local.isoformat(),'deadline_tehran':DEADLINE.isoformat(),'deadline_utc':DEADLINE.astimezone(timezone.utc).isoformat(),
        'entry_stop':ENTRY_STOP.isoformat(),'unwind_start':UNWIND_START.isoformat(),'seconds_remaining':max(0,(DEADLINE-local).total_seconds()),
        'clock_verified':bool(safe),'clock_skew_seconds':clock_skew_seconds,'clock_status':'VERIFIED_HTTP_DATE_WITHIN_5S' if safe else 'UNVERIFIED_OR_DANGEROUS_CLOCK_FAIL_CLOSED',
        'allow_new_entry':safe and phase=='COLLECTING','allow_exit':safe and phase in ('COLLECTING','ENTRY_DISABLED','EXIT_ONLY'),
        'allow_cancel':safe and phase!='HALTED','LIVE':'HARD_DISABLED','live_armed':False,
        'residual_status':'UNLIQUIDATED_RESIDUAL_MANUAL_REVIEW' if residual and phase=='HALTED' else 'OPEN_EXPOSURE_REQUIRES_RECONCILIATION' if residual else 'NOT_VERIFIED_NO_ACCOUNT_SNAPSHOT',
        'settlement_guaranteed':False,'after_deadline_automatic_liquidation':False}

def clock_probe():
    # Public GET only; Date can be a proxy clock, not a financial authorization.
    begin=time.time()
    try:
        request=urllib.request.Request('https://api.wallex.ir/v1/markets',headers={'User-Agent':'Atlas-clock-readonly','Cache-Control':'no-cache'})
        with urllib.request.urlopen(request,timeout=10) as response:
            raw=response.headers.get('Date');age=response.headers.get('Age');status=response.status
        end=time.time();server=parsedate_to_datetime(raw).timestamp();skew=server-(begin+end)/2
        valid=200<=status<300 and end-begin<=4 and (age is None or float(age)<=1) and abs(skew)<=5
        return {'observed_epoch':end,'server_epoch':server,'skew_seconds':skew,'rtt_seconds':end-begin,'verified':valid,'source':'PUBLIC_HTTPS_DATE_NOT_EXCHANGE_FILL_TIME'}
    except Exception as exc:return {'observed_epoch':time.time(),'verified':False,'error_type':type(exc).__name__}

def permission(root,action):
    """Actual current-clock boundary; no caller-supplied clock or entry override."""
    path=Path(root)/'operations/clock_receipt.json';clock={}
    if path.is_file():
        try:clock=json.loads(path.read_text())
        except (ValueError,OSError):pass
    wall=time.time();age=wall-clock.get('observed_epoch',0)
    fresh=0<=age<=120 and isinstance(clock.get('server_epoch'),(int,float)) and math.isfinite(clock['server_epoch'])
    # Use the later clock plus Date/round-trip uncertainty. A local clock a few
    # seconds behind the server must never permit trading after server deadline.
    effective=max(wall,clock['server_epoch']+age+max(0,clock.get('rtt_seconds',0))/2+1) if fresh else wall
    state=schedule(datetime.fromtimestamp(effective,timezone.utc),clock_verified=fresh and clock.get('verified') is True,clock_skew_seconds=clock.get('skew_seconds'))
    kind='allow_new_entry' if action in ('BUY','ADD','REBALANCE') else 'allow_exit' if action in ('SELL','REDUCE') else 'allow_cancel'
    if not state[kind]:raise RuntimeError('COMPETITION_DEADLINE_OR_CLOCK_BLOCK:'+state['phase'])
    return state

def watchdog(root,*,duration=None,interval=15):
    folder=Path(root)/'operations';folder.mkdir(parents=True,exist_ok=True);start=time.monotonic()
    clock={};state={}
    try:
        while True:
            clock=clock_probe();(folder/'clock_receipt.json').write_text(json.dumps(clock),encoding='utf-8')
            positions=[];orders=[];account=Path(root)/'shadow.sqlite'
            if account.is_file():
                db=sqlite3.connect(account.resolve().as_uri()+'?mode=ro',uri=True)
                try:positions=[r[0] for r in db.execute('SELECT symbol FROM positions')]
                finally:db.close()
            state=schedule(clock_verified=clock.get('verified',False),clock_skew_seconds=clock.get('skew_seconds'),residual_assets=positions,open_orders=orders)
            state.update(paper_residual_symbols=positions,real_residual_status='UNKNOWN_ACCOUNT_NOT_VERIFIED',
                operator_alert=('UNLIQUIDATED_RESIDUAL_MANUAL_REVIEW' if positions else 'ACCOUNT_OR_RESIDUAL_NOT_VERIFIED_MANUAL_REVIEW') if state['phase']=='HALTED' else None)
            # Independent process state; no order transport and no automatic service install.
            state.update(watchdog_observed_epoch=time.time(),process_heartbeat=True,actual_orders_sent=0)
            (folder/'deadline_status.json').write_text(json.dumps(state,indent=2),encoding='utf-8')
            print(json.dumps({'phase':state['phase'],'clock_verified':state['clock_verified'],'LIVE':'HARD_DISABLED'}),flush=True)
            if duration is not None and time.monotonic()-start>=duration:return
            time.sleep(min(interval,max(.1,duration-(time.monotonic()-start))) if duration is not None else interval)
    finally:
        # A stopped watchdog must not leave an apparently live permission lease.
        clock.update(probe_verified=clock.get('verified',False),verified=False,watchdog_stopped_at=time.time())
        state.update(process_heartbeat=False,stopped_at=time.time())
        (folder/'clock_receipt.json').write_text(json.dumps(clock),encoding='utf-8')
        (folder/'deadline_status.json').write_text(json.dumps(state,indent=2),encoding='utf-8')

def main():
    p=argparse.ArgumentParser();p.add_argument('command',choices=['status','clock-check','watchdog']);p.add_argument('--root',default='atlas_store');p.add_argument('--duration',type=float);a=p.parse_args()
    if a.command=='watchdog':watchdog(a.root,duration=a.duration);return
    result=clock_probe() if a.command=='clock-check' else schedule()
    print(json.dumps(result,ensure_ascii=False))

if __name__=='__main__':main()
