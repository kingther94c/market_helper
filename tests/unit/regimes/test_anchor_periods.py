"""Pinned anchor-period sanity tests for the regime engine.

Guards against silent regressions when calibration parameters change. The
fixture under ``fixtures/`` is a slice of the Yahoo-sourced market panel that
covers a known macro episode (here: the COVID-19 crash, Feb-Apr 2020, plus
roughly a year of warm-up before and recovery after). The test runs the
production market-implied layer config against that slice and asserts:

  - the pre-crisis date sits in a benign growth-up regime,
  - the crisis date trips the risk overlay and prints deep-negative scores,
  - the recovery date prints positive growth and inflation scores.

Macro layer is intentionally disabled because the FRED panel is not checked
into the repo (regenerating it requires ``FRED_API_KEY`` + ``fred-macro-sync``;
see ``DEV_DOCS/docs/devplans/regime_engine_devplan.md`` for the activation
runbook). The market layer alone is enough to catch the kinds of regressions
this harness is designed to surface (signal weights, normalization windows,
hysteresis thresholds, risk-overlay enter/exit, beta-adjustment math).

To regenerate the fixture after a config change that materially shifts the
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
FIXTURE_PATH = Path(__file__).parent / "fixtures" / "market_panel_covid_2020.feather"
REGIME_ENGINE_CONFIG = REPO_ROOT / "configs" / "regime_detection" / "regime_engine.yml"
MARKET_REGIME_CONFIG = REPO_ROOT / "configs" / "regime_detection" / "market_regime.yml"


@pytest.fixture(scope="module")
def covid_engine_results():
    panel = pd.read_feather(FIXTURE_PATH)
    cfg = load_regime_engine_config(REGIME_ENGINE_CONFIG)
    # Disable macro + ML layers — fixture is market-only.
    cfg.layers["macro_nowcast"] = LayerConfig(enabled=False)
    cfg.layers["macro_truth_ml"] = LayerConfig(enabled=False, model_type="svm")
    cfg.layers["return_truth_ml"] = LayerConfig(enabled=False, model_type="svm")
    market_cfg = load_market_regime_config(MARKET_REGIME_CONFIG)
    results = run_regime_engine_v2(config=cfg, market_panel=panel, market_config=market_cfg)
    return {str(r.date)[:10]: r for r in results}


def test_pre_crisis_2020_02_21_is_benign_growth(covid_engine_results) -> None:
    # Last trading day before the COVID waterfall — markets at all-time highs,
    # vol still anchored, no stress overlay yet.
    result = covid_engine_results["2020-02-21"]
    assert result.risk_overlay_on is False, (
        f"Expected no stress overlay pre-crisis but got risk_on=True, regime={result.final_regime!r}"
    )
    assert result.final_growth_score > 0.0, (
        f"Expected growth>0 pre-crisis but got {result.final_growth_score:.3f}"
    )
    # Goldilocks / Expansion is the only positive-growth, low-inflation
    # quadrant; if the label shifts to a different positive-growth quadrant,
    # something changed in the inflation-score sign convention.
    assert "Goldilocks" in result.final_regime or "Expansion" in result.final_regime, (
        f"Expected Goldilocks/Expansion family pre-crisis but got {result.final_regime!r}"
    )


def test_crisis_2020_03_18_trips_stress_and_deep_negative_scores(
    covid_engine_results,
) -> None:
    # Within days of the March 23 cycle bottom; this is the cleanest
    # high-vol, growth-collapse, oil-collapse signature the engine should
    # ever see and is the strongest single-date regression guard we have.
    result = covid_engine_results["2020-03-18"]
    assert result.risk_overlay_on is True, (
        f"Expected stress overlay on at COVID bottom but got risk_on=False, regime={result.final_regime!r}"
    )
    assert "Stress Overlay" in result.final_regime, (
        f"Expected 'Stress Overlay' tag but got {result.final_regime!r}"
    )
    assert result.final_growth_score < -0.3, (
        f"Expected deep-negative growth score but got {result.final_growth_score:.3f}"
    )
    # Oil collapsed and breakevens crashed in March 2020 — inflation axis
    # should print clearly negative here.
    assert result.final_inflation_score < -0.3, (
        f"Expected deep-negative inflation score but got {result.final_inflation_score:.3f}"
    )


def test_recovery_2020_06_15_shows_positive_growth_and_reflation(
    covid_engine_results,
) -> None:
    # Mid-June 2020 — equities have retraced most of the drawdown, copper
    # and oil are off the lows, vol still elevated but trending down. This
    # should land somewhere in the Reflation / positive-growth family.
    result = covid_engine_results["2020-06-15"]
    assert result.final_growth_score > 0.0, (
        f"Expected growth>0 in recovery but got {result.final_growth_score:.3f}"
    )
    assert result.final_inflation_score > 0.0, (
        f"Expected inflation>0 in recovery but got {result.final_inflation_score:.3f}"
    )
