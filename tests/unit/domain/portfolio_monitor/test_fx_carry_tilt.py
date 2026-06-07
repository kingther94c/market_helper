"""FX carry tilt overlay: bounded tilt toward carry + honest before/after (no network)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from market_helper.domain.portfolio_monitor.services.fx_carry_tilt import (
    compute_fx_carry_tilt,
)
from market_helper.domain.portfolio_monitor.services.fx_hedge_advisor import FxHedgeLeg

USD_RATE = 0.043


def _leg(currency, on_rate, realized, usd_per_contract, contracts):
    carry = realized * (on_rate - USD_RATE)  # so _derive_on_rate_usd recovers USD_RATE
    return FxHedgeLeg(
        currency=currency, instrument=f"{currency}/USD (X)", futures_root="X",
        yahoo_symbol=f"{currency}USD=X", beta=0.2, beta_std_error=0.0, t_stat=0.0,
        spot_usd_per_unit=1.0, target_notional_usd=realized, contract_size=1.0,
        contract_size_currency=currency, usd_notional_per_contract=usd_per_contract,
        target_contracts=contracts, realized_notional_usd=realized, residual_notional_usd=0.0,
        on_rate=on_rate, expected_annual_carry_usd=carry, expiry="2026-06-17",
    )


def _alloc():
    # EUR low carry (negative diff), AUD high carry, CNH mild positive.
    legs = [
        _leg("EUR", 0.025, 500_000.0, 100_000.0, 5),
        _leg("AUD", 0.055, 300_000.0, 75_000.0, 4),
        _leg("CNH", 0.045, 400_000.0, 80_000.0, 5),
    ]
    return SimpleNamespace(legs=legs, hedge_notional_usd=1_200_000.0)


def test_tilt_overweights_high_carry_underweights_low():
    res = compute_fx_carry_tilt(_alloc(), tilt_strength=0.5)
    assert res is not None
    assert res.method == "rate_differential"
    assert res.on_rate_usd == pytest.approx(USD_RATE, abs=1e-9)
    by_ccy = {r["currency"]: r for r in res.rows}
    # Lowest-carry leg (EUR) is trimmed; highest-carry (AUD) is not trimmed.
    assert by_ccy["EUR"]["tilted_contracts"] <= by_ccy["EUR"]["base_contracts"]
    assert by_ccy["AUD"]["tilted_contracts"] >= by_ccy["AUD"]["base_contracts"]
    # Tilting toward carry does not reduce expected carry, and reports a real deviation cost.
    assert res.carry_impact_usd >= 0.0
    assert res.hedge_deviation_pct > 0.0
    assert res.hedge_deviation_pct <= res.max_deviation + 1e-9
    # Before/after economics are populated.
    for side in (res.before, res.after):
        assert {"gross_notional_usd", "net_notional_usd", "annual_carry_usd", "carry_bps"} <= set(side)


def test_zero_strength_is_a_noop():
    res = compute_fx_carry_tilt(_alloc(), tilt_strength=0.0)
    assert res is not None
    assert res.carry_impact_usd == pytest.approx(0.0, abs=1e-6)
    assert res.hedge_deviation_pct == pytest.approx(0.0, abs=1e-9)
    for r in res.rows:
        assert r["tilted_contracts"] == r["base_contracts"]


def test_equal_carry_means_no_tilt():
    legs = [_leg("EUR", 0.04, 500_000.0, 100_000.0, 5), _leg("AUD", 0.04, 300_000.0, 75_000.0, 4)]
    res = compute_fx_carry_tilt(SimpleNamespace(legs=legs, hedge_notional_usd=800_000.0), tilt_strength=1.0)
    assert res is not None
    assert res.carry_impact_usd == pytest.approx(0.0, abs=1e-6)
    for r in res.rows:
        assert r["delta_contracts"] == 0


def test_no_legs_returns_none():
    assert compute_fx_carry_tilt(SimpleNamespace(legs=[], hedge_notional_usd=0.0)) is None
