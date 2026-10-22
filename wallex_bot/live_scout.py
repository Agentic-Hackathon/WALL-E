"""Read-only Wallex live order-book opportunity measurements.

Uses only observed public exchange market metadata and depth, plus private
read-only package restrictions. This module never places, cancels or fills an
order; notional sweep outputs are *estimates from observed depth*, not fills.
No mocked/synthetic prices or observations exist in this module.
"""
from __future__ import annotations

import json
import math
import time
import datetime as dt
from pathlib import Path

from .audit import AuditStore
from .market import depth, markets
from .wallex_api import WallexReadClient, read_organizer_allowlist


def _finite_positive(raw, name: str) -> float:
    try:
        value = float(raw)
    except (TypeError, ValueError, OverflowError):
        raise ValueError(f'Invalid numeric {name}') from None
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f'Nonpositive/nonfinite {name}')
    return value


def _levels(order_book: dict, side: str) -> list[tuple[float,float]]:
    raw = order_book.get(side)
    if not isinstance(raw, list) or not raw:
        raise ValueError(f'Live order book has no {side} levels')
    pairs = []
    for row in raw:
        if not isinstance(row, dict):
            raise ValueError('Order-book level is not an object')
        price = _finite_positive(row.get('price'), 'book price')
        qty = _finite_positive(row.get('quantity'), 'book quantity')
        pairs.append((price, qty))
    return sorted(pairs, key=lambda z: z[0], reverse=(side == 'bid'))


def _buy_with_notional(asks: list[tuple[float,float]], notional: float):
    """Sweep displayed asks with a hypothetical quote budget; no API order."""
    remaining = notional
    acquired = 0.0
    spent = 0.0
    for px, qty in asks:
        used = min(remaining, px * qty)
        acquired += used / px
        spent += used
        remaining -= used
        if remaining <= max(1e-8, notional * 1e-10):
            break
    if remaining > max(1e-8, notional * 1e-10):
        return None
    return acquired, spent / acquired


def _sell_qty(bids: list[tuple[float,float]], quantity: float):
    remaining = quantity
    gross = 0.0
    for px, qty in bids:
        used = min(remaining, qty)
        gross += used * px
        remaining -= used
        if remaining <= max(1e-12, quantity * 1e-10):
            break
    if remaining > max(1e-12, quantity * 1e-10):
        return None
    return gross, gross / quantity


def measure_book(raw: dict, notional_tmn: float, fee_rate: float) -> dict:
    """Deterministic features of an ACTUAL observed Wallex depth response.

    Does not claim executable liquidity, order fills or future prices.
    """
    notional = _finite_positive(notional_tmn, 'notional_tmn')
    if not (0 <= fee_rate < .05):
        raise ValueError('Invalid fee per side')
    if not isinstance(raw, dict):
        raise ValueError('Wallex book must be an object')
    asks, bids = _levels(raw,'ask'), _levels(raw,'bid')
    best_ask, best_bid = asks[0][0], bids[0][0]
    if best_ask <= best_bid:
        raise ValueError('Crossed/locked book, cannot estimate spread')
    mid = (best_bid + best_ask) / 2
    # Five best levels on each side, measured in TMN.
    near_ask = sum(px*q for px,q in asks[:5])
    near_bid = sum(px*q for px,q in bids[:5])
    imbalance = (near_bid-near_ask) / (near_bid+near_ask)
    buy = _buy_with_notional(asks, notional)
    sell = _sell_qty(bids,buy[0]) if buy is not None else None
    roundtrip = (sell[0]*(1-fee_rate)/(notional*(1+fee_rate))-1) if sell is not None else None
    return {
        'best_bid_tmn': best_bid, 'best_ask_tmn': best_ask,
        'mid_tmn': mid, 'spread_bps': (best_ask-best_bid)/mid*10000,
        'ask_levels': len(asks), 'bid_levels': len(bids),
        'top5_ask_notional_tmn': near_ask, 'top5_bid_notional_tmn': near_bid,
        'top5_quote_imbalance': imbalance,
        'hypothetical_budget_tmn': notional,
        'hypothetical_full_buy_depth_available': buy is not None,
        'hypothetical_full_roundtrip_depth_available': sell is not None,
        'hypothetical_buy_avg_price': buy[1] if buy is not None else None,
        'hypothetical_sell_avg_price': sell[1] if sell is not None else None,
        'hypothetical_instant_roundtrip_net_pct': 100*roundtrip if roundtrip is not None else None,
        'fee_per_side_assumption': fee_rate,
    }


