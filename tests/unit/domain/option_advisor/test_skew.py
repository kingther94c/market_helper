"""Chain-skew estimate + sticky-moneyness what-if (hermetic, no network).

The what-if's *Link IV to chain skew* path: moving spot off the generation
anchor moves each leg's IV along the chain's observed ``∂IV/∂log-moneyness``
instead of holding it flat. With ``iv_skew=0`` the behaviour collapses back to
the flat re-price (the load-bearing ``what-if == engine`` invariant).
"""

from __future__ import annotations

from dataclasses import asdict

import pytest

from market_helper.domain.option_advisor import structures
from market_helper.domain.option_advisor.contracts import (
    ChainSnapshot,
    OptionQuote,
    UnderlyingContext,
)
from market_helper.domain.option_advisor.providers import build_synthetic_chain
from market_helper.domain.option_advisor.structures import build_call_spread, build_covered_call


def _chain(dte=35):
    return build_synthetic_chain("ABC", 100.0, 0.25, expiries_dte=(dte,), n_strikes=61, strike_step_pct=0.01)


def _ctx(held=0.0):
    return UnderlyingContext(internal_id="STK:ABC:SMART", symbol="ABC", as_of="t", spot=100.0, held_qty=held)


# --------------------------------------------------------------------------- #
# ChainSnapshot.atm_skew
# --------------------------------------------------------------------------- #


def test_atm_skew_is_negative_for_index_surface():
    chain = _chain()
    expiry = chain.expiries()[0]
    skew = chain.atm_skew(expiry)
    assert skew is not None
    # Default synthetic surface is an index-like put skew (skew=-0.12) → negative,
    # flattened slightly by the sqrt-T term-decay at ~35 DTE.
    assert -0.20 < skew < -0.05


def test_atm_skew_none_without_two_strikes():
    one = ChainSnapshot(
        underlying="ABC", as_of="t", spot=100.0,
        quotes=[OptionQuote(underlying="ABC", expiry="2026-07-17", dte=30, right="C", strike=100.0, iv=0.25)],
    )
    assert one.atm_skew("2026-07-17") is None


def test_atm_skew_none_when_no_iv():
    no_iv = ChainSnapshot(
        underlying="ABC", as_of="t", spot=100.0,
        quotes=[
            OptionQuote(underlying="ABC", expiry="2026-07-17", dte=30, right="C", strike=98.0),
            OptionQuote(underlying="ABC", expiry="2026-07-17", dte=30, right="C", strike=102.0),
        ],
    )
    assert no_iv.atm_skew("2026-07-17") is None


# --------------------------------------------------------------------------- #
# OptionIdea carries the skew
# --------------------------------------------------------------------------- #


def test_idea_carries_iv_skew():
    idea = build_call_spread(_chain(), _ctx(), long_delta=0.45, short_delta=0.25, dte=35)
    assert idea is not None
    assert idea.iv_skew is not None and idea.iv_skew < 0


# --------------------------------------------------------------------------- #
# reprice_legs sticky-moneyness behaviour
# --------------------------------------------------------------------------- #


def test_reprice_skew_moves_iv_vs_flat_on_spot_up():
    idea = build_call_spread(_chain(), _ctx(), long_delta=0.45, short_delta=0.25, dte=35)
    flat = structures.reprice_legs(idea.legs, 110.0, base_spot=100.0)              # iv_skew defaults 0
    skewed = structures.reprice_legs(idea.legs, 110.0, iv_skew=idea.iv_skew, base_spot=100.0)
    # spot up → moneyness ln(K/S) falls → negative skew lifts IV above the flat path.
    for f, s in zip(flat, skewed):
        assert s.est_iv > f.est_iv


def test_reprice_skew_is_flat_at_base_spot():
    # No spot move ⇒ no skew adjustment, even with a non-zero skew.
    idea = build_call_spread(_chain(), _ctx(), long_delta=0.45, short_delta=0.25, dte=35)
    flat = structures.reprice_legs(idea.legs, 100.0, base_spot=100.0)
    skewed = structures.reprice_legs(idea.legs, 100.0, iv_skew=idea.iv_skew, base_spot=100.0)
    for f, s in zip(flat, skewed):
        assert s.est_iv == pytest.approx(f.est_iv, abs=1e-9)


# --------------------------------------------------------------------------- #
# whatif: skew=0 regression + passthrough from detail
# --------------------------------------------------------------------------- #


def test_whatif_zero_skew_matches_default():
    idea = build_covered_call(_chain(), _ctx(held=100), target_delta=0.30, dte=35)
    base = structures.whatif(idea.structure_type, idea.legs, idea.spot, spot_override=92.0)
    explicit_zero = structures.whatif(idea.structure_type, idea.legs, idea.spot, spot_override=92.0, iv_skew=0.0)
    assert explicit_zero == base


def test_whatif_skew_changes_economics_off_anchor():
    idea = build_covered_call(_chain(), _ctx(held=100), target_delta=0.30, dte=35)
    flat = structures.whatif(idea.structure_type, idea.legs, idea.spot, spot_override=108.0)
    skewed = structures.whatif(
        idea.structure_type, idea.legs, idea.spot, spot_override=108.0, iv_skew=idea.iv_skew
    )
    # The skew path re-prices the short call's IV, so the net economics differ.
    assert skewed["net_credit"] != pytest.approx(flat["net_credit"], abs=1e-6)


def test_whatif_from_detail_skew_passthrough():
    idea = build_call_spread(_chain(40), _ctx(), long_delta=0.45, short_delta=0.25, dte=40)
    detail = asdict(idea)
    via_detail = structures.whatif_from_detail(detail, spot_override=110.0, iv_skew=detail["iv_skew"])
    via_obj = structures.whatif(idea.structure_type, idea.legs, idea.spot, spot_override=110.0, iv_skew=idea.iv_skew)
    assert via_detail["net_credit"] == pytest.approx(via_obj["net_credit"], abs=1e-6)
    assert via_detail["max_loss"] == pytest.approx(via_obj["max_loss"], abs=1e-6)
