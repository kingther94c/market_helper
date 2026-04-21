from __future__ import annotations

import pytest

from market_helper.regimes.axes import (
    GrowthInflationAxes,
    QUADRANT_DEFLATIONARY_SLOWDOWN,
    QUADRANT_GOLDILOCKS,
    QUADRANT_REFLATION,
    QUADRANT_STAGFLATION,
    QuadrantSnapshot,
)
from market_helper.regimes.ensemble import EnsembleConfig, aggregate
from market_helper.regimes.methods.base import MethodResult


def _make_result(
    method: str, as_of: str, growth: float, inflation: float,
    *, crisis: bool = False, intensity: float = 0.0, confidence: float = 0.7,
    quadrant_label: str | None = None,
) -> MethodResult:
    axes = GrowthInflationAxes(
        as_of=as_of,
        growth_score=growth,
        inflation_score=inflation,
        confidence=confidence,
    )
    if quadrant_label is None:
        if growth >= 0 and inflation < 0:
            quadrant_label = QUADRANT_GOLDILOCKS
        elif growth >= 0 and inflation >= 0:
            quadrant_label = QUADRANT_REFLATION
        elif growth < 0 and inflation >= 0:
            quadrant_label = QUADRANT_STAGFLATION
        else:
            quadrant_label = QUADRANT_DEFLATIONARY_SLOWDOWN
    quadrant = QuadrantSnapshot(
        as_of=as_of,
        quadrant=quadrant_label,
        axes=axes,
        crisis_flag=crisis,
        crisis_intensity=intensity,
        duration_days=1,
    )
    return MethodResult(
        as_of=as_of,
        method_name=method,
        quadrant=quadrant,
        native_label=quadrant_label,
    )


def test_aggregate_unanimous_methods_agreement_100pct() -> None:
    dates = ["2024-01-02", "2024-01-03", "2024-01-04"]
    per_method = {
        "a": [_make_result("a", d, 1.0, -1.0) for d in dates],
        "b": [_make_result("b", d, 0.5, -0.5) for d in dates],
    }
    cfg = EnsembleConfig(min_consecutive_days=1)
    out = aggregate(per_method, config=cfg)
    assert len(out) == 3
    assert all(snap.quadrant == QUADRANT_GOLDILOCKS for snap in out)
    assert all(snap.diagnostics["method_agreement"] == 1.0 for snap in out)


def test_aggregate_disagreement_uses_confidence_weighting() -> None:
    date = "2024-03-01"
    # Method a is confident on growth=+ / inflation=+ (Reflation)
    # Method b is barely confident on growth=- / inflation=- (Slowdown)
    # Confidence-weighted vote -> Reflation wins.
    per_method = {
        "a": [_make_result("a", date, 2.0, 2.0, confidence=0.95)],
        "b": [_make_result("b", date, -0.1, -0.1, confidence=0.1)],
    }
    cfg = EnsembleConfig(min_consecutive_days=1, use_confidence_weighting=True)
    out = aggregate(per_method, config=cfg)
    assert out[0].quadrant == QUADRANT_REFLATION
    assert pytest.approx(out[0].diagnostics["method_agreement"], abs=1e-6) == 0.5


def test_aggregate_crisis_flag_ors_and_intensity_maxes() -> None:
    date = "2024-04-01"
    per_method = {
        "a": [_make_result("a", date, 0.5, 0.5, crisis=True, intensity=0.6)],
        "b": [_make_result("b", date, 0.5, 0.5, crisis=False, intensity=0.0)],
    }
    out = aggregate(per_method, config=EnsembleConfig(min_consecutive_days=1))
    assert out[0].crisis_flag is True
    assert out[0].crisis_intensity == pytest.approx(0.6)


def test_aggregate_only_emits_on_common_dates() -> None:
    per_method = {
        "a": [
            _make_result("a", "2024-01-02", 1.0, -1.0),
            _make_result("a", "2024-01-03", 1.0, -1.0),
        ],
        "b": [
            _make_result("b", "2024-01-03", 1.0, -1.0),
            _make_result("b", "2024-01-04", 1.0, -1.0),
        ],
    }
    out = aggregate(per_method, config=EnsembleConfig(min_consecutive_days=1))
    assert [snap.as_of for snap in out] == ["2024-01-03"]


def test_aggregate_tie_carries_previous_side() -> None:
    # Two methods with equal weight; one bullish, one bearish on growth ->
    # a vote tie every day. The ensemble should carry forward an initial
    # positive default and never flip.
    dates = [f"2024-05-{day:02d}" for day in range(1, 6)]
    per_method = {
        "a": [_make_result("a", d, 1.0, 1.0, confidence=0.5) for d in dates],
        "b": [_make_result("b", d, -1.0, -1.0, confidence=0.5) for d in dates],
    }
    cfg = EnsembleConfig(min_consecutive_days=1, use_confidence_weighting=False)
    out = aggregate(per_method, config=cfg)
    # Ties default to positive both axes -> Reflation
    assert all(snap.quadrant == QUADRANT_REFLATION for snap in out)
