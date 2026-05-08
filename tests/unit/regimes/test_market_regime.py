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


def test_market_transform_and_normalization_can_be_decoupled() -> None:
    cfg = MarketRegimeConfig(
        signals=[
            MarketSignalSpec(
                name="spy_level",
                axis="growth",
                symbol="SPY",
                transform="level",
                normalization="zscore",
                zscore_window_days=63,
            )
        ],
    )
    scores = compute_market_axis_scores(_panel(100), cfg)
    assert "contrib:spy_level" in scores.columns


def test_market_legacy_level_zscore_token_still_works() -> None:
    cfg = MarketRegimeConfig(
        signals=[
            MarketSignalSpec(
                name="vix_legacy",
                axis="risk",
                symbol="VIX",
                transform="level_zscore",
                zscore_window_days=63,
            )
        ],
    )
    scores = compute_market_axis_scores(_panel(100), cfg)
    assert "contrib:vix_legacy" in scores.columns


def test_market_minmax_normalization_produces_bounded_contribution() -> None:
    cfg = MarketRegimeConfig(
        signals=[
            MarketSignalSpec(
                name="spy_minmax",
                axis="growth",
                symbol="SPY",
                transform="level",
                normalization="minmax",
                minmax_lower=-1.0,
                minmax_upper=1.0,
                minmax_window_days=20,
            )
        ],
    )
    scores = compute_market_axis_scores(_panel(60), cfg)
    contrib = scores["contrib:spy_minmax"].dropna()
    assert ((contrib >= -1.0 - 1e-9) & (contrib <= 1.0 + 1e-9)).all()


def test_market_dormant_zero_weight_signal_does_not_affect_axis_score() -> None:
    base = MarketRegimeConfig(
        signals=[
            MarketSignalSpec(
                name="spy",
                axis="growth",
                symbol="SPY",
                transform="return",
                lookback_days=5,
                weight=1.0,
            )
        ],
    )
    extended = MarketRegimeConfig(
        signals=[
            MarketSignalSpec(
                name="spy",
                axis="growth",
                symbol="SPY",
                transform="return",
                lookback_days=5,
                weight=1.0,
            ),
            MarketSignalSpec(
                name="dormant_oil",
                axis="growth",
                symbol="USO",
                transform="return",
                lookback_days=5,
                weight=0.0,
            ),
        ],
    )
    a = compute_market_axis_scores(_panel(100), base)["growth"].dropna().tolist()
    b = compute_market_axis_scores(_panel(100), extended)["growth"].dropna().tolist()
    assert a == b
