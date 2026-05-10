from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

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


def test_market_concept_aggregation_two_concepts() -> None:
    """Concept-axis blend: A weight 1 (two members 50/50), B weight 0.5
    (one member). axis = (A_score*1 + B_score*0.5) / 1.5."""
    from market_helper.regimes.methods.market_regime import MarketConceptSpec

    n = 200
    dates = pd.bdate_range("2024-01-01", periods=n)
    panel = pd.DataFrame({
        "date": dates,
        "X": [100.0 * (1.0 + 0.001 * idx) for idx in range(n)],
        "Y": [100.0 * (1.0 - 0.001 * idx) for idx in range(n)],
        "Z": [100.0 * (1.0 + 0.002 * idx) for idx in range(n)],
        "VIX": [15.0] * n,
    })
    cfg = MarketRegimeConfig(
        signals=[
            MarketSignalSpec(name="x", axis="growth", symbol="X", transform="return", lookback_days=5, normalization="raw"),
            MarketSignalSpec(name="y", axis="growth", symbol="Y", transform="return", lookback_days=5, normalization="raw"),
            MarketSignalSpec(name="z", axis="growth", symbol="Z", transform="return", lookback_days=5, normalization="raw"),
        ],
        concepts=[
            MarketConceptSpec(name="A", axis="growth", weight=1.0, members={"x": 0.5, "y": 0.5}),
            MarketConceptSpec(name="B", axis="growth", weight=0.5, members={"z": 1.0}),
        ],
    )
    scores = compute_market_axis_scores(panel, cfg)
    assert "concept:growth:A" in scores.columns
    assert "concept:growth:B" in scores.columns
    g = scores["growth"].dropna()
    a = scores["concept:growth:A"].dropna()
    b = scores["concept:growth:B"].dropna()
    expected = (a.iloc[-1] * 1.0 + b.iloc[-1] * 0.5) / 1.5
    assert g.iloc[-1] == pytest.approx(expected)


def test_market_beta_adjusted_relative_return_strips_systematic_beta() -> None:
    """When numerator = beta * denominator (perfectly), the beta-adjusted
    residual is ~zero on average over the lookback. Use a strongly-trending
    denominator so the raw relative_return diverges meaningfully from zero
    while the residual stays near zero."""
    n = 240
    dates = pd.bdate_range("2024-01-01", periods=n)
    # Linear-growth denominator: ~+0.1% per day
    den = np.array([100.0 * (1.0 + 0.001 * i) for i in range(n)])
    den_ret = np.diff(den, prepend=den[0]) / den
    den_ret[0] = 0.0
    # Numerator = denominator with beta 1.5 (so it grows ~+0.15% per day)
    num = np.zeros(n); num[0] = 100.0
    for i in range(1, n):
        num[i] = num[i-1] * (1.0 + 1.5 * den_ret[i])
    panel = pd.DataFrame({"date": dates, "NUM": num, "DEN": den})

    cfg = MarketRegimeConfig(
        signals=[
            MarketSignalSpec(
                name="raw", axis="growth",
                numerator="NUM", denominator="DEN",
                transform="relative_return", lookback_days=21, normalization="raw",
            ),
            MarketSignalSpec(
                name="beta_adj", axis="growth",
                numerator="NUM", denominator="DEN",
                transform="beta_adjusted_relative_return", lookback_days=21, normalization="raw",
                beta_window_days=60, beta_clip=3.0,
            ),
        ],
    )
    scores = compute_market_axis_scores(panel, cfg)
    raw = scores["contrib:raw"].dropna()
    adj = scores["contrib:beta_adj"].dropna()
    # Raw relative is meaningfully positive (NUM outperforms DEN by 1.5x).
    assert raw.iloc[-1] > 0.005
    # Beta-adjusted residual is dramatically smaller (β fits the 1.5 ratio).
    assert abs(adj.iloc[-1]) < 0.2 * abs(raw.iloc[-1])
