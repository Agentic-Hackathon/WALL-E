"""Contract tests only; they contain no market fixtures, quotes, fills, or prices."""
import inspect
from pathlib import Path

from wallex_bot import atlas_risk, atlas_shadow


def test_risk_policy_keeps_the_existing_shadow_caps_explicit():
    limits = atlas_risk.RiskLimits()
    assert limits.max_cash_fraction_per_entry == .10
    assert limits.max_order_notional_tmn == 500_000.
    assert limits.max_open_notional_tmn == 1_000_000.
    assert limits.max_drawdown_fraction == .03
    assert limits.stop_loss_fraction == .012


def test_risk_gate_has_no_network_or_order_submission_path():
    source = inspect.getsource(atlas_risk)
    assert 'requests.' not in source
    assert 'createorder' not in source.lower()
    assert 'WALLEX_API_KEY' not in source
    assert 'LLM' in source


def test_paper_account_delegates_entries_exits_and_circuit_breaker_to_gate():
    source = Path(inspect.getfile(atlas_shadow)).read_text(encoding='utf8')
    assert 'from .atlas_risk import RiskGate' in source
    assert 'self.risk.evaluate(' in source
    assert 'self.risk.assess_equity(' in source


def test_watch_final_liquidation_cannot_bypass_the_risk_gate():
    source = Path(inspect.getfile(atlas_shadow)).with_name('atlas_watch.py').read_text(encoding='utf8')
    assert 'paper.risk.final_tmn_liquidation(' in source
