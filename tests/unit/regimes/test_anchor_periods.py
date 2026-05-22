"""Pinned anchor-period sanity tests for the regime engine.

Guards against silent regressions when calibration parameters change. Each
fixture under ``fixtures/`` is a slice of the Yahoo-sourced market panel
covering a known macro episode plus enough warm-up for the engine's
normalization windows. The tests run the production market-implied layer
config against each slice and assert what the market layer SHOULD see —
honest about the limits of a market-only view.

Why market-only: the FRED macro panel is not checked into the repo
(regenerating it requires ``FRED_API_KEY`` + ``fred-macro-sync``;
see ``DEV_DOCS/docs/devplans/regime_engine_devplan.md`` for the activation
runbook). The market layer alone catches the regressions this harness is
designed to surface (signal weights, normalization windows, hysteresis
thresholds, risk-overlay enter/exit, beta-adjustment math).

Known limitation surfaced by these tests: the market-implied inflation
axis reads commodity proxies (oil, copper, GSCI) and cannot match headline-
CPI consensus when commodities decouple from inflation prints. The 2022
inflation surge is the clearest example — by mid-2022 oil had peaked and
was rolling over while CPI was still north of 8%; the market layer reads
this as inflation cooling. That is a structural property of the proxy
choice, not a bug; documented in the relevant test cases.

To regenerate fixtures after a config change that materially shifts the
symbol set, run ``scripts/dev/regenerate_anchor_period_fixtures.py``.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from market_helper.regimes.engine_v2 import (
    LayerConfig,
    load_regime_engine_config,
    run_regime_engine_v2,
)
from market_helper.regimes.methods.market_regime import load_market_regime_config


REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURES_DIR = Path(__file__).parent / "fixtures"
REGIME_ENGINE_CONFIG = REPO_ROOT / "configs" / "regime_detection" / "regime_engine.yml"
MARKET_REGIME_CONFIG = REPO_ROOT / "configs" / "regime_detection" / "market_regime.yml"


def _run_market_only(fixture_filename: str) -> dict[str, object]:
    panel = pd.read_feather(FIXTURES_DIR / fixture_filename)
    cfg = load_regime_engine_config(REGIME_ENGINE_CONFIG)
    # Market-only: macro panel not in git, ML layers are placeholders.
    cfg.layers["macro_nowcast"] = LayerConfig(enabled=False)
    cfg.layers["macro_truth_ml"] = LayerConfig(enabled=False, model_type="svm")
    cfg.layers["return_truth_ml"] = LayerConfig(enabled=False, model_type="svm")
    market_cfg = load_market_regime_config(MARKET_REGIME_CONFIG)
    results = run_regime_engine_v2(config=cfg, market_panel=panel, market_config=market_cfg)
    return {str(r.date)[:10]: r for r in results}


def _any_in_window(results: dict, start: str, end: str, predicate) -> bool:
    """Return True if any date in [start, end] satisfies predicate(result)."""
    s, e = pd.Timestamp(start), pd.Timestamp(end)
    for date_str, r in results.items():
        d = pd.Timestamp(date_str)
        if s <= d <= e and predicate(r):
            return True
    return False


# ---------------------------------------------------------------------------
# COVID 2020 — clean equity + commodity + vol shock; the cleanest anchor
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def covid_engine_results():
    return _run_market_only("market_panel_covid_2020.feather")


def test_covid_pre_crisis_is_benign_growth(covid_engine_results) -> None:
    # Last trading day before the COVID waterfall — markets at all-time highs,
    # vol still anchored, no stress overlay yet.
    result = covid_engine_results["2020-02-21"]
    assert result.risk_overlay_on is False, (
        f"Expected no stress overlay pre-crisis but got risk_on=True, regime={result.final_regime!r}"
    )
    assert result.final_growth_score > 0.0
    assert "Goldilocks" in result.final_regime or "Expansion" in result.final_regime


def test_covid_crisis_2020_03_18_trips_stress_and_deep_negatives(
    covid_engine_results,
) -> None:
    # Within days of the March 23 cycle bottom; cleanest signature in the dataset.
    result = covid_engine_results["2020-03-18"]
    assert result.risk_overlay_on is True
    assert "Stress Overlay" in result.final_regime
    assert result.final_growth_score < -0.3
    assert result.final_inflation_score < -0.3, (
        "Oil collapsed and breakevens crashed Mar 2020 — inflation axis should be deep negative."
    )


def test_covid_recovery_2020_06_shows_reflation(covid_engine_results) -> None:
    result = covid_engine_results["2020-06-15"]
    assert result.final_growth_score > 0.0
    assert result.final_inflation_score > 0.0


# ---------------------------------------------------------------------------
# GFC 2008-09 — slower-developing crisis; tests the engine's ability to flag
# stress during the Sep-Nov 2008 window even though Lehman day itself may
# not trip the risk overlay immediately (consensus risk hysteresis is slow).
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def gfc_engine_results():
    return _run_market_only("market_panel_gfc_2008.feather")


def test_gfc_late_2007_softening_but_not_yet_crisis(gfc_engine_results) -> None:
    # End-2007 / early-2008: SPY had peaked in October 2007 and conditions were
    # softening (subprime headlines, BNP Paribas funds frozen Aug 9). The
    # engine should already register growth-down but stress overlay should not
    # be on yet — that comes after Bear Stearns / Lehman. This validates the
    # engine has lead-time on slow-developing crises without overreacting.
    result = gfc_engine_results["2007-12-03"]
    assert result.risk_overlay_on is False, (
        f"Engine tripped stress overlay too early (Dec 2007): regime={result.final_regime!r}"
    )
    assert result.final_growth_score < 0.0, (
        f"Late-2007 growth should already be reading negative, got {result.final_growth_score:.3f}"
    )


def test_gfc_lehman_aftermath_trips_stress(gfc_engine_results) -> None:
    # Risk overlay should fire AT LEAST ONCE during the Sep 15 - Nov 30 window.
    # Lehman day itself (2008-09-15) may lag a session or two due to hysteresis;
    # the broader stress period must register.
    assert _any_in_window(
        gfc_engine_results, "2008-09-15", "2008-11-30",
        predicate=lambda r: r.risk_overlay_on,
    ), "Risk overlay never fired during the Sep-Nov 2008 stress window"


def test_gfc_2008_11_20_max_drawdown_is_deep_negative(gfc_engine_results) -> None:
    # Nov 20 2008: peak drawdown / Citi near collapse. Deepest signature.
    result = gfc_engine_results["2008-11-20"]
    assert result.risk_overlay_on is True
    assert result.final_growth_score < -0.5
    assert result.final_inflation_score < -0.5, (
        "Commodity collapse in Q4 2008 should drive inflation axis deeply negative."
    )


def test_gfc_recovery_2009_07_shows_reflation(gfc_engine_results) -> None:
    # Mid-2009: SPY +40% off March low, copper +60%, vol falling.
    result = gfc_engine_results["2009-07-15"]
    assert result.final_growth_score > 0.0
    assert "Reflation" in result.final_regime or "Goldilocks" in result.final_regime


# ---------------------------------------------------------------------------
# 2022 inflation surge — market-only LIMITATION case. Commodity proxies see
# oil/copper peaking then rolling over (mid-2022 onwards) while CPI stays
# 8-9% YoY. Market layer cannot match the macro narrative; the test pins
# the GROWTH-axis behavior (which is the market layer's strong suit) and
# documents the inflation-proxy disconnect rather than asserting on it.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def inflation_engine_results():
    return _run_market_only("market_panel_inflation_2022.feather")


def test_inflation_2022_mid_year_growth_drawdown_registers(inflation_engine_results) -> None:
    # H1 2022 was the worst SPY drawdown since GFC. Growth axis must catch it.
    # We look for the negative-growth signature during the mid-year window,
    # not on any single exact date — Fed meetings and CPI prints sit in
    # different sessions each cycle.
    assert _any_in_window(
        inflation_engine_results, "2022-06-01", "2022-07-15",
        predicate=lambda r: r.final_growth_score < -0.3,
    ), "Engine never read deep-negative growth during the mid-2022 drawdown"


def test_inflation_2022_oil_peak_visible_on_inflation_axis(
    inflation_engine_results,
) -> None:
    # Oil peaked around 2022-03-08 (Brent $128) on Russia invasion shock.
    # The market-implied inflation axis should print clearly positive at
    # SOME point in Q1 2022 even if it cannot match the headline-CPI peak.
    assert _any_in_window(
        inflation_engine_results, "2022-02-15", "2022-04-30",
        predicate=lambda r: r.final_inflation_score > 0.2,
    ), (
        "Engine never saw positive inflation around the Q1 2022 oil shock. "
        "If this fires, the commodity-momentum signals likely degraded."
    )


# ---------------------------------------------------------------------------
# 2025 tariff shock — recent, clean event. Stagflation tag is the right
# answer because tariffs are a textbook stagflationary shock.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def tariff_engine_results():
    return _run_market_only("market_panel_tariff_2025.feather")


def test_tariff_2025_liberation_day_signals_stagflation_or_stress(
    tariff_engine_results,
) -> None:
    # 2025-04-02 ("Liberation Day") + 2025-04-09 (90-day pause). Either
    # day should print negative growth and a stagflation-like / stress regime.
    liberation = tariff_engine_results.get("2025-04-02")
    assert liberation is not None
    assert liberation.final_growth_score < -0.2, (
        f"Expected growth<-0.2 on tariff announce day, got {liberation.final_growth_score:.3f}"
    )
    # Stagflation = growth-down + inflation-up. Tariffs are textbook
    # stagflationary; the engine should reach for that quadrant.
    assert ("Stagflation" in liberation.final_regime) or (
        liberation.risk_overlay_on
    ), (
        f"Liberation Day landed in {liberation.final_regime!r} without stress overlay — "
        "tariff shock should produce stagflation tag OR risk overlay."
    )


def test_tariff_2025_april_window_trips_stress(tariff_engine_results) -> None:
    # The pause-day (Apr 9) is when vol peaked. Risk overlay must fire at
    # some point during the April 2-30 tariff window.
    assert _any_in_window(
        tariff_engine_results, "2025-04-02", "2025-04-30",
        predicate=lambda r: r.risk_overlay_on,
    ), "Risk overlay never fired during the April 2025 tariff shock window"
