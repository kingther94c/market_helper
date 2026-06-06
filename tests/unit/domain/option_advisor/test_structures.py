"""Structure builders: payoff math, breakevens, max loss/gain (no network)."""

from __future__ import annotations

import pytest

from market_helper.domain.option_advisor.contracts import UnderlyingContext
from market_helper.domain.option_advisor.providers import build_synthetic_chain
from market_helper.domain.option_advisor.structures import (
    build_call_spread,
    build_cash_secured_put,
    build_covered_call,
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
