"""Independent read-only deadline supervisor; original Atlas orchestration.

Reuses atlas_deadline clock policy, never bypasses RiskGate or starts orders.
SQLite high-water time and HALTED latch survive restart and wall-clock rollback.
Browser lifecycle is irrelevant. Private reads are explicit and remain local.
"""
import argparse
import json
from pathlib import Path
import sqlite3
import time
from datetime import datetime, timezone

from .atlas_deadline import clock_probe, schedule
from .atlas_spot_exchange import SpotReadTransport, BrokerSafetyError


class DeadlineSupervisor:
    def __init__(self, root):
        self.root = Path(root)
        folder = self.root / 'operations'; folder.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(folder / 'deadline_supervisor.sqlite', timeout=20)
        self.db.execute('CREATE TABLE IF NOT EXISTS supervisor(id INTEGER PRIMARY KEY CHECK(id=1),high_water REAL,halted INTEGER,snapshot TEXT)')
        self.db.commit()

    def tick(self, clock, *, private_read=False):
        wall = time.time()
        age = wall - clock.get('observed_epoch', 0)
        fresh = clock.get('verified') is True and 0 <= age <= 120
        effective = max(wall, clock.get('server_epoch', wall) + max(0, age) + 1) if fresh else wall
        self.db.execute('BEGIN IMMEDIATE')
        with self.db:
            old = self.db.execute('SELECT high_water,halted FROM supervisor WHERE id=1').fetchone()
            effective = max(effective, old[0] if old else effective)
            state = schedule(datetime.fromtimestamp(effective, timezone.utc), clock_verified=fresh,
                             clock_skew_seconds=clock.get('skew_seconds'))
            halted = bool(old and old[1]) or state['phase'] == 'HALTED'
            if halted:
                state.update(phase='HALTED', allow_new_entry=False, allow_exit=False, allow_cancel=False)
            state.update(halted_latched=halted, active_epoch=wall, orders_sent=0,
                         account_read='NOT_REQUESTED', real_residual='UNKNOWN', automatic_exit=False,
                         alert='REAL_ACCOUNT_AND_SETTLEMENT_NOT_VERIFIED')
            self.db.execute('INSERT OR REPLACE INTO supervisor VALUES(1,?,?,?)',
                            (effective, int(halted), json.dumps(state)))
        # Never hold a SQLite write lock over a network call.
        if private_read:
            try:
                api = SpotReadTransport()
                evidence = {'balances': api.read('balances'), 'open_orders': api.read('open_orders'), 'observed_epoch': time.time()}
                (self.root/'operations/supervisor_private_snapshot.json').write_text(json.dumps(evidence), encoding='utf-8')
                state.update(account_read='SUCCESS_READ_ONLY', real_residual='REQUIRES_ACCOUNT_CLASSIFICATION_AND_MANUAL_RECONCILIATION')
            except BrokerSafetyError:
                state.update(account_read='FAILED_OR_KEY_UNSET', real_residual='UNKNOWN_NO_RETRY')
        (self.root/'operations/supervisor_status.json').write_text(json.dumps(state, indent=2), encoding='utf-8')
        return state

    def close(self):
        self.db.close()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root', default='atlas_store'); p.add_argument('--private-read', action='store_true')
    p.add_argument('--duration', type=float, default=0); p.add_argument('--interval', type=float, default=15)
    a = p.parse_args()
    if a.duration < 0 or a.interval < 1:
        p.error('duration >= 0 and interval >= 1 required')
    supervisor = DeadlineSupervisor(a.root); start = time.monotonic()
    try:
        while True:
            state = supervisor.tick(clock_probe(), private_read=a.private_read)
            print(json.dumps({k: state[k] for k in ('phase', 'clock_verified', 'halted_latched', 'account_read', 'orders_sent')}), flush=True)
            if time.monotonic()-start >= a.duration:
                break
            time.sleep(min(a.interval, max(.1, a.duration-(time.monotonic()-start))))
    finally:
        supervisor.close()


if __name__ == '__main__':
    main()
