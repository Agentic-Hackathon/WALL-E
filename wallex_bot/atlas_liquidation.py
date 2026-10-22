"""End-of-watch spot/TMN PAPER liquidation through existing Broker and RiskGate.

Source: Wallex hackathon rule: finish with realized TMN, not held coins.
Conceptual inspiration only: risk-first gate (trading-bot @
688087e64f79f545c7e40ee6e889c9ce92e03693, no license) and durable
execution safeguards (grid_trading_bot @ fbda3dd5558a168f11e1a9733e12e1d9d8b3e1fc, MIT).
NO copied third-party code, no synthetic prices, no model overrides, no private
API access, no actual Wallex trade, cancel or withdrawal endpoints.

A sell at an actually observed top-of-book bid is a *hypothetical* paper
mutation, NOT a guaranteed fill. The future live closeout requires real
exchange order status, lot-size and fees verification, and reconciliation.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import math
import os
import tempfile
import sqlite3
import time

from .atlas_broker import BrokerSafetyError, OrderIntent, ShadowBroker
from .atlas_shadow import PaperAccount
from . import market
from .live_scout import _levels  # parse genuine Wallex order-book levels, not mocked quotes


def _utcnow():
    return datetime.now(timezone.utc).isoformat()


def _canonical(obj):
    return json.dumps(obj, sort_keys=True, ensure_ascii=False,
                      separators=(',', ':'), allow_nan=False)


def _save_atomic(path, obj):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, intermediate = tempfile.mkstemp(prefix='.' + path.name + '-', suffix='.partial',
                                        dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf8') as handle:
            handle.write(json.dumps(obj, indent=2, ensure_ascii=False, allow_nan=False))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(intermediate, path)
    finally:
        if os.path.exists(intermediate):
            os.unlink(intermediate)


def _session(root, *, deadline_required):
    f = Path(root) / 'watch_session.json'
    if not f.is_file():
        if deadline_required:
            raise BrokerSafetyError('No persisted watch session; final paper liquidation refused')
        return None
    data = json.loads(f.read_text(encoding='utf8'))
    if not isinstance(data, dict):
        raise BrokerSafetyError('Watch session is not a valid object')
    if deadline_required:
        try:
            start = float(data['started_epoch'])
            deadline = float(data['deadline_epoch'])
            hours = float(data['hours'])
        except (KeyError, TypeError, ValueError, OverflowError):
            raise BrokerSafetyError('Incomplete watch deadline; fail closed') from None
        if (not all(math.isfinite(x) for x in (start, deadline, hours)) or
                not 1 <= hours <= 72 or abs(deadline-start-hours*3600) > 1 or
                time.time() < deadline):
            raise BrokerSafetyError('Watch deadline not reached or invalid; paper liquidation refused')
    return data


def liquidation_status(root) -> dict:
    """Strictly READ-ONLY status; never creates the shadow ledger or calls Wallex."""
    root = Path(root)
    state = _session(root, deadline_required=False)
    report = {'mode': 'PAPER_STATUS_READ_ONLY',
              'live_order_submission': 'ABSENT',
              'watch_status': state.get('status') if state else 'NO_SESSION',
              'deadline_epoch': state.get('deadline_epoch') if state else None,
              'paper_positions': [], 'paper_cash_tmn': None,
              'real_contest_balance': 'NOT_QUERIED_BY_THIS_COMMAND'}
    path = root / 'shadow.sqlite'
    if not path.is_file():
        report['status'] = 'NO_EXISTING_PAPER_LEDGER'
        return report
    con = sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)
    try:
        cash = con.execute("SELECT value FROM kv WHERE key='cash_tmn'").fetchone()
        report['paper_cash_tmn'] = float(cash[0]) if cash else None
        report['paper_positions'] = [
            {'symbol': sym, 'quantity': qty, 'entry_cost_tmn': cost}
            for sym, qty, cost in con.execute('SELECT symbol,quantity,entry_cost FROM positions ORDER BY symbol')]
        prev = 'GENESIS'
        integrity = True
        for at, sym, action, payload, previous, digest in con.execute(
                'SELECT observed_at,symbol,action,payload,prev_hash,hash FROM events ORDER BY id'):
            computed = hashlib.sha256((previous+'|'+at+'|'+sym+'|'+action+'|'+payload).encode()).hexdigest()
            if previous != prev or computed != digest:
                integrity = False
                break
            prev = digest
        report['paper_hash_chain_valid'] = integrity
    finally:
        con.close()
    report['status'] = ('PAPER_AUDIT_INVALID' if not report['paper_hash_chain_valid'] else
                        ('PAPER_FLAT' if not report['paper_positions'] else 'PAPER_POSITIONS_REMAIN'))
    return report


def _observed_exit_book(raw, quantity):
    """Verify actual best bid has enough displayed quantity for a FULL paper exit.

    The existing PaperAccount uses the top bid for the entire sell; never
    assign that price to more quantity than was actually displayed there.
    """
    bids = _levels(raw, 'bid')
    asks = _levels(raw, 'ask')
    bid, at_bid = bids[0]
    ask = asks[0][0]
    if ask <= bid:
        raise ValueError('Invalid crossed or locked observed order book')
    mid = (ask + bid) / 2
    if not math.isfinite(mid) or mid <= 0:
        raise ValueError('Invalid observed best bid/ask')
    return {'best_bid_tmn': bid,
            'best_ask_tmn': ask,
            'best_bid_quantity': at_bid,
            'spread_bps': (ask-bid)/mid*10000,
            'top5_ask_notional_tmn': sum(price*q for price,q in asks[:5]),
            'top5_bid_notional_tmn': sum(price*q for price,q in bids[:5]),
            'held_quantity_temporary_for_gate': quantity}


def liquidate_paper_positions(lake, *, fee=.001, require_watch_deadline=True,
                              max_fetch_seconds=15.0):
    """Close paper holdings once, using actual newly queried Wallex bid depth.

    On missing/invalid quotes, record a failure and RETAIN the position.
    Retrying after a fresh observation uses an evidence-derived client ID;
    duplicate submissions with identical evidence remain atomic and safe.
    There is *no real-order transport* or fabricated market fixture.
    """
    if not isinstance(fee, (float, int)) or isinstance(fee, bool) or not math.isfinite(fee) or not 0 <= fee < .05:
        raise ValueError('Explicit finite research fee required; NOT an exchange-verified fee')
    if not isinstance(max_fetch_seconds, (int, float)) or not 0 < max_fetch_seconds <= 30:
        raise ValueError('Invalid maximum observation fetch age')
    session = _session(lake.root, deadline_required=require_watch_deadline)
    session_id = str(session.get('started_epoch')) if session else 'NO_WATCH_SESSION'
    paper = PaperAccount(lake)
    observations = []
    try:
        if not paper.verify():
            raise BrokerSafetyError('Paper audit chain invalid; no liquidation allowed')
        broker = ShadowBroker(paper)
        existing = paper.db.execute('SELECT symbol,quantity,entry_cost FROM positions ORDER BY symbol').fetchall()
        for symbol, quantity, entry_cost in existing:
            event = {'symbol': symbol, 'type': 'PAPER_TMN_CLOSEOUT',
                     'not_a_real_fill': True, 'fee_assumption': fee}
            try:
                if not isinstance(symbol, str) or not symbol.endswith('TMN') or not symbol.isalnum():
                    raise BrokerSafetyError('Non-TMN or invalid position; fail closed')
                if (not isinstance(quantity, (float,int)) or not math.isfinite(quantity) or quantity <= 0 or
                        not isinstance(entry_cost, (float,int)) or not math.isfinite(entry_cost) or entry_cost <= 0):
                    raise BrokerSafetyError('Corrupt paper position; fail closed')
                begun = time.monotonic()
                # ONLY actual API returns; no injected prices or fallback to last close.
                raw = market.depth(symbol)
                took = time.monotonic() - begun
                if took > max_fetch_seconds:
                    raise BrokerSafetyError('Book request exceeded bounded freshness; fail closed')
                book = _observed_exit_book(raw, quantity)
                observed_utc = _utcnow()
                # Snapshot the ORIGINAL genuine public depth before paper mutation.
                record = {'symbol': symbol, 'observed_utc': observed_utc,
                          'origin': 'WALLEX_PUBLIC_DEPTH', 'raw_depth': raw,
                          'derived_book': book, 'fetch_duration_seconds': took,
                          'hypothetical_only': True}
                evidence_sha = hashlib.sha256(_canonical(record['raw_depth']).encode('utf8')).hexdigest()
                receipt_sha = hashlib.sha256(_canonical(record).encode('utf8')).hexdigest()
                store_file = Path(lake.root) / 'liquidation_observations' / (receipt_sha + '.json')
                if not store_file.is_file():
                    _save_atomic(store_file, record)
                else:
                    prior = json.loads(store_file.read_text(encoding='utf8'))
                    if hashlib.sha256(_canonical(prior).encode('utf8')).hexdigest() != receipt_sha:
                        raise BrokerSafetyError('Stored quote evidence SHA-256 mismatch')
                if time.monotonic() - begun > max_fetch_seconds:
                    raise BrokerSafetyError('Quote freshness expired before broker risk approval')
                event['observed_utc'] = observed_utc
                event['raw_depth_sha256'] = evidence_sha
                event['observation_record_sha256'] = receipt_sha
                event['raw_evidence_path'] = str(store_file)
                client_id = 'liq_' + hashlib.sha256(
                    _canonical([session_id, symbol, quantity, evidence_sha]).encode('utf8')).hexdigest()[:32]
                # Intentionally no explicit limit/quantity override: existing ledger and gate
                # determine the full sell. The actual quote best-level quantity must cover it.
                intent = OrderIntent(client_id, symbol, side='SELL', purpose='FINAL_TMN')
                receipt = broker.submit(intent, forecast={}, book=book, fee=fee)
                event.update({'broker_state': receipt.state.value,
                              'broker_action': receipt.reason,
                              'client_order_id': client_id})
            except Exception as exc:
                event.update({'broker_state': 'NOT_EXECUTED', 'error_type': type(exc).__name__,
                              'reason': str(exc)[:160]})
                # Preserve evidence that this final exit failed, without changing holdings.
                if not paper.verify():
                    raise BrokerSafetyError('Paper audit chain corrupt during liquidation') from exc
                with paper.db:
                    paper.log(symbol, 'PAPER_FINAL_CLOSE_FAILED',
                              {'type': type(exc).__name__, 'no_position_mutation': True,
                               'no_real_exchange_request': True})
            observations.append(event)
        if not paper.verify():
            raise BrokerSafetyError('Paper audit corrupted after liquidation')
        outstanding = paper.db.execute('SELECT symbol FROM positions ORDER BY symbol').fetchall()
        report = {'status': 'PAPER_FLAT' if not outstanding else 'PAPER_INCOMPLETE',
                  'mode': 'SHADOW_LIQUIDATION_ONLY', 'generated_at_utc': _utcnow(),
                  'paper_cash_tmn': float(paper.get('cash_tmn')),
                  'remaining_paper_positions': len(outstanding),
                  'unresolved_symbols': [row[0] for row in outstanding],
                  'observations': observations,
                  'source': 'genuine_Wallex_public_depth_only',
                  'no_real_orders': True,
                  'exchange_fills_claimed': 0,
                  'fee_status': 'RESEARCH_ASSUMPTION_NOT_VERIFIED_WITH_EXCHANGE',
                  'warning': 'PAPER fills at observed best bid are hypothetical, not exchange executions'}
        _save_atomic(Path(lake.root) / 'last_paper_liquidation_report.json', report)
        return report
    finally:
        paper.close()
