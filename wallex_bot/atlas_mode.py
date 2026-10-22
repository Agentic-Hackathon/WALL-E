"""Deterministic Wallex Atlas execution-mode contract (Stage 5).

Provenance: QuantCrypt was listed but unavailable in the recorded reference
review; the BACKTEST / SHADOW separation is independently written from the
integration playbook, with no third-party source copied. LIVE remains disabled.

The contract protects production context/paper ledgers at entry points.
It does NOT make arbitrary Python inside the process sandboxed or make
historical candle fills genuine exchange fills.
"""
from __future__ import annotations

from enum import Enum


class ModeSafetyError(RuntimeError):
    """Execution context is not authorized for the requested side effect."""


class ExecutionMode(str, Enum):
    BACKTEST = 'BACKTEST'
    SHADOW = 'SHADOW'
    LIVE = 'LIVE'


def normalized_mode(mode):
    if isinstance(mode, ExecutionMode):
        return mode
    if not isinstance(mode, str):
        raise ModeSafetyError('Explicit supported mode required')
    try:
        return ExecutionMode(mode)
    except ValueError as exc:
        raise ModeSafetyError('Unsupported execution mode; fail closed') from exc


def require_mode(mode, *, permitted, operation):
    """Fail before any DB/network interaction. LIVE is always disabled."""
    selected = normalized_mode(mode)
    if selected is ExecutionMode.LIVE:
        raise ModeSafetyError('LIVE_EXECUTION_HARD_DISABLED_NO_AUTHORIZATION')
    allowed = frozenset(normalized_mode(x) for x in permitted)
    if selected not in allowed:
        raise ModeSafetyError(f'{operation}: {selected.value} mode is forbidden')
    return selected


def cli_mode(command, requested=None):
    """Validate explicit command mode, never silently downcast LIVE to SHADOW."""
    designated = {
        'validate': ExecutionMode.BACKTEST,
        'challenger-preflight': ExecutionMode.BACKTEST,
        'train-challenger-v2': ExecutionMode.BACKTEST,
        'challenger-evaluate': ExecutionMode.BACKTEST,
        'benchmark': ExecutionMode.BACKTEST,
        'watch': ExecutionMode.SHADOW,
        'shadow-cycle': ExecutionMode.SHADOW,
        'agent-cycle': ExecutionMode.SHADOW,
        'liquidate-paper': ExecutionMode.SHADOW,
        'run': ExecutionMode.SHADOW,  # Combined research + paper cycle, not a backtest.
    }
    if requested is None:
        return designated.get(command)
    selected = normalized_mode(requested)
    require_mode(selected, permitted=(ExecutionMode.BACKTEST, ExecutionMode.SHADOW), operation=command)
    if command not in designated:
        raise ModeSafetyError(f'{command}: explicit mode not applicable')
    if selected != designated[command]:
        raise ModeSafetyError(f'{command}: requires {designated[command].value} mode')
    return selected


def mode_status():
    return {
        'mode_contract_version': 'ATLAS_EXECUTION_MODE_V1',
        'BACKTEST': 'Production context hash verified read-only; operational events hidden to prevent future-information leakage; no paper actions',
        'SHADOW': 'Hash-chained operational memory and risk-gated hypothetical actions permitted',
        'LIVE': 'HARD_DISABLED; no order-submit transport; authorization cannot be supplied here',
        'real_exchange_order_submission': False,
        'no_live_orders': True,
    }