def _eligible_markets(symbols: list[str], allowlist_path: str, package_id: int,
                      read_client: WallexReadClient) -> dict[str, dict]:
    if not isinstance(package_id,int) or package_id <= 0:
        raise ValueError('An actual positive trade-credit package ID is required')
    allowed = set(read_organizer_allowlist(allowlist_path))
    if not symbols or len(symbols)>8 or len(set(symbols))!=len(symbols):
        raise ValueError('Choose 1..8 distinct symbols from organizer allowlist')
    if any(symbol not in allowed for symbol in symbols):
        raise ValueError('Requested market is not in organizer allowlist; fail closed')
    public = {m.get('symbol'):m for m in markets()}
    details = read_client.package_details(package_id)
    forbidden = details.get('unavailableMarkets')
    if not isinstance(forbidden,list) or any(not isinstance(x,str) for x in forbidden):
        raise ValueError('Package unavailableMarkets is not a validated list')
    rejected = []
    selected = {}
    for symbol in symbols:
        m = public.get(symbol)
        if (not isinstance(m,dict) or m.get('is_spot') is not True or
            m.get('is_tmn_based') is not True or m.get('quote_asset') != 'TMN' or
            symbol in forbidden):
            rejected.append(symbol)
        else:
            selected[symbol] = m
    if rejected:
        raise ValueError('Spot/TMN/credit-package authorization failed for: '+', '.join(rejected))
    return selected


def capture_once(symbols: list[str], allowlist_path: str, package_id: int,
                 audit_path: str | Path, notional_tmn: float, fee_rate: float,
                 max_spread_bps: float = 100.0) -> dict:
    """Fetch new ACTUAL public snapshots and persist source+computed metrics.

    The API key remains only in WallexReadClient process memory and is never
    stored or forwarded to third-party MCP servers.
    """
    if not 0 < max_spread_bps <= 10000:
        raise ValueError('Invalid maximum observed spread')
    read_client = WallexReadClient()
    selected = _eligible_markets(symbols,allowlist_path,package_id,read_client)
    store = AuditStore(audit_path)
    # Existing evidence must be intact before any new append.
    valid, _ = store.verify()
    if not valid:
        store.close()
        raise RuntimeError('Existing SQLite audit chain is corrupted; refusing to append')
    summaries=[]
    try:
        for symbol in symbols:
            observed_at = dt.datetime.now(dt.timezone.utc).isoformat(timespec='microseconds')
            started = time.perf_counter()
            try:
                raw_book = depth(symbol)  # actual public Wallex snapshot
                elapsed_ms = round((time.perf_counter()-started)*1000,3)
                result = measure_book(raw_book, notional_tmn, fee_rate)
                meta=selected[symbol]
                event = {
                    'origin':'wallex_public_depth_and_market_metadata',
                    'symbol':symbol,'observed_at_utc':observed_at,
                    'local_depth_request_latency_ms':elapsed_ms,
                    'market_24h_change_reported':meta.get('change_24h'),
                    'market_24h_quote_volume_reported':meta.get('quote_volume_24h'),
                    'metrics':result,'raw_order_book':raw_book,
                    'contest_eligibility':{'organizer_allowlisted':True,'spot':True,
                          'tmn_quoted':True,'not_blocked_in_package':True},
                    'observation_only':True,'no_order_submitted':True,
                    'caveat':'Local REST fetch timestamp, NOT an exchange server timestamp; depth can change before execution.'
                }
                store.record('REAL_BOOK_OBSERVATION',event,observed_at)
                summaries.append({'symbol':symbol,'observed_at_utc':observed_at,
                    'spread_bps':round(result['spread_bps'],5),
                    'top5_quote_imbalance':round(result['top5_quote_imbalance'],6),
                    'instant_roundtrip_estimate_pct':round(result['hypothetical_instant_roundtrip_net_pct'],5)
                        if result['hypothetical_instant_roundtrip_net_pct'] is not None else None,
                    'candidate_for_further_research':bool(result['spread_bps']<=max_spread_bps
                        and result['hypothetical_full_roundtrip_depth_available']),
                    'latency_ms':elapsed_ms})
            except (ValueError, TypeError, KeyError) as exc:
                # No substituted prices, no synthetic fallback data.
                store.record('LIVE_BOOK_REJECTED',{'symbol':symbol,'observed_at_utc':observed_at,
                    'reason':type(exc).__name__+': '+str(exc)[:180],
                    'no_order_submitted':True},observed_at)
                summaries.append({'symbol':symbol,'status':'REJECTED_INVALID_EXCHANGE_SNAPSHOT',
                                  'reason':type(exc).__name__})
    finally:
        store.close()
    return {'mode':'PUBLIC_REAL_MARKET_SCOUT_ONLY', 'audit_path':str(audit_path),
            'records':summaries,'trade_execution_enabled':False}


