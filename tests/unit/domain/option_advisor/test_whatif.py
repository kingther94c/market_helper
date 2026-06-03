"""What-if recompute engine: zero-shift == engine, plus shift sanity (hermetic)."""

from __future__ import annotations

import pytest

from market_helper.domain.option_advisor import structures
from market_helper.domain.option_advisor.contracts import UnderlyingContext
from market_helper.domain.option_advisor.providers import build_synthetic_chain
from market_helper.domain.option_advisor.structures import (
    build_call_spread,
    build_covered_call,
    build_protective_put,
)


def _chain(dte=35):
    return build_synthetic_chain("ABC", 100.0, 0.25, expiries_dte=(dte,), n_strikes=61, strike_step_pct=0.01)


def _ctx(held=0.0):
    return UnderlyingContext(internal_id="STK:ABC:SMART", symbol="ABC", as_of="t", spot=100.0, held_qty=held)


def test_idea_carries_spot():
    idea = build_call_spread(_chain(), _ctx(), long_delta=0.45, short_delta=0.25, dte=35)
    assert idea is not None and idea.spot == 100.0


def test_whatif_zero_reproduces_engine():
    """The load-bearing invariant: no-op what-if == the engine's stored metrics."""
    idea = build_covered_call(_chain(), _ctx(held=100), target_delta=0.30, dte=35)
    m = structures.whatif(idea.structure_type, idea.legs, idea.spot)
    assert m["net_credit"] == pytest.approx(idea.est_net_debit_credit, abs=1.0)
    assert m["max_loss"] == pytest.approx(idea.est_max_loss, abs=1.0)
    assert m["max_gain"] == pytest.approx(idea.est_max_gain, abs=1.0)
    assert m["net_greeks"]["delta"] == pytest.approx(idea.net_greeks["delta"], abs=0.5)


def test_whatif_from_detail_matches_object_path():
    from dataclasses import asdict

    idea = build_call_spread(_chain(40), _ctx(), long_delta=0.45, short_delta=0.25, dte=40)
    via_obj = structures.whatif(idea.structure_type, idea.legs, idea.spot)
    via_detail = structures.whatif_from_detail(asdict(idea))
    assert via_detail["net_credit"] == pytest.approx(via_obj["net_credit"], abs=0.5)
    assert via_detail["max_loss"] == pytest.approx(via_obj["max_loss"], abs=0.5)


def test_whatif_qty_scale_doubles_economics():
    idea = build_call_spread(_chain(40), _ctx(), long_delta=0.45, short_delta=0.25, dte=40)
    base = structures.whatif(idea.structure_type, idea.legs, idea.spot)
    dbl = structures.whatif(idea.structure_type, idea.legs, idea.spot, qty_scale=2)
    assert dbl["max_loss"] == pytest.approx(2 * base["max_loss"], rel=0.02)
    assert dbl["net_credit"] == pytest.approx(2 * base["net_credit"], rel=0.02)


def test_whatif_iv_up_raises_long_put_cost():
    idea = build_protective_put(_chain(75), _ctx(held=100), target_delta=0.15, dte=75)
    base = structures.whatif(idea.structure_type, idea.legs, idea.spot)
    bumped = structures.whatif(idea.structure_type, idea.legs, idea.spot, iv_shift=0.05)
    # long put: higher IV → higher premium → larger debit → net credit more negative
    assert bumped["net_credit"] < base["net_credit"]
    assert base["net_greeks"]["vega"] > 0  # long-vega hedge
