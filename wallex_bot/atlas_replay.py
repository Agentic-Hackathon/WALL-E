"""Stage 8: deterministic READ-ONLY replay of previously recorded RiskGate decisions.

Conceptual provenance: event-sourced deterministic replay in NautilusTrader,
see reference_projects_integration_playbook.md and third_party/SOURCES.md.
Entire implementation independently authored: NO third-party code was copied.

This is a replay of RiskGate on the originally recorded observations and ledger
state. It does NOT regenerate past model forecasts, re-fetch past books, run an
LLM, validate actual order fills, or re-run a full historical strategy.
"""
from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any
import hashlib
import json
import sqlite3

from .atlas_risk import RiskGate

PROTOCOL='ATLAS_RISK_REPLAY_V1'


def _canonical(value: Any) -> str:
    return json.dumps(value,sort_keys=True,ensure_ascii=False,
                      separators=(',',':'),allow_nan=False)


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def _risk_source_hash() -> str:
    return hashlib.sha256(Path(__file__).with_name('atlas_risk.py').read_bytes()).hexdigest()


def _read_only_events(db: sqlite3.Connection):
    previous='GENESIS'
    count=0
    for row in db.execute('''SELECT id,observed_at,symbol,action,payload,prev_hash,hash
                              FROM events ORDER BY id'''):
        identity,at,sym,action,payload,prev,h=row
        if prev!=previous or _sha(prev+'|'+at+'|'+sym+'|'+action+'|'+payload)!=h:
            return None,count
        previous=h
        count+=1
    return previous,count


