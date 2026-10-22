"""Deterministic, fail-closed risk gate for every Atlas order intent.

Source note: the separation of strategy from a risk-first gate was studied in
https://github.com/yashdhingra0/trading-bot @ 688087e64f79f545c7e40ee6e889c9ce92e03693
(no license file; no code was copied).  Circuit-breaker concepts were also
studied in grid_trading_bot @ fbda3dd5558a168f11e1a9733e12e1d9d8b3e1fc (MIT).
This implementation is independently written for Wallex spot/TMN Shadow mode.

It never imports an LLM, never sends an HTTP request, and never treats a model
forecast or news text as authority to bypass a deterministic constraint.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import math
from typing import Iterable


@dataclass(frozen=True)
class RiskLimits:
    """Current Shadow policy, made explicit and versionable.

    These are controls, not claims about executable exchange limits or fees.
    Live execution must supply separately verified organizer, package and fee
    data before it can reuse this gate.
    """

    max_cash_fraction_per_entry: float = 0.10
    max_order_notional_tmn: float = 500_000.0
    max_open_notional_tmn: float = 1_000_000.0
    max_drawdown_fraction: float = 0.03
    stop_loss_fraction: float = 0.012
    min_order_notional_tmn: float = 100_000.0
    min_top5_ask_depth_multiple: float = 3.0
    max_spread_bps: float = 70.0
    edge_safety_log_return: float = 0.001


@dataclass(frozen=True)
class RiskDecision:
    action: str
    reason: str
    notional_tmn: float = 0.0
    estimated_cost_log_return: float | None = None

    def audit_payload(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class EquityAssessment:
    high_water_tmn: float
    drawdown_fraction: float
    stopped: bool


def _finite(value, name: str, *, positive: bool = False, nonnegative: bool = False) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        raise ValueError(f'Invalid {name}') from None
    if not math.isfinite(number):
        raise ValueError(f'Invalid {name}')
    if positive and number <= 0:
        raise ValueError(f'Invalid {name}')
    if nonnegative and number < 0:
        raise ValueError(f'Invalid {name}')
    return number


class RiskGate:
    """The sole deterministic approval point for Shadow and future brokers."""

    def __init__(self, limits: RiskLimits | None = None):
        self.limits = limits or RiskLimits()

    def evaluate(self, symbol: str, forecast: dict, book: dict, cash_tmn, positions: Iterable,
                 stopped: bool, fee) -> RiskDecision:
        """Return an action without mutating accounts, positions, or external state.

        ``positions`` is the real ledger view: iterable rows of
        ``(symbol, quantity, entry_cost)``.  Invalid/missing information rejects
        a new order rather than filling a gap with inferred prices or balances.
        """
        if not isinstance(symbol, str) or not symbol.isalnum() or symbol != symbol.upper() or not symbol.endswith('TMN'):
            return RiskDecision('REJECTED', 'SPOT_TMN_SYMBOL_REQUIRED')
        if not isinstance(book, dict):
            return RiskDecision('REJECTED', 'MISSING_OR_INVALID_OBSERVED_BOOK')
        try:
            bid = _finite(book.get('best_bid_tmn'), 'observed bid', positive=True)
            ask = _finite(book.get('best_ask_tmn'), 'observed ask', positive=True)
            spread_bps = _finite(book.get('spread_bps'), 'observed spread', nonnegative=True)
            top5_ask = _finite(book.get('top5_ask_notional_tmn'), 'top-five ask depth', nonnegative=True)
            cash = _finite(cash_tmn, 'cash balance', nonnegative=True)
            fee_rate = _finite(fee, 'fee', nonnegative=True)
        except ValueError:
            return RiskDecision('REJECTED', 'MISSING_OR_INVALID_OBSERVED_BOOK')
        if ask <= bid or fee_rate >= .05:
            return RiskDecision('REJECTED', 'MISSING_OR_INVALID_OBSERVED_BOOK')

        ledger = {}
        try:
            for row in positions:
                held_symbol, quantity, entry_cost = row
                quantity = _finite(quantity, 'position quantity', positive=True)
                entry_cost = _finite(entry_cost, 'position entry cost', positive=True)
                if not isinstance(held_symbol, str) or held_symbol in ledger:
                    return RiskDecision('REJECTED', 'INVALID_POSITION_LEDGER')
                ledger[held_symbol] = (quantity, entry_cost)
        except (TypeError, ValueError):
            return RiskDecision('REJECTED', 'INVALID_POSITION_LEDGER')

        own = ledger.get(symbol)
        quantiles = forecast.get('quantile_log_returns', {}) if isinstance(forecast, dict) else {}
        q50 = quantiles.get('q50') if isinstance(quantiles, dict) else None
        if own:
            quantity, entry_cost = own
            entry_price = entry_cost / quantity
            loss_fraction = 1 - bid / entry_price
            if stopped:
                return RiskDecision('PAPER_SELL', 'CIRCUIT_BREAKER_EXIT')
            if isinstance(q50, (int, float)) and math.isfinite(q50) and q50 < 0:
                return RiskDecision('PAPER_SELL', 'NEGATIVE_MEDIAN_FORECAST')
            if loss_fraction > self.limits.stop_loss_fraction:
                return RiskDecision('PAPER_SELL', 'POSITION_STOP_LOSS')
            return RiskDecision('HOLD_POSITION', 'POSITION_REMAINS_WITHIN_DETERMINISTIC_LIMITS')

        if stopped:
            return RiskDecision('RISK_CIRCUIT_BREAKER_STOPPED', 'MAX_DRAWDOWN_ALREADY_REACHED')
        if spread_bps > self.limits.max_spread_bps:
            return RiskDecision('WIDE_SPREAD', 'OBSERVED_SPREAD_EXCEEDS_LIMIT')

        q10 = quantiles.get('q10') if isinstance(quantiles, dict) else None
        if not isinstance(q10, (int, float)) or not math.isfinite(q10):
            return RiskDecision('NO_TRUSTED_FORECAST', 'FINITE_Q10_FORECAST_REQUIRED')
        estimated_cost = 2 * math.log1p(fee_rate) + math.log(ask / bid) + self.limits.edge_safety_log_return
        if q10 <= estimated_cost:
            return RiskDecision('INSUFFICIENT_RISK_ADJUSTED_EDGE', 'Q10_DOES_NOT_COVER_OBSERVED_COSTS',
                                estimated_cost_log_return=estimated_cost)

        intended = min(cash * self.limits.max_cash_fraction_per_entry, self.limits.max_order_notional_tmn)
        held_notional = sum(cost for _, cost in ledger.values())
        if held_notional + intended > self.limits.max_open_notional_tmn:
            return RiskDecision('PORTFOLIO_RISK_LIMIT', 'OPEN_NOTIONAL_CAP_REACHED')
        if top5_ask < intended * self.limits.min_top5_ask_depth_multiple:
            return RiskDecision('INSUFFICIENT_VISIBLE_LIQUIDITY', 'OBSERVED_TOP_FIVE_ASK_DEPTH_TOO_SMALL')
        if intended < self.limits.min_order_notional_tmn:
            return RiskDecision('ORDER_BELOW_RESEARCH_MIN', 'CASH_BUDGET_BELOW_SHADOW_MINIMUM')
        return RiskDecision('PAPER_BUY', 'ALL_DETERMINISTIC_RISK_CHECKS_PASSED', intended, estimated_cost)

    def assess_equity(self, equity_tmn, high_water_tmn, already_stopped: bool) -> EquityAssessment:
        """Evaluate the persisted circuit breaker from genuine mark-to-market equity."""
        equity = _finite(equity_tmn, 'marked equity', nonnegative=True)
        high_water = _finite(high_water_tmn, 'high-water equity', positive=True)
        next_high_water = max(high_water, equity)
        drawdown = 1 - equity / next_high_water
        return EquityAssessment(next_high_water, drawdown,
                                bool(already_stopped) or drawdown >= self.limits.max_drawdown_fraction)

    def final_tmn_liquidation(self, symbol: str, book: dict, cash_tmn, positions: Iterable, fee) -> RiskDecision:
        """Authorize a final Shadow-only conversion to TMN through this same gate."""
        decision = self.evaluate(symbol, {}, book, cash_tmn, positions, True, fee)
        if decision.action == 'PAPER_SELL':
            return RiskDecision('PAPER_SELL', 'FINAL_TMN_LIQUIDATION')
        return decision
