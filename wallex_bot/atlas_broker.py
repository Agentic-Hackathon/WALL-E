"""Wallex Atlas broker boundary: persistent PAPER adapter and a hard-disabled live broker.

Source provenance (conceptual only; NO source code copied):
- grid_trading_bot @ fbda3dd5558a168f11e1a9733e12e1d9d8b3e1fc (MIT):
  robustness/circuit-breaker principles.
- Lumibot @ b529372528d2a1bba7f0f5e0183f6b4be8de1d7c (reported GPL-3.0):
  paper/live broker interface idea only; no implementation copied.
- Hummingbot in-flight order tracker is NOT yet audited/ported; future concept only.

No HTTP, order placement, API key reading, leverage, or fabricated quotes.
No live order may be submitted by this version. 'DRY_RUN_BLOCKED' is NOT a fill.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Protocol
import hashlib
import json
import math
import re
import sqlite3


class BrokerSafetyError(RuntimeError):
    """Missing authorization or invalid state: never retry a live submission."""


class IdempotencyConflict(BrokerSafetyError):
    """The same client request identifier was reused with different inputs."""


class OrderState(str, Enum):
    # UNKNOWN is deliberately NOT retry-safe. It requires read-only exchange reconciliation.
    NEW = 'NEW'
    OPEN = 'OPEN'
    PARTIAL = 'PARTIAL'
    FILLED = 'FILLED'
    CANCELLED = 'CANCELLED'
    REJECTED = 'REJECTED'
    UNKNOWN = 'UNKNOWN'
    BLOCKED_DRY_RUN = 'BLOCKED_DRY_RUN'
    PAPER_EXECUTED = 'PAPER_EXECUTED'
    PAPER_NOT_EXECUTED = 'PAPER_NOT_EXECUTED'


# Specification for a future, independently gated exchange adapter.
_ALLOWED_TRANSITIONS = {
    OrderState.NEW: frozenset((OrderState.OPEN, OrderState.PARTIAL, OrderState.FILLED,
                               OrderState.CANCELLED, OrderState.REJECTED, OrderState.UNKNOWN)),
    OrderState.OPEN: frozenset((OrderState.PARTIAL, OrderState.FILLED, OrderState.CANCELLED, OrderState.UNKNOWN)),
    OrderState.PARTIAL: frozenset((OrderState.FILLED, OrderState.CANCELLED, OrderState.UNKNOWN)),
    OrderState.UNKNOWN: frozenset((OrderState.NEW, OrderState.OPEN, OrderState.PARTIAL,
                                   OrderState.FILLED, OrderState.CANCELLED, OrderState.REJECTED)),
    OrderState.BLOCKED_DRY_RUN: frozenset(),
    OrderState.PAPER_EXECUTED: frozenset(),
    OrderState.PAPER_NOT_EXECUTED: frozenset(),
    OrderState.FILLED: frozenset(),
    OrderState.CANCELLED: frozenset(),
    OrderState.REJECTED: frozenset(),
}


def allowed_transition(previous: OrderState, next_state: OrderState) -> bool:
    """Pure state-machine invariant, no market data or simulated fills."""
    a, b = OrderState(previous), OrderState(next_state)
    return a == b or b in _ALLOWED_TRANSITIONS[a]


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'), allow_nan=False)


def _digest(value):
    return hashlib.sha256(_canonical(value).encode('utf8')).hexdigest()


def _utcnow():
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class OrderIntent:
    """Order proposal, NOT exchange authorization or an exchange order.

    AUTO is valid only for the existing PaperAccount strategy/risk decision.
    A real-order API would require a verified quote, fee, organizer allowlist,
    contest subaccount, package restrictions, outstanding orders and exposure.
    Such an API is intentionally NOT provided here.
    """
    client_order_id: str
    symbol: str
    side: str = 'AUTO'
    notional_tmn: float | None = None
    quantity: float | None = None
    limit_price_tmn: float | None = None

    def __post_init__(self):
        if not isinstance(self.client_order_id, str) or not re.fullmatch(r'[A-Za-z0-9:_-]{8,120}', self.client_order_id):
            raise ValueError('Client order identifier required (8..120 safe characters)')
        if not isinstance(self.symbol, str) or not re.fullmatch(r'[A-Z0-9]+TMN', self.symbol):
            raise ValueError('Only spot TMN-quote symbols are accepted at this boundary')
        if self.side not in ('AUTO', 'BUY', 'SELL'):
            raise ValueError('Unsupported spot order side')
        for field_name in ('notional_tmn', 'quantity', 'limit_price_tmn'):
            number = getattr(self, field_name)
            if number is not None and (not isinstance(number, (int, float)) or
                                       isinstance(number, bool) or not math.isfinite(number) or number <= 0):
                raise ValueError('Invalid proposed order '+field_name)
        if self.side == 'AUTO' and any(getattr(self, x) is not None for x in
                                        ('notional_tmn', 'quantity', 'limit_price_tmn')):
            raise ValueError('Automatic shadow-side intent cannot override RiskGate sizing')

    def fingerprint(self):
        return _digest({'client_order_id': self.client_order_id,
                        'symbol': self.symbol, 'side': self.side,
                        'notional_tmn': self.notional_tmn,
                        'quantity': self.quantity, 'limit_price_tmn': self.limit_price_tmn})


@dataclass(frozen=True)
class BrokerReceipt:
    client_order_id: str
    symbol: str
    state: OrderState
    reason: str
    venue: str
    hypothetical: bool
    exchange_order_id: str | None = None


class Broker(Protocol):
    def submit(self, intent: OrderIntent, *, forecast: dict | None = None,
               book: dict | None = None, fee: float | None = None) -> BrokerReceipt: ...
    def cancel(self, client_order_id: str) -> BrokerReceipt: ...
    def status(self, client_order_id: str) -> BrokerReceipt | None: ...
    def balances(self) -> dict: ...
    def reconcile(self) -> dict: ...


class ShadowBroker:
    """Adapter for EXISTING persistent PaperAccount and its sole RiskGate.

    Idempotency is committed *with* the paper cash/position mutation in shadow.sqlite.
    No second price or risk implementation exists here. Genuine book data must
    be passed by the existing real Wallex observation call site.
    """
    def __init__(self, paper_account):
        self.paper = paper_account

    def submit(self, intent: OrderIntent, *, forecast: dict | None = None,
               book: dict | None = None, fee: float | None = None) -> BrokerReceipt:
        if not isinstance(intent, OrderIntent):
            raise TypeError('OrderIntent required')
        if not isinstance(forecast, dict) or not isinstance(book, dict) or fee is None:
            raise BrokerSafetyError('Observed book, model forecast and explicit fee assumption required')
        action = self.paper.trade(intent.symbol, forecast, book, fee,
                                  client_order_id=intent.client_order_id,
                                  expected_side=intent.side)
        executed = action in ('PAPER_BUY', 'PAPER_SELL')
        return BrokerReceipt(intent.client_order_id, intent.symbol,
                             OrderState.PAPER_EXECUTED if executed else OrderState.PAPER_NOT_EXECUTED,
                             action, 'SHADOW_ONLY', True)

    def status(self, client_order_id: str) -> BrokerReceipt | None:
        row = self.paper.db.execute('SELECT symbol,action FROM broker_intents WHERE client_order_id=?',
                                     (client_order_id,)).fetchone()
        if row is None:
            return None
        symbol, action = row
        return BrokerReceipt(client_order_id, symbol,
                             OrderState.PAPER_EXECUTED if action in ('PAPER_BUY', 'PAPER_SELL')
                             else OrderState.PAPER_NOT_EXECUTED, action, 'SHADOW_ONLY', True)

    def cancel(self, client_order_id: str) -> BrokerReceipt:
        old = self.status(client_order_id)
        if old is None:
            raise KeyError('No saved paper intent for cancellation')
        return BrokerReceipt(old.client_order_id, old.symbol, old.state,
                             'PAPER_INSTANTANEOUS_NO_PENDING_EXCHANGE_ORDER', 'SHADOW_ONLY', True)

    def balances(self) -> dict:
        return {'mode': 'HYPOTHETICAL_ONLY', 'cash_tmn': self.paper.get('cash_tmn'),
                'positions': [{'symbol': sym, 'quantity': qty, 'entry_cost_tmn': cost}
                              for sym, qty, cost in self.paper.db.execute(
                                  'SELECT symbol,quantity,entry_cost FROM positions ORDER BY symbol')]}

    def reconcile(self) -> dict:
        if not self.paper.verify():
            raise BrokerSafetyError('Paper audit chain tampered: fail closed')
        return {'mode': 'PAPER_LEDGER_ONLY', 'audit_valid': True,
                'no_exchange_orders_generated': True,
                'intent_count': self.paper.db.execute('SELECT COUNT(*) FROM broker_intents').fetchone()[0]}


class WallexLiveBroker:
    """Durable, intentionally NON-EXECUTING broker skeleton for future audited work.

    No transport object is accepted; there is no method that sends POST/DELETE
    to Wallex. A future separate integration MUST implement verified preflight,
    response ID persistence, read-only order reconciliation and staged release.
    Passing live_enabled=True always fails closed, regardless of environment.
    """
    def __init__(self, root, *, live_enabled: bool = False):
        if live_enabled:
            raise BrokerSafetyError('LIVE TRADING IS NOT IMPLEMENTED OR AUTHORIZED')
        path = Path(root) / 'broker_control.sqlite'
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, timeout=30)
        self.db.execute('PRAGMA busy_timeout=30000')
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS broker_policy(key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS broker_orders(
                client_order_id TEXT PRIMARY KEY, symbol TEXT NOT NULL, side TEXT NOT NULL,
                request_sha256 TEXT NOT NULL, state TEXT NOT NULL, reason TEXT NOT NULL,
                exchange_order_id TEXT, created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS broker_events(
                id INTEGER PRIMARY KEY, at TEXT NOT NULL, client_order_id TEXT NOT NULL,
                event TEXT NOT NULL, payload_json TEXT NOT NULL, prev_hash TEXT NOT NULL,
                event_hash TEXT NOT NULL);
        ''')
        with self.db:
            self.db.execute("INSERT OR IGNORE INTO broker_policy VALUES('kill_switch','ENGAGED')")
        self.db.commit()

    def _append(self, identifier, event, payload):
        at = _utcnow()
        previous_row = self.db.execute('SELECT event_hash FROM broker_events ORDER BY id DESC LIMIT 1').fetchone()
        previous = previous_row[0] if previous_row else 'GENESIS'
        data = _canonical(payload)
        event_hash = hashlib.sha256((previous + '|' + at + '|' + identifier + '|' + event + '|' + data)
                                    .encode('utf8')).hexdigest()
        self.db.execute('INSERT INTO broker_events(at,client_order_id,event,payload_json,prev_hash,event_hash) VALUES(?,?,?,?,?,?)',
                        (at, identifier, event, data, previous, event_hash))

    def verify(self) -> bool:
        previous = 'GENESIS'
        for at, identifier, event, payload, prev, digest in self.db.execute(
                'SELECT at,client_order_id,event,payload_json,prev_hash,event_hash FROM broker_events ORDER BY id'):
            actual = hashlib.sha256((prev + '|' + at + '|' + identifier + '|' + event + '|' + payload)
                                    .encode('utf8')).hexdigest()
            if prev != previous or actual != digest:
                return False
            previous = digest
        return True

    def _require_integrity(self):
        if not self.verify():
            raise BrokerSafetyError('Broker event chain corrupted; halt all order workflows')

    def kill(self, reason: str = 'MANUAL_SAFETY_STOP') -> dict:
        if not isinstance(reason, str) or not re.fullmatch(r'[A-Z0-9_]{4,80}', reason):
            raise ValueError('Bounded safe kill-switch reason required')
        self._require_integrity()
        self.db.execute('BEGIN IMMEDIATE')
        try:
            self.db.execute("UPDATE broker_policy SET value='ENGAGED' WHERE key='kill_switch'")
            self._append('SYSTEM', 'KILL_SWITCH_ENGAGED', {'reason': reason})
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        return {'kill_switch': 'ENGAGED', 'reason': reason, 'live_order_capability': 'ABSENT'}

    def status(self, client_order_id: str) -> BrokerReceipt | None:
        self._require_integrity()
        row = self.db.execute('SELECT symbol,state,reason,exchange_order_id FROM broker_orders WHERE client_order_id=?',
                              (client_order_id,)).fetchone()
        if row is None:
            return None
        symbol, state, reason, exchange_order_id = row
        return BrokerReceipt(client_order_id, symbol, OrderState(state), reason,
                             'WALLEX_LIVE_DISABLED', False, exchange_order_id)

    def submit(self, intent: OrderIntent, *, forecast: dict | None = None,
               book: dict | None = None, fee: float | None = None) -> BrokerReceipt:
        if not isinstance(intent, OrderIntent) or intent.side not in ('BUY', 'SELL'):
            raise ValueError('Explicit BUY/SELL OrderIntent required for live preflight')
        if forecast is not None or book is not None or fee is not None:
            raise BrokerSafetyError('No live order request parameters or transport accepted')
        self._require_integrity()
        # Intent fingerprint covers all order fields, even though no request is sent.
        # No submitted order or hypothetical fill is inferred from this audit entry.
        fingerprint = intent.fingerprint()
        self.db.execute('BEGIN IMMEDIATE')
        try:
            existing = self.db.execute('SELECT request_sha256 FROM broker_orders WHERE client_order_id=?',
                                       (intent.client_order_id,)).fetchone()
            if existing:
                if existing[0] != fingerprint:
                    raise IdempotencyConflict('Same client_order_id with conflicting order intent')
            else:
                self.db.execute('''INSERT INTO broker_orders
                    (client_order_id,symbol,side,request_sha256,state,reason,exchange_order_id,created_at)
                    VALUES(?,?,?,?,?,?,?,?)''', (intent.client_order_id, intent.symbol, intent.side,
                    fingerprint, OrderState.BLOCKED_DRY_RUN.value,
                    'NO_AUTHORIZED_EXCHANGE_ORDER_PATH', None, _utcnow()))
                self._append(intent.client_order_id, 'LIVE_SUBMISSION_BLOCKED',
                             {'symbol': intent.symbol, 'side': intent.side, 'state': 'BLOCKED_DRY_RUN',
                              'reason': 'NO_AUTHORIZED_EXCHANGE_ORDER_PATH',
                              'kill_switch': 'ENGAGED', 'no_exchange_request': True})
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        receipt = self.status(intent.client_order_id)
        assert receipt is not None
        return receipt

    def cancel(self, client_order_id: str) -> BrokerReceipt:
        saved = self.status(client_order_id)
        if saved is None:
            raise BrokerSafetyError('No local order to cancel; no exchange call attempted')
        # No exchange order has ever been submitted by this broker.
        return saved

    def balances(self) -> dict:
        return {'mode': 'LIVE_EXECUTION_DISABLED', 'balances': None,
                'reason': 'Use existing WallexReadClient separately for verified read-only account balances'}

    def reconcile(self) -> dict:
        self._require_integrity()
        rows = self.db.execute('SELECT state,COUNT(*) FROM broker_orders GROUP BY state').fetchall()
        return {'mode': 'PERSISTED_LOCAL_INTENTS_ONLY',
                'remote_reconciliation': 'NOT_IMPLEMENTED_NO_EXCHANGE_ORDER_IDS',
                'order_state_counts': dict(rows), 'kill_switch': 'ENGAGED',
                'audit_valid': True, 'submitted_exchange_orders': 0}

    def close(self):
        self.db.close()


def broker_status(root) -> dict:
    """Read-only status for dashboard/CLI; never creates broker DB on inspection."""
    path = Path(root) / 'broker_control.sqlite'
    if not path.is_file():
        return {'mode': 'DRY_RUN_ONLY', 'broker_control_database_exists': False,
                'live_submission': 'NOT_IMPLEMENTED', 'submitted_exchange_orders': 0}
    broker = WallexLiveBroker(root)
    try:
        return {'broker_control_database_exists': True, **broker.reconcile()}
    finally:
        broker.close()
