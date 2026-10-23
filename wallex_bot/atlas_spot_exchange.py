"""Independent Spot adapter; official developers.wallex.ir spot-* contracts.

No trading framework source copied. Hummingbot tracker concepts were reviewed
at the Apache-2.0 revision recorded in third_party/SOURCES.md. Existing
OrderIntent/RiskGate are reused, not modified. This release is NOT armed:
authenticated transport is READ-ONLY until account-specific authorization and
real financial end-to-end evidence are reviewed in a separate release.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from pathlib import Path
import hashlib
import json
import os
import re
import sqlite3
import time
import requests

from .atlas_broker import BrokerSafetyError, IdempotencyConflict, OrderIntent
from .atlas_risk import RiskGate

STATES = ('CREATED', 'SUBMITTED', 'ACKNOWLEDGED', 'OPEN', 'PARTIALLY_FILLED',
          'FILLED', 'CANCEL_PENDING', 'CANCELLED', 'REJECTED', 'UNKNOWN')
TERMINAL = {'FILLED', 'CANCELLED', 'REJECTED'}
MODES = ('READ_ONLY', 'SHADOW', 'LIVE_PREFLIGHT', 'LIVE_READY', 'LIVE_ARMED',
         'EXIT_ONLY', 'HALTED', 'BLOCKED')


def decimal(value, *, zero=False):
    # Binary floats are not accepted at the wire boundary.
    if isinstance(value, (float, bool)):
        raise ValueError('DECIMAL_STRING_REQUIRED')
    try:
        number = Decimal(value)
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError('INVALID_DECIMAL') from None
    if not number.is_finite() or number < 0 or (not zero and number == 0):
        raise ValueError('INVALID_DECIMAL')
    return number


def wire_order(intent, *, price, quantity, tick, step, minimum_quantity, minimum_notional):
    """Exact LIMIT serialization; never silently round/change the approved intent.

    Limits must come from separately verified account/market evidence. Public
    decimal precision alone is NOT proof of a minimum notional or tick size.
    """
    if not isinstance(intent, OrderIntent) or intent.side not in ('BUY', 'SELL'):
        raise ValueError('EXPLICIT_SPOT_INTENT_REQUIRED')
    if not re.fullmatch(r'[A-Za-z0-9_]{8,64}', intent.client_order_id):
        raise ValueError('WALLEX_CLIENT_ID_REQUIRES_ALPHANUMERIC_UNDERSCORE')
    p, q, t, s, mq, mn = map(decimal, (price, quantity, tick, step, minimum_quantity, minimum_notional))
    if p % t or q % s:
        raise ValueError('PRICE_OR_QUANTITY_OFF_GRID')
    if q < mq or p * q < mn:
        raise ValueError('BELOW_VERIFIED_MARKET_MINIMUM')
    return {'client_id': intent.client_order_id, 'symbol': intent.symbol,
            'side': intent.side, 'type': 'LIMIT', 'price': format(p, 'f'), 'quantity': format(q, 'f')}


class SpotReadTransport:
    """Fixed-host GET only; no redirects, retries, secret files or mutation API."""
    def read(self, resource, client_id=None):
        paths = {'balances': '/v1/account/balances-detail', 'fees': '/v1/account/fee',
                 'open_orders': '/v1/account/openOrders', 'order': '/v1/account/orders/'}
        if resource not in paths:
            raise BrokerSafetyError('READ_ENDPOINT_NOT_ALLOWED')
        key = os.environ.get('WALLEX_API_KEY')
        if not key:
            raise BrokerSafetyError('WALLEX_API_KEY_UNSET')
        path = paths[resource]
        if resource == 'order':
            if not isinstance(client_id, str) or not re.fullmatch(r'[A-Za-z0-9_]{8,64}', client_id):
                raise ValueError('INVALID_CLIENT_ID')
            path += client_id
        try:
            r = requests.get('https://api.wallex.ir' + path,
                             headers={'x-api-key': key, 'Accept': 'application/json'},
                             timeout=(5, 15), allow_redirects=False)
            if r.status_code != 200:
                raise BrokerSafetyError('PRIVATE_READ_UNSUCCESSFUL_STATUS')
            payload = r.json()
            if payload.get('success') is not True or 'result' not in payload:
                raise BrokerSafetyError('PRIVATE_READ_SCHEMA_UNVERIFIED')
            return payload
        except (requests.RequestException, ValueError):
            raise BrokerSafetyError('PRIVATE_READ_FAILED_NO_RETRY') from None


class SpotLedger:
    """Persistent client-id identity and cumulative exchange observations.

    UNKNOWN is sticky until a matching authoritative order read succeeds.
    Never reconstruct cash from an unobserved fill; balances are read separately.
    Each cumulative snapshot replaces (not adds to) its prior execution totals.
    """
    def __init__(self, root):
        folder = Path(root) / 'operations'; folder.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(folder / 'spot_exchange.sqlite', timeout=20)
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.executescript('''
          CREATE TABLE IF NOT EXISTS spot_orders(client_id TEXT PRIMARY KEY,
            symbol TEXT NOT NULL, side TEXT NOT NULL, fingerprint TEXT NOT NULL,
            state TEXT NOT NULL, payload TEXT NOT NULL, exchange_snapshot TEXT,
            observed REAL, executed_qty TEXT, executed_sum TEXT);
          CREATE TABLE IF NOT EXISTS spot_audit(id INTEGER PRIMARY KEY, client_id TEXT,
            state TEXT, at REAL, sha256 TEXT, previous TEXT, digest TEXT);
        ''')
        self._require_integrity()
        # Crash after durable SUBMITTED but before response is UNKNOWN, not retryable.
        with self.db:
            for row in self.db.execute("SELECT client_id FROM spot_orders WHERE state IN ('SUBMITTED','CANCEL_PENDING')").fetchall():
                self._state(row[0], 'UNKNOWN', 'RESTART_REQUIRES_EXCHANGE_READ')

    def _state(self, client_id, state, evidence):
        if state not in STATES:
            raise ValueError('INVALID_STATE')
        sha = hashlib.sha256(evidence.encode()).hexdigest(); at = time.time()
        row = self.db.execute('SELECT digest FROM spot_audit ORDER BY id DESC LIMIT 1').fetchone()
        previous = row[0] if row else 'GENESIS'
        digest = hashlib.sha256(json.dumps([previous, client_id, state, at, sha]).encode()).hexdigest()
        self.db.execute('INSERT INTO spot_audit(client_id,state,at,sha256,previous,digest) VALUES(?,?,?,?,?,?)',
                        (client_id, state, at, sha, previous, digest))
        self.db.execute('UPDATE spot_orders SET state=? WHERE client_id=?', (state, client_id))

    def _require_integrity(self):
        previous='GENESIS';latest={}
        for row in self.db.execute('SELECT client_id,state,at,sha256,previous,digest FROM spot_audit ORDER BY id'):
            client_id,state,at,sha,prev,digest=row
            actual=hashlib.sha256(json.dumps([previous,client_id,state,at,sha]).encode()).hexdigest()
            if previous!=prev or actual!=digest:
                raise BrokerSafetyError('SPOT_AUDIT_CHAIN_INVALID')
            previous=digest;latest[client_id]=state
        for row in self.db.execute('SELECT client_id,fingerprint,state,payload,exchange_snapshot FROM spot_orders'):
            if latest.get(row[0])!=row[2] or hashlib.sha256(row[3].encode()).hexdigest()!=row[1]:
                raise BrokerSafetyError('SPOT_ORDER_INTEGRITY_INVALID')
            if row[4]:
                sha=hashlib.sha256(row[4].encode()).hexdigest()
                if not self.db.execute('SELECT 1 FROM spot_audit WHERE client_id=? AND sha256=?',(row[0],sha)).fetchone():
                    raise BrokerSafetyError('SPOT_EXCHANGE_SNAPSHOT_NOT_BOUND_TO_AUDIT')

    def register(self, payload):
        raw = json.dumps(payload, sort_keys=True, separators=(',', ':')); sha = hashlib.sha256(raw.encode()).hexdigest()
        self.db.execute('BEGIN IMMEDIATE')
        with self.db:
            self._require_integrity()
            old = self.db.execute('SELECT fingerprint FROM spot_orders WHERE client_id=?', (payload['client_id'],)).fetchone()
            if old:
                if old[0] != sha:
                    raise IdempotencyConflict('IDEMPOTENCY_CONFLICT')
                return False
            if self.db.execute("SELECT 1 FROM spot_orders WHERE symbol=? AND state NOT IN ('FILLED','CANCELLED','REJECTED')",
                               (payload['symbol'],)).fetchone():
                raise BrokerSafetyError('PENDING_OR_UNKNOWN_MARKET_ORDER_RECONCILE_FIRST')
            self.db.execute('INSERT INTO spot_orders(client_id,symbol,side,fingerprint,state,payload) VALUES(?,?,?,?,?,?)',
                            (payload['client_id'], payload['symbol'], payload['side'], sha, 'CREATED', raw))
            self._state(payload['client_id'], 'CREATED', raw)
        return True

    def observe(self, client_id, response):
        """Only an actual read response should be supplied, never a Shadow fill."""
        self.db.execute('BEGIN IMMEDIATE')
        with self.db:
            self._require_integrity()
            return self._observe_locked(client_id,response)

    def _observe_locked(self,client_id,response):
        raw = json.dumps(response, sort_keys=True, separators=(',', ':'), allow_nan=False)
        p = response.get('result')
        row = self.db.execute('SELECT * FROM spot_orders WHERE client_id=?', (client_id,)).fetchone()
        if not row or response.get('success') is not True or not isinstance(p, dict):
            raise BrokerSafetyError('UNVERIFIED_EXCHANGE_RESPONSE')
        requested = json.loads(row['payload'])
        if any(p.get(k) != requested[k] for k in ('symbol', 'side', 'type')) or p.get('clientOrderId') != client_id:
            raise BrokerSafetyError('EXCHANGE_ORDER_IDENTITY_MISMATCH')
        original = decimal(p.get('origQty')); executed = decimal(p.get('executedQty'), zero=True)
        total = decimal(p.get('executedSum'), zero=True)
        if original != decimal(requested['quantity']) or executed > original:
            raise BrokerSafetyError('EXCHANGE_QUANTITY_MISMATCH')
        if row['executed_qty'] is not None and (executed < decimal(row['executed_qty'], zero=True) or total < decimal(row['executed_sum'], zero=True)):
            raise BrokerSafetyError('REGRESSING_CUMULATIVE_EXECUTION')
        fills = p.get('fills')
        if not isinstance(fills, list):
            raise BrokerSafetyError('MISSING_FILL_DETAILS')
        fill_qty = Decimal(0); fill_sum = Decimal(0); fees = {}
        for fill in fills:
            if fill.get('symbol') != row['symbol'] or not isinstance(fill.get('feeAsset'), str):
                raise BrokerSafetyError('INVALID_FILL_IDENTITY')
            fill_qty += decimal(fill.get('quantity')); fill_sum += decimal(fill.get('sum'))
            fill_price=decimal(fill.get('price'));limit=decimal(requested['price'])
            if (row['side']=='BUY' and fill_price>limit) or (row['side']=='SELL' and fill_price<limit):
                raise BrokerSafetyError('FILL_PRICE_VIOLATES_LIMIT')
            fee = decimal(fill.get('fee'), zero=True)
            fees[fill['feeAsset']] = fees.get(fill['feeAsset'], Decimal(0)) + fee
        if fill_qty != executed or fill_sum != total:
            raise BrokerSafetyError('INCOMPLETE_CUMULATIVE_FILL_DETAILS')
        status = p.get('status')
        # Official docs use both FINISHED and FILLED. Completion is inferred only
        # from exact cumulative quantities, never from a vague terminal label.
        if executed == original:
            state = 'FILLED'
        elif status in ('CANCELED', 'CANCELLED') and p.get('active') is False:
            state = 'CANCELLED'
        elif p.get('active') is True:
            state = 'PARTIALLY_FILLED' if executed else 'OPEN'
        elif status == 'REJECTED' and not executed:
            state = 'REJECTED'
        else:
            state = 'UNKNOWN'
        if row['state'] in TERMINAL and row['state'] != state:
            raise BrokerSafetyError('TERMINAL_STATE_CONFLICT_MANUAL_REVIEW')
        self.db.execute('UPDATE spot_orders SET exchange_snapshot=?,observed=?,executed_qty=?,executed_sum=? WHERE client_id=?',
                        (raw, time.time(), str(executed), str(total), client_id))
        self._state(client_id, state, raw)
        return {'state': state, 'fees_by_asset': {k: str(v) for k, v in fees.items()},
                'executed_qty': str(executed), 'executed_sum': str(total),
                'balance_conservation': 'REQUIRES_INDEPENDENT_ACCOUNT_RECONCILIATION'}

    def status(self, client_id):
        row = self.db.execute('SELECT client_id,symbol,side,state,observed,executed_qty,executed_sum FROM spot_orders WHERE client_id=?', (client_id,)).fetchone()
        return dict(row) if row else None

    def close(self):
        self.db.close()


class RealSpotBroker:
    """Account-isolated preflight/read/recovery adapter, NOT a released trader.

    There is deliberately no boolean, environment variable or browser endpoint
    to grant LIVE_ARMED. The unresolved contest identity/market authorization and
    missing real-fill E2E evidence must not be replaced by caller-supplied flags.
    Existing WallexLiveBroker remains HARD_DISABLED and unchanged.
    """
    def __init__(self, root):
        self.root = Path(root); self.ledger = SpotLedger(root)
        self.transport = SpotReadTransport(); self.gate = RiskGate()
        self.mode = 'BLOCKED'

    def preview(self, intent, *, market_limits, price, quantity, forecast, book,
                cash_tmn, positions, stopped, fee):
        payload = wire_order(intent, price=price, quantity=quantity, **market_limits)
        rows = list(positions)
        decision = self.gate.evaluate(intent.symbol, forecast, book, cash_tmn, rows, stopped, fee)
        required = 'PAPER_BUY' if intent.side == 'BUY' else 'PAPER_SELL'
        if decision.action != required:
            raise BrokerSafetyError('RISK_VETO:' + decision.reason)
        q = decimal(quantity); p = decimal(price)
        if intent.side == 'BUY':
            if p * q > Decimal(str(decision.notional_tmn)) or p*q*(1+Decimal(str(fee))) > Decimal(str(cash_tmn)):
                raise BrokerSafetyError('RISK_APPROVED_BUDGET_EXCEEDED')
        else:
            held = next((Decimal(str(r[1])) for r in rows if r[0] == intent.symbol), Decimal(0))
            if q > held:
                raise BrokerSafetyError('SPOT_SELL_EXCEEDS_HELD_QUANTITY')
        return {'payload': payload, 'risk': decision.audit_payload(), 'mode': self.mode,
                'executable': False, 'reason': 'ACCOUNT_AUTHORIZATION_AND_FINANCIAL_E2E_NOT_VERIFIED'}

    def submit(self, intent, **kwargs):
        raise BrokerSafetyError('LIVE_HARD_DISABLED_NO_OPERATOR_ARM_OR_ACCOUNT_AUTHORIZATION')

    def cancel(self, client_order_id):
        raise BrokerSafetyError('LIVE_CANCEL_NOT_AUTHORIZED_USE_READ_ONLY_RECONCILIATION')

    def status(self, client_order_id):
        return self.ledger.status(client_order_id)

    def balances(self):
        return self.transport.read('balances')

    def reconcile(self):
        result = []
        for row in self.ledger.db.execute("SELECT client_id FROM spot_orders WHERE state!='CREATED'").fetchall():
            try:
                result.append(self.ledger.observe(row[0], self.transport.read('order', row[0])))
            except BrokerSafetyError:
                with self.ledger.db:
                    self.ledger._state(row[0], 'UNKNOWN', 'READ_FAILED_OR_SCHEMA_UNVERIFIED')
                result.append({'state': 'UNKNOWN', 'retry_allowed': False})
        return {'orders': result, 'open_orders_response': self.transport.read('open_orders'),
                'balances_response': self.balances(), 'automatic_retry': False,
                'settlement_guaranteed': False}

    def close(self):
        self.ledger.close()
