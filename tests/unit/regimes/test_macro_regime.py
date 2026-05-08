from __future__ import annotations

import pandas as pd
import pytest

from market_helper.data_sources.fred.macro_panel import SeriesSpec
from market_helper.regimes.axes import QUADRANT_GOLDILOCKS
from market_helper.regimes.methods.macro_regime import (
    MacroRegimeConfig,
    MacroRegimeMethod,
    compute_macro_axis_scores,
)


def test_macro_fast_slow_bucket_weights_default_70_30() -> None:
    panel = pd.DataFrame(
        {
            "date": pd.bdate_range("2024-01-01", periods=3),
            "FAST": [1.0, 1.0, 1.0],
            "SLOW": [-1.0, -1.0, -1.0],
        }
    )
    specs = [
        SeriesSpec(series_id="FAST", axis="growth", transform="level", bucket="fast"),
        SeriesSpec(series_id="SLOW", axis="growth", transform="level", bucket="slow"),
    ]
    scores = compute_macro_axis_scores(panel, specs)
    assert scores.iloc[-1]["growth"] == pytest.approx(0.4)


def test_macro_raw_sign_classifies_without_zscore() -> None:
    panel = pd.DataFrame(
        {
            "date": pd.bdate_range("2024-01-01", periods=5),
            "G": [1.0] * 5,
            "I": [-1.0] * 5,
        }
    )
    specs = [
        SeriesSpec(series_id="G", axis="growth", transform="level", bucket="fast"),
        SeriesSpec(series_id="I", axis="inflation", transform="level", bucket="fast"),
    ]
    method = MacroRegimeMethod(
        specs, config=MacroRegimeConfig(min_consecutive_days=1)
    )
    results = method.classify(panel)
    assert results[-1].quadrant.quadrant == QUADRANT_GOLDILOCKS


def test_macro_minmax_normalization_scales_into_configured_bounds() -> None:
    panel = pd.DataFrame(
        {
            "date": pd.bdate_range("2024-01-01", periods=10),
            "G": [-2.0, -1.0, 0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0],
        }
    )
    specs = [
        SeriesSpec(
            series_id="G",
            axis="growth",
            transform="level",
            bucket="fast",
            normalization="minmax",
            minmax_lower=-1.0,
            minmax_upper=1.0,
            minmax_window_bdays=5,
        )
    ]
    scores = compute_macro_axis_scores(panel, specs)
    growth = scores["growth"].dropna()
    assert ((growth >= -1.0 - 1e-9) & (growth <= 1.0 + 1e-9)).all()
    # The latest value sits at the top of its rolling window so the contribution
    # should clamp to the upper bound.
    assert growth.iloc[-1] == pytest.approx(1.0)


def test_macro_percentile_normalization_returns_values_in_minus_one_to_one() -> None:
    panel = pd.DataFrame(
        {
            "date": pd.bdate_range("2024-01-01", periods=12),
            "G": list(range(12)),
        }
    )
    specs = [
        SeriesSpec(
            series_id="G",
            axis="growth",
            transform="level",
            bucket="fast",
            normalization="percentile",
            percentile_window_bdays=10,
        )
    ]
    scores = compute_macro_axis_scores(panel, specs)
    growth = scores["growth"].dropna()
    assert ((growth >= -1.0 - 1e-9) & (growth <= 1.0 + 1e-9)).all()
    assert growth.iloc[-1] == pytest.approx(1.0)


def test_macro_engine_block_round_trip_through_yaml(tmp_path) -> None:
    from market_helper.regimes.methods.macro_regime import load_macro_regime_config

    config_path = tmp_path / "fred_series.yml"
    config_path.write_text(
        "engine:\n"
        "  bucket_weights: {fast: 0.6, slow: 0.4}\n"
        "  zscore_window_bdays: 100\n"
        "  zscore_clip: 2.5\n"
        "  min_consecutive_days: 7\n"
        "series: []\n"
    )
    cfg = load_macro_regime_config(config_path)
    assert cfg.bucket_weights == {"fast": 0.6, "slow": 0.4}
    assert cfg.zscore_window_bdays == 100
    assert cfg.zscore_clip == 2.5
    assert cfg.min_consecutive_days == 7


def test_macro_per_series_zscore_window_overrides_engine_default() -> None:
    panel = pd.DataFrame(
        {
            "date": pd.bdate_range("2024-01-01", periods=200),
            "G": [float(i) for i in range(200)],
        }
    )
    spec_default = SeriesSpec(
        series_id="G",
        axis="growth",
        transform="level",
        bucket="fast",
        normalization="zscore",
    )
    spec_override = SeriesSpec(
        series_id="G",
        axis="growth",
        transform="level",
        bucket="fast",
        normalization="zscore",
        zscore_window_bdays=20,
        zscore_min_periods=20,
    )
    config = MacroRegimeConfig(zscore_window_bdays=2520, min_periods=252)
    default_score = compute_macro_axis_scores(panel, [spec_default], config=config).iloc[-1]
    override_score = compute_macro_axis_scores(panel, [spec_override], config=config).iloc[-1]
    # With min_periods=252 on 200 rows, the engine default produces NaN; the
    # per-series override (20-day window) yields a finite z-score.
    import math as _math
    assert _math.isnan(default_score["growth"])
    assert not _math.isnan(override_score["growth"])
