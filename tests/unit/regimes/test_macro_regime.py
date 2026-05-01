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
