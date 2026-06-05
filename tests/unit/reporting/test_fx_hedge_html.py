"""Tests for the Risk → FX *Target FX Allocation* renderer."""

from __future__ import annotations

from datetime import datetime, timezone

from market_helper.domain.portfolio_monitor.services.fx_hedge_advisor import (
    FxHedgeAllocation,
    FxHedgeArtifactState,
    FxHedgeLeg,
)
from market_helper.reporting.fx_hedge_html import (
    fx_hedge_section_styles,
    render_fx_hedge_section,
)


def _leg(currency: str, instrument: str, beta: float, contracts: int) -> FxHedgeLeg:
    usd_per_contract = 125_000.0
    target = beta * 10_000_000
    realized = contracts * usd_per_contract
    return FxHedgeLeg(
        currency=currency,
        instrument=instrument,
        futures_root="6E",
        yahoo_symbol="EURUSD=X",
        beta=beta,
        beta_std_error=0.05,
        t_stat=beta / 0.05,
        spot_usd_per_unit=1.08,
        target_notional_usd=target,
        contract_size=125_000,
        contract_size_currency="EUR",
        usd_notional_per_contract=usd_per_contract,
        target_contracts=contracts,
        realized_notional_usd=realized,
        residual_notional_usd=target - realized,
        on_rate=0.025,
        expected_annual_carry_usd=realized * (0.025 - 0.043),
        expiry="2026-06-17",
    )


def _allocation() -> FxHedgeAllocation:
    legs = (
        _leg("EUR", "EUR/USD (6E)", 0.42, 3),
        _leg("CNH", "USD/CNH (CNH)", 0.40, -2),
    )
    return FxHedgeAllocation(
        schema_version=1,
        run_date="2026-06-03",
        generated_at="2026-06-03T00:00:00+00:00",
        base_currency="SGD",
        hedge_target_pair="USD/SGD",
        hedge_target_yahoo="SGD=X",
        target_definition="r_tgt = Δln(USD per SGD); hedge = long Σβᵢ·A short USD.",
        return_convention={
            "price_basis": "usd_per_unit",
            "frequency": "W-FRI",
            "overlapping": False,
            "return_method": "log",
            "lookback_weeks": 156,
        },
        data_source="yahoo_finance",
        hedge_notional_usd=10_000_000.0,
        hedge_notional_source="funded_aum_usd",
        data_window={"start": "2023-06-02", "end": "2026-05-29", "observations": 156},
        regression={
            "r_squared": 0.78,
            "adj_r_squared": 0.77,
            "alpha_weekly": 0.0001,
            "residual_vol_annualized": 0.03,
        },
        legs=legs,
        totals={
            "target_notional_usd_gross": 8_200_000.0,
            "realized_notional_usd_gross": 575_000.0,
            "realized_notional_usd_net": 125_000.0,
            "rounding_residual_usd": 12_345.0,
            "hedge_quality_r_squared": 0.78,
            "statistical_unhedged_fraction": 0.22,
            "statistical_unhedged_notional_usd": 4_690_000.0,
            "expected_annual_carry_usd": -8_500.0,
            "expected_annual_carry_bps": -8.5,
        },
        on_rates_as_of="2026-05-01",
        on_rates_source="configured (indicative)",
        max_age_days=30,
    )


def _state(**overrides) -> FxHedgeArtifactState:
    base = dict(
        state="ok",
        mode_used="refresh-if-stale",
        allocation=_allocation(),
        computed_fresh=True,
        age_days=0,
        last_run_at=datetime(2026, 6, 3, tzinfo=timezone.utc),
        error_message=None,
    )
    base.update(overrides)
    return FxHedgeArtifactState(**base)  # type: ignore[arg-type]


def test_render_populated_section_has_anchor_conventions_and_legs() -> None:
    html = render_fx_hedge_section(_state())
    assert "id='fx-hedge'" in html
    assert "Target FX Allocation" in html
    assert "USD/SGD" in html
    # Acceptance: states whether freshly computed or loaded from cache.
    assert "Freshly computed" in html
    # Explicit conventions block is present.
    assert "Conventions" in html
    assert "fx_usdsgd_eod" in html  # documents the inverse-of-repo basis
    assert "long the foreign currency" in html
    # Both legs render with direction wording.
    assert "EUR/USD (6E)" in html
    assert "USD/CNH (CNH)" in html
    assert "Long 3" in html and "Short 2" in html
    # Hedge-quality + window + expiry surfaced.
    assert "78.0%" in html  # R²
    assert "2026-06-17" in html  # expiry
    assert "156 weekly obs" in html


def test_render_cache_badge_shows_age() -> None:
    html = render_fx_hedge_section(
        _state(computed_fresh=False, age_days=12, state="ok")
    )
    assert "Loaded from cache (12 days old)" in html
    assert "Freshly computed" not in html


def test_render_missing_and_error_states_render_explainer() -> None:
    missing = render_fx_hedge_section(
        FxHedgeArtifactState(
            state="missing", mode_used="cached", allocation=None,
            computed_fresh=False, age_days=None, last_run_at=None,
            error_message="absent",
        )
    )
    assert "id='fx-hedge'" in missing
    assert "not yet computed" in missing
    assert "fx-hedge-report" in missing  # actionable hint

    errored = render_fx_hedge_section(
        FxHedgeArtifactState(
            state="error", mode_used="force-refresh", allocation=None,
            computed_fresh=False, age_days=None, last_run_at=None,
            error_message="feed down",
        )
    )
    assert "failed" in errored and "feed down" in errored


def test_styles_define_badges() -> None:
    css = fx_hedge_section_styles()
    assert ".fx-badge--fresh" in css and ".fx-badge--cache" in css
