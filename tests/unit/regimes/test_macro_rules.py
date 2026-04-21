from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from market_helper.data_sources.fred.macro_panel import SeriesSpec
from market_helper.regimes.axes import (
    QUADRANT_DEFLATIONARY_SLOWDOWN,
    QUADRANT_GOLDILOCKS,
    QUADRANT_REFLATION,
    QUADRANT_STAGFLATION,
)
from market_helper.regimes.methods.macro_rules import (
    MacroRulesConfig,
    MacroRulesMethod,
    compute_axis_scores,
)


def _panel(values: dict[str, list[float]]) -> pd.DataFrame:
    n = len(next(iter(values.values())))
    dates = pd.bdate_range("2018-01-01", periods=n)
    return pd.DataFrame({"date": dates, **values})


def _specs(axis_map: dict[str, str]) -> list[SeriesSpec]:
    return [
        SeriesSpec(
            series_id=sid,
            axis=axis,
            transform="level",
            weight=1.0,
        )
        for sid, axis in axis_map.items()
    ]


def test_axis_scores_positive_when_series_rises_above_history() -> None:
    # 260 business days of flat values, then one print that spikes above mean.
    # The last day's rolling z should be strongly positive.
    baseline = [0.0] * 260
    trace = baseline + [5.0]
    panel = _panel({"G1": trace})
    specs = _specs({"G1": "growth"})
    cfg = MacroRulesConfig(
        zscore_window_bdays=260,
        min_periods=20,
        zscore_clip=3.0,
        min_consecutive_days=1,
    )
    scores = compute_axis_scores(panel, specs, config=cfg)
    last = scores.iloc[-1]
    assert last["growth"] > 1.0
    assert np.isnan(last["inflation"])


def test_axis_scores_respect_weights() -> None:
    # Two inflation series: one strongly positive, one strongly negative, with
    # unequal weights. Weighted mean should reflect the heavier one.
    up = [0.0] * 250 + [10.0]
    down = [0.0] * 250 + [-10.0]
    panel = _panel({"UP": up, "DOWN": down})
    specs = [
        SeriesSpec(series_id="UP", axis="inflation", transform="level", weight=3.0),
        SeriesSpec(series_id="DOWN", axis="inflation", transform="level", weight=1.0),
    ]
    cfg = MacroRulesConfig(
        zscore_window_bdays=250,
        min_periods=20,
        zscore_clip=10.0,
        min_consecutive_days=1,
    )
    scores = compute_axis_scores(panel, specs, config=cfg)
    last = scores.iloc[-1]
    assert last["inflation"] > 0.0  # heavier weight wins


def test_macro_rules_method_produces_quadrant_per_date() -> None:
    # Construct an obvious case: growth spikes up, inflation drops below mean.
    # After warmup, the last rows should land in Goldilocks.
    n = 300
    # inflation rolls slowly negative; growth spikes up at the end
    growth_vals = [0.0] * (n - 20) + [5.0] * 20
    inflation_vals = [0.0] * (n - 20) + [-5.0] * 20
    panel = _panel({"G": growth_vals, "I": inflation_vals})
    specs = _specs({"G": "growth", "I": "inflation"})
    cfg = MacroRulesConfig(
        zscore_window_bdays=260,
        min_periods=20,
        zscore_clip=3.0,
        min_consecutive_days=3,
        warmup_bdays=20,
    )
    method = MacroRulesMethod(specs, config=cfg)
    results = method.classify(panel)
    assert results, "method should emit at least one result"
    assert results[-1].quadrant.quadrant == QUADRANT_GOLDILOCKS
    # Hysteresis should report a duration >= 3 by the last day (consecutive regime).
    assert results[-1].quadrant.duration_days >= 3
    # Drivers carry the signed contribution of each series.
    assert "G" in results[-1].quadrant.axes.growth_drivers
    assert "I" in results[-1].quadrant.axes.inflation_drivers


def test_macro_rules_method_all_four_quadrants_reachable() -> None:
    # Build a panel where the last day for each scenario lands in a known quadrant.
    # Use two series (one per axis), with last value chosen to force sign.
    def last_quadrant(growth_last: float, inflation_last: float) -> str:
        g = [0.0] * 260 + [growth_last]
        i = [0.0] * 260 + [inflation_last]
        panel = _panel({"G": g, "I": i})
        specs = _specs({"G": "growth", "I": "inflation"})
        cfg = MacroRulesConfig(
            zscore_window_bdays=260,
            min_periods=20,
            zscore_clip=5.0,
            min_consecutive_days=1,
            warmup_bdays=0,
        )
        method = MacroRulesMethod(specs, config=cfg)
        results = method.classify(panel)
        return results[-1].quadrant.quadrant

    assert last_quadrant(5.0, -5.0) == QUADRANT_GOLDILOCKS
    assert last_quadrant(5.0, 5.0) == QUADRANT_REFLATION
    assert last_quadrant(-5.0, 5.0) == QUADRANT_STAGFLATION
    assert last_quadrant(-5.0, -5.0) == QUADRANT_DEFLATIONARY_SLOWDOWN


def test_macro_rules_method_empty_panel_returns_empty() -> None:
    specs = _specs({"G": "growth"})
    method = MacroRulesMethod(specs)
    assert method.classify(pd.DataFrame()) == []


def test_macro_rules_method_warmup_drops_prefix() -> None:
    n = 300
    panel = _panel({"G": [float(i) for i in range(n)], "I": [0.0] * n})
    specs = _specs({"G": "growth", "I": "inflation"})
    cfg = MacroRulesConfig(
        zscore_window_bdays=260,
        min_periods=20,
        zscore_clip=3.0,
        min_consecutive_days=1,
        warmup_bdays=50,
    )
    method = MacroRulesMethod(specs, config=cfg)
    results = method.classify(panel)
    # Warmup shouldn't emit from day 0; earliest emission date must be >= day 50.
    assert pd.Timestamp(results[0].as_of) >= pd.bdate_range("2018-01-01", periods=51)[-1]
