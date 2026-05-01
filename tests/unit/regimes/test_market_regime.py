from __future__ import annotations

import pandas as pd

from market_helper.regimes.axes import QUADRANT_GOLDILOCKS
from market_helper.regimes.methods.market_regime import (
    MarketRegimeConfig,
    MarketRegimeMethod,
    MarketSignalSpec,
    compute_market_axis_scores,
)


def _panel(n: int = 100) -> pd.DataFrame:
    dates = pd.bdate_range("2024-01-01", periods=n)
    vix = [15.0] * n
    if n > 20:
        vix[-20:] = [40.0] * 20
    return pd.DataFrame(
        {
            "date": dates,
            "SPY": [100.0 + idx for idx in range(n)],
            "USO": [100.0 - idx * 0.2 for idx in range(n)],
            "VIX": vix,
        }
    )


def test_market_raw_sign_growth_inflation_mapping() -> None:
    cfg = MarketRegimeConfig(
        signals=[
            MarketSignalSpec(
                name="spy",
                axis="growth",
                symbol="SPY",
                transform="raw_sign",
                lookback_days=1,
            ),
            MarketSignalSpec(
                name="oil",
                axis="inflation",
                symbol="USO",
                transform="raw_sign",
                lookback_days=1,
            ),
        ],
        min_consecutive_days=1,
    )
    method = MarketRegimeMethod(cfg)
    results = method.classify(_panel(10))
    assert results[-1].quadrant.quadrant == QUADRANT_GOLDILOCKS


def test_market_risk_overlay_triggers_on_high_vix() -> None:
    cfg = MarketRegimeConfig(
        signals=[
            MarketSignalSpec(
                name="spy",
                axis="growth",
                symbol="SPY",
                transform="raw_sign",
                lookback_days=1,
            ),
            MarketSignalSpec(
                name="oil",
                axis="inflation",
                symbol="USO",
                transform="raw_sign",
                lookback_days=1,
            ),
            MarketSignalSpec(
                name="vix",
                axis="risk",
                symbol="VIX",
                transform="level_zscore",
                zscore_window_days=30,
            ),
        ],
        min_consecutive_days=1,
        risk_min_consecutive_days=1,
        risk_enter_threshold=0.5,
    )
    results = MarketRegimeMethod(cfg).classify(_panel())
    assert results[-1].quadrant.crisis_flag is True
    assert results[-1].quadrant.diagnostics["risk_regime"] == "risk_off"


def test_market_axis_scores_include_driver_contributions() -> None:
    cfg = MarketRegimeConfig(
        signals=[
            MarketSignalSpec(
                name="spy",
                axis="growth",
                symbol="SPY",
                transform="raw_sign",
                lookback_days=1,
            )
        ]
    )
    scores = compute_market_axis_scores(_panel(10), cfg)
    assert "contrib:spy" in scores.columns