def replay_decision(root, *, event_id: int | None = None) -> dict:
    """Return an auditable result without creating, changing or querying live data.

    At least one complete Stage-8 replay envelope must have been recorded by
    genuine Shadow execution. An older event cannot be silently reconstructed.
    The entire existing paper hash chain must be intact before replay.
    """
    if event_id is not None and (type(event_id) is not int or event_id<1):
        raise ValueError('event_id must be a positive existing integer')
    path=Path(root)/'shadow.sqlite'
    result={'mode':'READ_ONLY_RISK_GATE_REPLAY','exchange_orders':0,
            'no_market_or_model_requests':True,'read_only':True,
            'paper_fills_are_hypothetical':True}
    if not path.is_file():
        return {**result,'status':'NO_EXISTING_SHADOW_LEDGER'}
    db=sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True,timeout=10)
    try:
        db.execute('PRAGMA query_only=ON')
        try:
            final_hash,count=_read_only_events(db)
        except sqlite3.DatabaseError:
            return {**result,'status':'LEDGER_UNREADABLE'}
        if final_hash is None:
            return {**result,'status':'AUDIT_HASH_CHAIN_INVALID','events_checked_before_failure':count}
        if event_id is None:
            # Prefer the latest recorded RiskGate snapshot, not a later generic
            # network error or explanatory event lacking the pre-trade state.
            # If no replayable row exists, return the newest legacy event and
            # explicitly refuse to infer inputs from future or current data.
            candidates=db.execute("""SELECT id,observed_at,symbol,action,payload,hash FROM events
                WHERE action NOT IN ('MULTI_AGENT_EXPLANATION','FRESH_REAL_BID_MARK_TO_MARKET')
                ORDER BY id DESC""")
            row=None
            legacy=None
            for candidate in candidates:
                if legacy is None:legacy=candidate
                try:
                    obj=json.loads(candidate[4])
                    if isinstance(obj,dict) and 'risk_replay_inputs' in obj:
                        row=candidate
                        break
                except (TypeError,ValueError):
                    continue
            if row is None:row=legacy
        else:
            row=db.execute("SELECT id,observed_at,symbol,action,payload,hash FROM events WHERE id=?",
                           (event_id,)).fetchone()
        if row is None:
            return {**result,'status':'EVENT_NOT_FOUND','events_verified':count}
        event_id,at,symbol,recorded_action,raw,receipt_hash=row
        base={**result,'event_id':event_id,'observed_at_utc':at,'symbol':symbol,
              'recorded_action':recorded_action,'event_hash':receipt_hash,'events_verified':count}
        try:
            payload=json.loads(raw)
        except (ValueError,TypeError):
            return {**base,'status':'INVALID_EVENT_PAYLOAD'}
        if not isinstance(payload,dict):
            return {**base,'status':'INVALID_EVENT_PAYLOAD'}
        snapshot=payload.get('risk_replay_inputs')
        expected_hash=payload.get('risk_replay_sha256')
        if not isinstance(snapshot,dict) or not isinstance(expected_hash,str):
            return {**base,'status':'LEGACY_NO_RISK_SNAPSHOT',
                    'reason':'Event predates Stage 8; original pre-trade state cannot be reconstructed'}
        try:
            if _sha(_canonical(snapshot))!=expected_hash:
                return {**base,'status':'SNAPSHOT_HASH_MISMATCH'}
        except (ValueError,TypeError):
            return {**base,'status':'INVALID_REPLAY_SNAPSHOT'}
        if snapshot.get('protocol')!=PROTOCOL or snapshot.get('symbol')!=symbol:
            return {**base,'status':'UNRECOGNIZED_REPLAY_PROTOCOL'}
        recorded_code_hash=snapshot.get('risk_source_sha256')
        current_code_hash=_risk_source_hash()
        if recorded_code_hash!=current_code_hash:
            return {**base,'status':'RISK_CODE_VERSION_MISMATCH',
                    'recorded_risk_sha256':recorded_code_hash,
                    'current_risk_sha256':current_code_hash}
        gate=RiskGate()
        if snapshot.get('policy_limits')!=asdict(gate.limits):
            return {**base,'status':'RISK_POLICY_VERSION_MISMATCH'}
        if (snapshot.get('expected_side') not in ('AUTO','BUY','SELL') or
            snapshot.get('purpose') not in ('STRATEGY','FINAL_TMN') or
            not isinstance(snapshot.get('positions'),list) or
            not isinstance(snapshot.get('stopped'),bool)):
            return {**base,'status':'INVALID_REPLAY_SNAPSHOT'}
        try:
            if snapshot['purpose']=='FINAL_TMN':
                decision=gate.final_tmn_liquidation(
                    symbol,snapshot['book'],snapshot['cash_tmn'],snapshot['positions'],
                    snapshot['fee_assumption'])
            else:
                decision=gate.evaluate(symbol,snapshot['forecast'],snapshot['book'],
                    snapshot['cash_tmn'],snapshot['positions'],snapshot['stopped'],
                    snapshot['fee_assumption'])
        except (KeyError,TypeError,ValueError,OverflowError):
            return {**base,'status':'INVALID_REPLAY_SNAPSHOT'}
        computed_action=decision.action
        if ((snapshot['expected_side']=='BUY' and computed_action=='PAPER_SELL') or
            (snapshot['expected_side']=='SELL' and computed_action=='PAPER_BUY')):
            computed_action='BROKER_SIDE_MISMATCH_NO_ORDER'
        matched=(snapshot.get('gate_decision')==decision.audit_payload() and
                 recorded_action==computed_action and
                 payload.get('risk_gate')==decision.audit_payload())
        return {**base,'status':'MATCH' if matched else 'DECISION_DIVERGENCE',
                'recomputed_action':computed_action,
                'risk_reason':decision.reason,
                'recorded_risk_sha256':recorded_code_hash,
                'snapshot_sha256':expected_hash,
                'model_sha256_recorded_not_reexecuted':snapshot.get('model_sha256'),
                'risk_gate_deterministically_recomputed':True,
                'full_model_or_execution_replay':False,
                'why':'Same recorded pre-trade state, RiskGate source hash and policy; no external calls'}
    finally:
        db.close()