def report_scout(audit_path: str | Path, forward_minutes: int = 45, tolerance_minutes: int = 6) -> dict:
    """Read only authentic recorded snapshots and summarize without new market data."""
    if not (1 <= forward_minutes <= 1440 and 0 <= tolerance_minutes <= 30):
        raise ValueError('Invalid forward/tolerance time')
    path = Path(audit_path)
    if not path.is_file():
        raise FileNotFoundError('Real-only scout audit does not exist')
    store = AuditStore(path)
    try:
        valid, n = store.verify()
        if not valid:
            raise RuntimeError('Tamper-evident event chain failed verification')
        bysymbol={}
        from statistics import mean,median
        for (payload,) in store.db.execute("SELECT payload FROM events WHERE kind='REAL_BOOK_OBSERVATION' ORDER BY id"):
            row=json.loads(payload)
            if row.get('origin')!='wallex_public_depth_and_market_metadata' or row.get('no_order_submitted') is not True:
                raise RuntimeError('Unexpected event origin/permissions')
            metrics=measure_book(row['raw_order_book'],row['metrics']['hypothetical_budget_tmn'],
                                 row['metrics']['fee_per_side_assumption'])
            if metrics != row['metrics']:
                raise RuntimeError('Stored computed metrics do not replay exactly from original raw book')
            bysymbol.setdefault(row['symbol'],[]).append(row)
        for symbol,records in list(bysymbol.items()):
            # Real future observed book, not a future price prediction and NOT fills.
            # Only match subsequently recorded observations within an explicit time tolerance.
            horizon = forward_minutes * 60
            tol = tolerance_minutes * 60
            stamped = [(dt.datetime.fromisoformat(r['observed_at_utc']).timestamp(),r) for r in records]
            forward_returns=[]
            for i,(ts,entry) in enumerate(stamped):
                matches=[(abs(later_ts-ts-horizon),future) for later_ts,future in stamped[i+1:]
                         if abs(later_ts-ts-horizon) <= tol]
                if not matches:
                    continue
                future=min(matches, key=lambda x:x[0])[1]
                notional = entry['metrics']['hypothetical_budget_tmn']
                fee = entry['metrics']['fee_per_side_assumption']
                buy = _buy_with_notional(_levels(entry['raw_order_book'],'ask'),notional)
                if buy is None:
                    continue
                sell = _sell_qty(_levels(future['raw_order_book'],'bid'),buy[0])
                if sell is None:
                    continue
                forward_returns.append(100*(sell[0]*(1-fee)/(notional*(1+fee))-1))
            spreads=[r['metrics']['spread_bps'] for r in records]
            edges=[r['metrics']['hypothetical_instant_roundtrip_net_pct'] for r in records
                   if r['metrics']['hypothetical_instant_roundtrip_net_pct'] is not None]
            bysymbol[symbol]={'observations':len(records),'first_utc':records[0]['observed_at_utc'],
                'last_utc':records[-1]['observed_at_utc'],
                'median_spread_bps':median(spreads),'worst_spread_bps':max(spreads),
                'min_depth_roundtrips':len(edges),'median_instant_roundtrip_net_pct':median(edges) if edges else None,
                'observed_forward_horizon_minutes':forward_minutes,
                'forward_book_pairs_scored':len(forward_returns),
                'mean_observed_forward_book_net_pct':mean(forward_returns) if forward_returns else None,
                'fraction_positive_observed_forward_book_pairs':mean(r>0 for r in forward_returns) if forward_returns else None}
        return {'mode':'REAL_ONLY_RECORDED_DEPTH_RESEARCH', 'audit_events':n,
                'audit_hash_chain_valid':valid,'symbols':bysymbol,
                'note':'No executed trades, no AI signals, no fills or prediction proof. Forward returns are only counterfactual estimates from TWO independently observed actual book snapshots, sampled on a local clock; overlapping observations are not independent.'}
    finally:
        store.close()
