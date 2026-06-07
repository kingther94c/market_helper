"""Structure builders: payoff math, breakevens, max loss/gain (no network)."""

from __future__ import annotations

import pytest

from market_helper.domain.option_advisor.config import load_rules
from market_helper.domain.option_advisor.contracts import UnderlyingContext
from market_helper.domain.option_advisor.filters import evaluate
from market_helper.domain.option_advisor.providers import build_synthetic_chain
from market_helper.domain.option_advisor.structures import (
    build_call_spread,
    build_carry_short_call,
    build_carry_short_put,
    build_cash_secured_put,
    build_covered_call,
    build_zero_cost_collar,
)


def _chain():
    return build_synthetic_chain("ABC", 100.0, 0.25, expiries_dte=(35,), n_strikes=61, strike_step_pct=0.01)


def _ctx(held=0.0):
    return UnderlyingContext(internal_id="STK:ABC:SMART", symbol="ABC", as_of="t", spot=100.0, held_qty=held)


def test_call_spread_payoff_geometry():
    idea = build_call_spread(_chain(), _ctx(), long_delta=0.45, short_delta=0.25, dte=35)
    assert idea is not None
    # debit spread: max loss == net debit (== net credit, which is negative)
    assert idea.est_max_loss == pytest.approx(idea.est_net_debit_credit, abs=1.0)
    assert idea.est_max_gain > 0
    assert len(idea.est_breakevens) == 1
    lo = min(l.resolved_strike for l in idea.legs)
    hi = max(l.resolved_strike for l in idea.legs)
    assert lo < idea.est_breakevens[0] < hi
    # width*100 - debit == max gain
    width = (hi - lo) * 100
    assert idea.est_max_gain == pytest.approx(width + idea.est_net_debit_credit, abs=1.0)


def test_covered_call_breakeven():
    idea = build_covered_call(_chain(), _ctx(held=100), target_delta=0.30, dte=35)
    assert idea is not None
    assert idea.est_net_debit_credit > 0  # net credit collected
    be = 100.0 - idea.est_net_debit_credit / 100.0
    assert idea.est_breakevens and idea.est_breakevens[0] == pytest.approx(be, abs=0.5)


def test_cash_secured_put_max_loss():
    idea = build_cash_secured_put(_chain(), _ctx(), target_delta=0.27, dte=35)
    assert idea is not None
    k = idea.legs[0].resolved_strike
    # max loss (underlying to zero) == -(strike*100 - credit)
    assert idea.est_max_loss == pytest.approx(-(k * 100 - idea.est_net_debit_credit), abs=5.0)


def test_net_greeks_present():
    idea = build_call_spread(_chain(), _ctx(), long_delta=0.45, short_delta=0.25, dte=35)
    for key in ("delta", "gamma", "theta", "vega"):
        assert key in idea.net_greeks


# --------------------------------------------------------------------------- #
# Module 1 — zero-cost protection + carry-premium structures
# --------------------------------------------------------------------------- #


def test_zero_cost_collar_geometry_and_financing():
    idea = build_zero_cost_collar(_chain(), _ctx(held=100), protect_put_delta=0.25, floor_put_delta=0.10, dte=35)
    assert idea is not None
    assert idea.structure_type == "ZERO_COST_COLLAR"
    # Three legs: buy put (protection), sell put (floor), sell call (finance).
    rights_actions = [(l.right, l.action) for l in idea.legs]
    assert rights_actions == [("P", "buy"), ("P", "sell"), ("C", "sell")]
    long_put, floor_put, call = idea.legs
    # Floor sits strictly below the protection put; both OTM (below spot); call is OTM above spot.
    assert floor_put.resolved_strike < long_put.resolved_strike < 100.0 < call.resolved_strike
    # "Zero-cost": the short call finances ≥ ~80% of the put-spread cost (net is a credit or a
    # debit no larger than 20% of the protection-put premium).
    protect_cost = (long_put.est_price or 0.0) * 100.0
    assert idea.est_net_debit_credit >= -0.20 * protect_cost
    # Net-short-vega is the design intent (two shorts vs one long).
    assert idea.net_greeks["vega"] < 0


def test_carry_short_call_is_naked_income():
    idea = build_carry_short_call(_chain(), _ctx(), target_delta=0.20, dte=35)
    assert idea is not None
    assert idea.structure_type == "CARRY_SHORT_CALL"
    assert idea.category == "INCOME"
    assert len(idea.legs) == 1 and idea.legs[0].action == "sell" and idea.legs[0].right == "C"
    assert idea.est_net_debit_credit > 0  # premium collected
    assert "NAKED" in idea.why_now.upper()


def test_carry_short_put_is_income():
    idea = build_carry_short_put(_chain(), _ctx(), target_delta=0.18, dte=35)
    assert idea is not None
    assert idea.structure_type == "CARRY_SHORT_PUT"
    assert len(idea.legs) == 1 and idea.legs[0].action == "sell" and idea.legs[0].right == "P"
    assert idea.est_net_debit_credit > 0


@pytest.mark.parametrize("builder", [build_carry_short_call, build_carry_short_put])
def test_carry_shorts_capped_at_monitor_by_filter(builder):
    """Naked premium-selling must carry a soft 'naked_premium_risk' fail → MONITOR cap,
    regardless of data mode (the read-only honesty rule)."""
    idea = builder(_chain(), _ctx(), dte=35)
    assert idea is not None
    outcomes, sizing = evaluate(idea, _ctx(), load_rules())
    risk = [o for o in outcomes if o.filter_name == "naked_premium_risk"]
    assert risk and risk[0].passed is False and risk[0].severity == "soft"
    # Sized by a margin proxy, not the misleading grid max-loss.
    assert sizing.basis == "naked_margin_cap"
