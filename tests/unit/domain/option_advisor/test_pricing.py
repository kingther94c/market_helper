"""Black-Scholes pricing / Greeks / implied-vol sanity (pure, no network)."""

from __future__ import annotations

import math

import pytest

from market_helper.domain.option_advisor.pricing import (
    bs_greeks,
    bs_price,
    implied_vol,
    intrinsic,
    leg_payoff_at_expiry,
)


def test_put_call_parity():
    S, K, t, r, q, sig = 100.0, 105.0, 0.5, 0.03, 0.0, 0.2
    c = bs_price("C", S, K, t, r, sig, q)
    p = bs_price("P", S, K, t, r, sig, q)
    assert (c - p) == pytest.approx(S * math.exp(-q * t) - K * math.exp(-r * t), abs=1e-9)


@pytest.mark.parametrize("right", ["C", "P"])
@pytest.mark.parametrize("K", [80.0, 100.0, 125.0])
def test_implied_vol_roundtrip(right, K):
    sigma = 0.30
    px = bs_price(right, 100.0, K, 0.4, 0.02, sigma)
    iv = implied_vol(px, right, 100.0, K, 0.4, 0.02)
    assert iv == pytest.approx(sigma, abs=1e-3)


def test_greeks_signs_and_bounds():
    gc = bs_greeks("C", 100, 100, 0.5, 0.03, 0.25)
    gp = bs_greeks("P", 100, 100, 0.5, 0.03, 0.25)
    assert 0.0 < gc.delta < 1.0
    assert -1.0 < gp.delta < 0.0
    assert gc.gamma > 0 and gp.gamma > 0
    assert gc.vega > 0 and gp.vega > 0
    assert gc.theta < 0  # long ATM call decays
    # gamma and vega are right-independent
    assert gc.gamma == pytest.approx(gp.gamma, rel=1e-9)
    assert gc.vega == pytest.approx(gp.vega, rel=1e-9)


def test_expiry_and_zero_vol_collapse_to_intrinsic():
    assert bs_price("C", 110, 100, 0.0, 0.02, 0.2) == intrinsic("C", 110, 100) == 10.0
    assert bs_price("P", 90, 100, 0.0, 0.02, 0.2) == intrinsic("P", 90, 100) == 10.0
    g = bs_greeks("C", 110, 100, 0.0, 0.02, 0.2)
    assert g.delta == 1.0 and g.gamma == 0.0 and g.vega == 0.0


def test_implied_vol_below_intrinsic_returns_none():
    # price under the no-arb lower bound is unsolvable
    assert implied_vol(0.01, "C", 100, 50, 0.5, 0.02) is None


def test_leg_payoff_at_expiry():
    assert leg_payoff_at_expiry("C", "buy", 100, 5, 110) == pytest.approx(5)
    assert leg_payoff_at_expiry("C", "buy", 100, 5, 95) == pytest.approx(-5)
    assert leg_payoff_at_expiry("P", "sell", 100, 4, 105) == pytest.approx(4)
    assert leg_payoff_at_expiry("P", "sell", 100, 4, 90) == pytest.approx(-6)
