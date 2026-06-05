"""Unit tests for the FX Hedging Advisor domain core.

All tests inject a synthetic spot loader and an explicit ``now`` so the suite is
fully hermetic (no Yahoo / network access) and deterministic.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest

from market_helper.domain.portfolio_monitor.services.fx_hedge_advisor import (
    FxHedgeComputationError,
    FxHedgeConfig,
    FxInstrumentSpec,
    build_weekly_return_panel,
    compute_fx_hedge_allocation,
    estimate_hedge_ratios,
    load_fx_hedge_allocation,
    load_fx_hedge_config,
    next_quarterly_imm_expiry,
    provide_fx_hedge_allocation,
    write_fx_hedge_allocation,
    _round_contracts,
)
from market_helper.data_sources.yahoo_finance import YahooFinanceTransientError


TRUE_BETAS = {"EUR": 0.45, "GBP": 0.10, "AUD": 0.25, "JPY": 0.15, "CNH": 0.40}
# Realistic USD-per-unit spot levels so contract counts are sensible.
SPOT_LEVELS = {"EUR": 1.08, "GBP": 1.27, "AUD": 0.66, "JPY": 0.0067, "CNH": 0.138}


def _make_config(**overrides) -> FxHedgeConfig:
    instruments = (
        FxInstrumentSpec("EUR", "EUR/USD (6E)", "6E", "EURUSD=X", False, 125000, "EUR", False, 0.025),
        FxInstrumentSpec("GBP", "GBP/USD (6B)", "6B", "GBPUSD=X", False, 62500, "GBP", False, 0.045),
        FxInstrumentSpec("AUD", "AUD/USD (6A)", "6A", "AUDUSD=X", False, 100000, "AUD", False, 0.035),
        FxInstrumentSpec("JPY", "JPY/USD (6J)", "6J", "JPY=X", True, 12500000, "JPY", False, 0.005),
        FxInstrumentSpec("CNH", "USD/CNH (CNH)", "CNH", "CNH=X", True, 100000, "USD", True, 0.018),
    )
    base = dict(
        base_currency="SGD",
        target_pair="USD/SGD",
        target_currency="SGD",
        target_yahoo_symbol="SGD=X",
        target_invert=True,
        price_basis="usd_per_unit",
        frequency="W-FRI",
        overlapping=False,
        return_method="log",
        lookback_weeks=156,
        min_observations=52,
        max_age_days=30,
        default_hedge_notional_usd=1_000_000.0,
        on_rate_usd=0.043,
        on_rates_as_of="2026-05-01",
        on_rates_source="configured (test)",
        instruments=instruments,
    )
    base.update(overrides)
    return FxHedgeConfig(**base)


def _synthetic_loader(seed: int = 7, *, already_usd_per_unit: bool = True):
    """Build a loader where the target is a known linear basket of regressors.

    Returns ``(loader, currency_by_symbol)``. The loader ignores ``invert`` and
    returns USD-per-unit prices directly — the regression core only cares that
    the target/regressor return relationship matches ``TRUE_BETAS``.
    """
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2021-01-01", periods=950)
    inst_rets = {c: rng.normal(0, 0.01, len(idx)) for c in TRUE_BETAS}
    target_ret = sum(TRUE_BETAS[c] * inst_rets[c] for c in TRUE_BETAS) + rng.normal(0, 0.0008, len(idx))

    def _price(rets, start):
        return pd.Series(start * np.exp(np.cumsum(rets)), index=idx)

    prices = {c: _price(inst_rets[c], SPOT_LEVELS[c]) for c in TRUE_BETAS}
    target_price = _price(target_ret, 0.74)
    by_symbol = {
        "EURUSD=X": "EUR", "GBPUSD=X": "GBP", "AUDUSD=X": "AUD",
        "JPY=X": "JPY", "CNH=X": "CNH",
    }

    def loader(symbol: str, invert: bool) -> pd.Series:
        if symbol == "SGD=X":
            return target_price
        return prices[by_symbol[symbol]]

    return loader


# --------------------------------------------------------------------------- #
# Config
# --------------------------------------------------------------------------- #
def test_load_committed_config_has_five_instruments_and_conventions() -> None:
    cfg = load_fx_hedge_config()
    assert cfg.base_currency == "SGD"
    assert cfg.target_currency == "SGD" and cfg.target_invert is True
    assert [i.currency for i in cfg.instruments] == ["EUR", "GBP", "AUD", "JPY", "CNH"]
    # JPY and CNH Yahoo quotes need inverting to reach USD-per-unit; majors don't.
    inverts = {i.currency: i.invert for i in cfg.instruments}
    assert inverts == {"EUR": False, "GBP": False, "AUD": False, "JPY": True, "CNH": True}
    # CNH future is USD-sized; the rest are foreign-currency-sized.
    usd_sized = {i.currency: i.usd_sized for i in cfg.instruments}
    assert usd_sized["CNH"] is True and usd_sized["EUR"] is False
    assert cfg.max_age_days == 30


# --------------------------------------------------------------------------- #
# Regression + panel
# --------------------------------------------------------------------------- #
def test_regression_recovers_known_betas() -> None:
    cfg = _make_config()
    target, regressors, latest = build_weekly_return_panel(cfg, spot_loader=_synthetic_loader())
    result = estimate_hedge_ratios(target, regressors)
    assert result.r_squared > 0.9
    for currency, true_beta in TRUE_BETAS.items():
        assert result.betas[currency] == pytest.approx(true_beta, abs=0.03)
        assert result.t_stats[currency] > 3  # all legs significant
    # Latest spot carried for contract sizing (one positive level per currency).
    assert set(latest) == set(TRUE_BETAS)
    assert all(value > 0 for value in latest.values())


def test_panel_respects_lookback_and_min_observations() -> None:
    cfg = _make_config(lookback_weeks=120)
    target, _, _ = build_weekly_return_panel(cfg, spot_loader=_synthetic_loader())
    assert len(target) == 120
    # Too-strict min raises rather than fitting on thin data.
    strict = _make_config(lookback_weeks=10, min_observations=200)
    with pytest.raises(FxHedgeComputationError):
        build_weekly_return_panel(strict, spot_loader=_synthetic_loader())


def test_overlapping_windows_produce_more_observations_than_calendar_weeks() -> None:
    weekly = _make_config(overlapping=False, lookback_weeks=10_000)
    overlap = _make_config(overlapping=True, lookback_weeks=10_000)
    w_target, _, _ = build_weekly_return_panel(weekly, spot_loader=_synthetic_loader())
    o_target, _, _ = build_weekly_return_panel(overlap, spot_loader=_synthetic_loader())
    assert len(o_target) > len(w_target)


def test_missing_target_history_raises() -> None:
    cfg = _make_config()

    def loader(symbol: str, invert: bool) -> pd.Series:
        if symbol == "SGD=X":
            return pd.Series(dtype=float)
        return pd.Series([1.0, 1.1], index=pd.bdate_range("2024-01-01", periods=2))

    with pytest.raises(FxHedgeComputationError):
        build_weekly_return_panel(cfg, spot_loader=loader)


# --------------------------------------------------------------------------- #
# Expiry + rounding
# --------------------------------------------------------------------------- #
def test_next_quarterly_imm_expiry_is_third_wednesday_and_rolls() -> None:
    # Known-good anchors.
    assert next_quarterly_imm_expiry(date(2026, 6, 3)) == date(2026, 6, 17)
    # Within a week of the June expiry → roll to September.
    assert next_quarterly_imm_expiry(date(2026, 6, 15)) == date(2026, 9, 16)
    # December → next year's March.
    assert next_quarterly_imm_expiry(date(2026, 12, 20)) == date(2027, 3, 17)
    for anchor in (date(2026, 1, 1), date(2026, 7, 30), date(2027, 11, 2)):
        expiry = next_quarterly_imm_expiry(anchor)
        assert expiry.weekday() == 2  # Wednesday
        assert 15 <= expiry.day <= 21  # third Wednesday
        assert expiry.month in (3, 6, 9, 12)


def test_round_contracts_half_away_from_zero() -> None:
    assert _round_contracts(0.5) == 1
    assert _round_contracts(-0.5) == -1
    assert _round_contracts(2.4) == 2
    assert _round_contracts(-2.6) == -3
    assert _round_contracts(0.0) == 0
    assert _round_contracts(float("nan")) == 0


# --------------------------------------------------------------------------- #
# Full allocation
# --------------------------------------------------------------------------- #
def test_compute_allocation_contract_math_and_carry_signs() -> None:
    cfg = _make_config()
    alloc = compute_fx_hedge_allocation(
        config=cfg,
        hedge_notional_usd=20_000_000,
        hedge_notional_source="funded_aum_usd",
        spot_loader=_synthetic_loader(),
        now=datetime(2026, 6, 3, tzinfo=timezone.utc),
    )
    assert alloc.run_date == "2026-06-03"
    assert alloc.hedge_target_pair == "USD/SGD"
    assert {leg.currency for leg in alloc.legs} == set(TRUE_BETAS)

    for leg in alloc.legs:
        # target notional = beta * hedge notional
        assert leg.target_notional_usd == pytest.approx(leg.beta * 20_000_000)
        # USD/contract: CNH is USD-sized; others = size * spot.
        if leg.currency == "CNH":
            assert leg.usd_notional_per_contract == pytest.approx(100_000)
        else:
            assert leg.usd_notional_per_contract == pytest.approx(
                leg.contract_size * leg.spot_usd_per_unit
            )
        # realized = contracts * usd/contract; residual = target - realized.
        assert leg.realized_notional_usd == pytest.approx(
            leg.target_contracts * leg.usd_notional_per_contract
        )
        assert leg.residual_notional_usd == pytest.approx(
            leg.target_notional_usd - leg.realized_notional_usd
        )
        # Long foreign leg with foreign ON < USD ON → negative carry.
        if leg.realized_notional_usd > 0:
            expected_sign = np.sign(leg.on_rate - cfg.on_rate_usd)
            assert np.sign(leg.expected_annual_carry_usd) == expected_sign

    totals = alloc.totals
    assert totals["hedge_quality_r_squared"] == pytest.approx(
        alloc.regression["r_squared"]
    )
    assert 0.0 <= totals["statistical_unhedged_fraction"] <= 1.0
    assert totals["expected_annual_carry_usd"] == pytest.approx(
        sum(leg.expected_annual_carry_usd for leg in alloc.legs)
    )


def test_allocation_artifact_round_trips(tmp_path) -> None:
    cfg = _make_config()
    alloc = compute_fx_hedge_allocation(
        config=cfg,
        hedge_notional_usd=5_000_000,
        hedge_notional_source="test",
        spot_loader=_synthetic_loader(),
        now=datetime(2026, 6, 3, tzinfo=timezone.utc),
    )
    path = tmp_path / "fx_hedge_allocation.json"
    write_fx_hedge_allocation(alloc, path)
    reloaded = load_fx_hedge_allocation(path)
    assert reloaded is not None
    assert reloaded.hedge_target_pair == alloc.hedge_target_pair
    assert len(reloaded.legs) == len(alloc.legs)
    assert reloaded.legs[0].beta == pytest.approx(alloc.legs[0].beta)
    assert reloaded.regression["r_squared"] == pytest.approx(alloc.regression["r_squared"])
    assert load_fx_hedge_allocation(tmp_path / "nope.json") is None


# --------------------------------------------------------------------------- #
# Provider: caching + staleness + fallback
# --------------------------------------------------------------------------- #
def test_provider_caching_staleness_and_error_fallback(tmp_path) -> None:
    cfg = _make_config()
    path = tmp_path / "fx.json"
    loader = _synthetic_loader()
    t0 = datetime(2026, 6, 3, tzinfo=timezone.utc)

    # Missing + refresh-if-stale → freshly computed.
    fresh = provide_fx_hedge_allocation(
        artifact_path=path, config=cfg, mode="refresh-if-stale",
        hedge_notional_usd=5_000_000, spot_loader=loader, now=t0,
    )
    assert fresh.state == "ok" and fresh.computed_fresh is True
    assert fresh.source_label == "Freshly computed"
    assert path.exists()

    # Within max age → reuse cache, not recomputed.
    reuse = provide_fx_hedge_allocation(
        artifact_path=path, config=cfg, mode="refresh-if-stale",
        spot_loader=loader, now=t0 + timedelta(days=10),
    )
    assert reuse.computed_fresh is False and reuse.age_days == 10
    assert reuse.source_label == "Loaded from cache (10 days old)"

    # Older than max age → recompute.
    stale_refresh = provide_fx_hedge_allocation(
        artifact_path=path, config=cfg, mode="refresh-if-stale",
        spot_loader=loader, now=t0 + timedelta(days=45),
    )
    assert stale_refresh.computed_fresh is True and stale_refresh.state == "ok"

    # cached mode never recomputes; reports stale past the window.
    cached = provide_fx_hedge_allocation(
        artifact_path=path, config=cfg, mode="cached",
        spot_loader=loader, now=t0 + timedelta(days=400),
    )
    assert cached.computed_fresh is False and cached.state == "stale"

    # Compute failure falls back to the cached allocation, tagged error.
    def boom(symbol: str, invert: bool) -> pd.Series:
        raise YahooFinanceTransientError("rate limited")

    errored = provide_fx_hedge_allocation(
        artifact_path=path, config=cfg, mode="force-refresh",
        spot_loader=boom, now=t0, hedge_notional_usd=5_000_000,
    )
    assert errored.state == "error" and errored.allocation is not None
    assert "rate limited" in (errored.error_message or "")


def test_provider_missing_in_cached_mode_returns_missing(tmp_path) -> None:
    cfg = _make_config()
    state = provide_fx_hedge_allocation(
        artifact_path=tmp_path / "absent.json", config=cfg, mode="cached",
        now=datetime(2026, 6, 3, tzinfo=timezone.utc),
    )
    assert state.state == "missing" and state.allocation is None
    assert state.is_renderable is False
