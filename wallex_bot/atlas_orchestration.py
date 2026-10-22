"""M6 shared Watch/Agent adapter and immutable decision evidence ledger.

TradingAgents role separation and Nautilus state-only replay are conceptual
references (SOURCES.md). Original independent code; no external implementation.
"""
import json,sqlite3,time
from pathlib import Path
from .atlas_forward import _sha,_canon
from .atlas_review import review
from .atlas_mode import require_mode,ExecutionMode

class DecisionLedger:
    def __init__(self,root):
        self.db=sqlite3.connect(Path(root)/'agent_evidence.sqlite',timeout=30)
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('''CREATE TABLE IF NOT EXISTS decisions_v6(
            decision_id TEXT PRIMARY KEY,created REAL NOT NULL,symbol TEXT NOT NULL,
            evidence TEXT NOT NULL,review TEXT NOT NULL,action TEXT NOT NULL,risk_replay TEXT,
            receipt_hash TEXT NOT NULL)''');self.db.commit()
    def record(self,evidence,result,action,risk_replay=None):
        key=result['proposal']['source_evidence_hash']
        payload={'evidence':evidence,'review':result,'action':action,'risk_replay':risk_replay}
        sha=_sha(payload)
        with self.db:
            old=self.db.execute('SELECT receipt_hash FROM decisions_v6 WHERE decision_id=?',(key,)).fetchone()
            if old and old[0]!=sha:raise ValueError('DECISION_IDEMPOTENCY_CONFLICT')
            self.db.execute('INSERT OR IGNORE INTO decisions_v6 VALUES(?,?,?,?,?,?,?,?)',(key,time.time(),evidence['symbol'],_canon(evidence),_canon(result),action,_canon(risk_replay),sha))
        return key
    def replay(self):
        results=[]
        for key,raw,stored,action,risk,sha in self.db.execute('SELECT decision_id,evidence,review,action,risk_replay,receipt_hash FROM decisions_v6 ORDER BY created'):
            evidence=json.loads(raw);original=json.loads(stored);inputs=json.loads(risk)
            valid=_sha({'evidence':evidence,'review':original,'action':action,'risk_replay':inputs})==sha
            repeated=review(evidence);gate_equal=None
            if inputs:
                from .atlas_risk import RiskGate,RiskLimits
                from dataclasses import asdict
                gate=RiskGate(RiskLimits(**inputs['policy_limits']))
                gate_equal=asdict(gate.evaluate(inputs['symbol'],inputs['forecast'],inputs['book'],inputs['cash_tmn'],inputs['positions'],inputs['stopped'],inputs['fee_assumption']))==inputs['gate_decision']
            results.append({'decision_id':key,'receipt_valid':valid,'review_identical':repeated==original,'risk_gate_identical':gate_equal,
                'action':action,'replay_authority':'NONE_NO_BROKER_NO_NETWORK_NO_MEMORY_WRITES'})
        return results
    def close(self):self.db.close()

def run_assets(lake,*,top=8,fee=.001,mode=ExecutionMode.SHADOW,allowed_symbols=None,models_dir=None):
    require_mode(mode,permitted=(ExecutionMode.SHADOW,),operation='shared_watch_agent_cycle')
    if models_dir is not None and Path(models_dir).resolve()!=(Path(lake.root)/'models').resolve():raise ValueError('CHAMPION_DIRECTORY_OVERRIDE_DISABLED')
    from .atlas_agent import cycle
    from .atlas_data_sync import DataSyncManager
    ranked=DataSyncManager(lake)._priority_symbols(top if allowed_symbols is None else 10000,'priority')
    if allowed_symbols is not None:
        allowed=set(allowed_symbols)
        if not allowed or any(not isinstance(s,str) or not s.isalnum() or s!=s.upper() for s in allowed):raise ValueError('INVALID_SYMBOL_SELECTION')
        ranked=[s for s in ranked if s in allowed][:top]
    events=[]
    for symbol in ranked:
        try:
            result=cycle(lake,symbol=symbol,thread_id='shared-'+symbol,fee=fee,mode=mode)
            events.append({'symbol':symbol,'action':result['decision'],'shared_contract':True,'result':result})
        except Exception as exc:events.append({'symbol':symbol,'action':'REJECTED','reason':type(exc).__name__,'shared_contract':True})
    return {'mode':'SHADOW_ONLY_NO_REAL_ORDERS','events':events,'contract':'ATLAS_SHARED_AGENT_WATCH_REVIEW_V1'}
