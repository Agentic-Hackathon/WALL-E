"""Predictive AI + hard, auditable risk constraints. Long-only spot/TMN."""
from __future__ import annotations
from dataclasses import dataclass
from math import isfinite

@dataclass(frozen=True)
class Parameters:
    fee_rate: float                  # user-supplied, not a claim about Wallex fees
    slippage_rate: float = 0.0005    # user-supplied model assumption
    edge_buffer: float = 0.0010     # experimental margin beyond costs
    max_position_fraction: float = 0.20
    risk_fraction: float = 0.005
    stop_loss: float = 0.010
    take_profit: float = 0.018
    max_drawdown: float = 0.03
    horizon: int = 3
    min_trade_tmn: float = 0        # must be replaced with actual market minimum
    def __post_init__(self):
        if not (0 <= self.fee_rate < 0.05 and 0 <= self.slippage_rate < .05):
            raise ValueError('Invalid fee/slippage')
        if not (0 < self.max_position_fraction <= 1 and 0 < self.risk_fraction < 1 and
                0 < self.stop_loss < 1 and 0 < self.take_profit < 1 and
                0 < self.max_drawdown < 1 and self.horizon > 0):
            raise ValueError('Invalid risk parameters')
    @property
    def entry_threshold(self):
        return 2*(self.fee_rate+self.slippage_rate) + self.edge_buffer

def decision(predicted_log_return, cash, qty, price, equity, peak, parameters: Parameters,
             age=0, basis=0, volatility_ok=True):
    """Return action, reason, TMN notional. Never short or trade outside allowlist."""
    p=parameters
    dd=1-equity/max(peak,1e-9)
    if qty > 0:
        pnl=price/max(basis,1e-9)-1
        if dd>=p.max_drawdown:
            return 'SELL','portfolio_max_drawdown',qty*price
        if pnl<=-p.stop_loss:
            return 'SELL','stop_loss',qty*price
        if pnl>=p.take_profit:
            return 'SELL','take_profit',qty*price
        if age>=p.horizon:
            return 'SELL','max_holding_period',qty*price
        if predicted_log_return < -p.entry_threshold:
            return 'SELL','negative_AI_forecast',qty*price
        return 'HOLD','position_active',0.0
    if dd>=p.max_drawdown:
        return 'HOLD','drawdown_circuit_breaker',0.0
    if not volatility_ok:
        return 'HOLD','volatility_filter',0.0
    if not isfinite(predicted_log_return):
        return 'HOLD','invalid_prediction',0.0
    if predicted_log_return<=p.entry_threshold:
        return 'HOLD','insufficient_net_expected_edge',0.0
    budget=min(cash*.95, equity*p.max_position_fraction, equity*p.risk_fraction/p.stop_loss)
    if budget < p.min_trade_tmn or budget <= 0:
        return 'HOLD','insufficient_trade_budget',0.0
    return 'BUY','AI_edge_after_cost_and_risk_checks',float(budget)
