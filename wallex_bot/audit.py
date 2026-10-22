"""Tamper-evident, durable SQLite event store; records decisions incl HOLD."""
from __future__ import annotations
import sqlite3, hashlib, json, datetime
from pathlib import Path

def canonical(x):
    return json.dumps(x,sort_keys=True,ensure_ascii=False,separators=(',',':'),allow_nan=False)

class AuditStore:
    def __init__(self, path):
        Path(path).parent.mkdir(parents=True,exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('''CREATE TABLE IF NOT EXISTS events(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_time TEXT NOT NULL,
            kind TEXT NOT NULL,
            payload TEXT NOT NULL,
            prev_hash TEXT NOT NULL,
            event_hash TEXT NOT NULL)''')
        self.db.execute('''CREATE TABLE IF NOT EXISTS kv(key TEXT PRIMARY KEY, value TEXT NOT NULL)''')
        self.db.commit()
    def remember(self,key,value):
        self.db.execute('INSERT OR REPLACE INTO kv VALUES(?,?)',(key,canonical(value)))
        self.db.commit()
    def recall(self,key,default=None):
        item=self.db.execute('SELECT value FROM kv WHERE key=?',(key,)).fetchone()
        return json.loads(item[0]) if item else default
    def record(self,kind,payload, event_time=None):
        if event_time is None:
            event_time=datetime.datetime.now(datetime.timezone.utc).isoformat()
        last=self.db.execute('SELECT event_hash FROM events ORDER BY id DESC LIMIT 1').fetchone()
        prev=last[0] if last else 'GENESIS'
        data={'event_time':str(event_time),'kind':kind,'payload':payload,'prev_hash':prev}
        digest=hashlib.sha256(canonical(data).encode()).hexdigest()
        self.db.execute('INSERT INTO events(event_time,kind,payload,prev_hash,event_hash) VALUES (?,?,?,?,?)',
                        (str(event_time),kind,canonical(payload),prev,digest))
        self.db.commit()
        return digest
    def verify(self):
        prev='GENESIS'; n=0
        for at,kind,payload,p,h in self.db.execute('SELECT event_time,kind,payload,prev_hash,event_hash FROM events ORDER BY id'):
            data={'event_time':at,'kind':kind,'payload':json.loads(payload),'prev_hash':p}
            if p!=prev or hashlib.sha256(canonical(data).encode()).hexdigest()!=h:
                return False,n
            prev=h;n+=1
        return True,n
    def close(self):
        # Windows holds WAL/SHM files open while an SQLite handle exists.
        try:
            self.db.execute('PRAGMA wal_checkpoint(TRUNCATE)')
        finally:
            self.db.close()
