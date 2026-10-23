"""Persistent order-state metadata contracts. No financial amounts or transport.

Independent glue over Atlas order-tracker concepts; no external code copied.
UNKNOWN cannot be retried until authoritative read-only reconciliation exists.
"""
import hashlib,json,sqlite3,time
from pathlib import Path

STATES=('NEW','SUBMITTED','ACKNOWLEDGED','PARTIALLY_FILLED','FILLED','CANCELED','REJECTED','UNKNOWN')
TERMINAL={'FILLED','CANCELED','REJECTED'}
NEXT={'NEW':{'SUBMITTED','REJECTED','UNKNOWN'},'SUBMITTED':{'ACKNOWLEDGED','PARTIALLY_FILLED','FILLED','CANCELED','REJECTED','UNKNOWN'},
      'ACKNOWLEDGED':{'PARTIALLY_FILLED','FILLED','CANCELED','UNKNOWN'},'PARTIALLY_FILLED':{'FILLED','CANCELED','UNKNOWN'},
      'UNKNOWN':{'ACKNOWLEDGED','PARTIALLY_FILLED','FILLED','CANCELED','REJECTED'}}

class OrderProtocol:
    def __init__(self,path):
        self.db=sqlite3.connect(Path(path),timeout=20)
        self.db.execute('CREATE TABLE IF NOT EXISTS order_metadata(client_id TEXT PRIMARY KEY,symbol TEXT,side TEXT,fingerprint TEXT,state TEXT,evidence_sha TEXT,updated REAL)');self.db.commit()
    def register(self,client_id,symbol,side):
        if not client_id or len(client_id)>120 or not symbol.endswith('TMN') or not symbol.isalnum() or side not in ('BUY','SELL'):raise ValueError('INVALID_SPOT_IDENTITY')
        fingerprint=hashlib.sha256(json.dumps([client_id,symbol,side]).encode()).hexdigest()
        self.db.execute('BEGIN IMMEDIATE')
        with self.db:
            old=self.db.execute('SELECT fingerprint FROM order_metadata WHERE client_id=?',(client_id,)).fetchone()
            if old:
                if old[0]!=fingerprint:raise ValueError('IDEMPOTENCY_CONFLICT')
                return
            opposite=self.db.execute("SELECT 1 FROM order_metadata WHERE symbol=? AND side!=? AND state NOT IN ('FILLED','CANCELED','REJECTED')",(symbol,side)).fetchone()
            if opposite:raise ValueError('OPPOSING_OR_UNKNOWN_ORDER_RECONCILE_FIRST')
            self.db.execute('INSERT INTO order_metadata VALUES(?,?,?,?,?,?,?)',(client_id,symbol,side,fingerprint,'NEW',None,time.time()))
    def transition(self,client_id,state,evidence_sha):
        if state not in STATES or not isinstance(evidence_sha,str) or len(evidence_sha)!=64 or any(c not in '0123456789abcdef' for c in evidence_sha):raise ValueError('VERIFIABLE_STATE_EVIDENCE_REQUIRED')
        self.db.execute('BEGIN IMMEDIATE')
        with self.db:
            old=self.db.execute('SELECT state FROM order_metadata WHERE client_id=?',(client_id,)).fetchone()
            if not old or (state!=old[0] and state not in NEXT.get(old[0],set())):raise ValueError('INVALID_ORDER_TRANSITION')
            self.db.execute('UPDATE order_metadata SET state=?,evidence_sha=?,updated=? WHERE client_id=?',(state,evidence_sha,time.time(),client_id))
    def retry_allowed(self,client_id):
        # No order transport exists: metadata is never permission to submit/retry.
        return False
    def close(self):self.db.close()
