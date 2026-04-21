from __future__ import annotations

import pytest

from market_helper.regimes.axes import (
    GrowthInflationAxes,
    QUADRANT_DEFLATIONARY_SLOWDOWN,
    QUADRANT_GOLDILOCKS,
    QUADRANT_REFLATION,
    QUADRANT_STAGFLATION,
    QuadrantSnapshot,
    apply_sign_hysteresis,
    compute_duration_days,
    quadrant_from_scores,
    quadrant_from_signs,
    quadrant_series,
)


def test_quadrant_from_signs_all_four_corners() -> None:
    assert quadrant_from_signs(True, False) == QUADRANT_GOLDILOCKS
    assert quadrant_from_signs(True, True) == QUADRANT_REFLATION
    assert quadrant_from_signs(False, True) == QUADRANT_STAGFLATION
    assert quadrant_from_signs(False, False) == QUADRANT_DEFLATIONARY_SLOWDOWN


def test_quadrant_from_scores_treats_zero_as_positive() -> None:
    assert quadrant_from_scores(0.0, 0.0) == QUADRANT_REFLATION
    assert quadrant_from_scores(-0.01, -0.01) == QUADRANT_DEFLATIONARY_SLOWDOWN
    assert quadrant_from_scores(1.0, -0.5) == QUADRANT_GOLDILOCKS


def test_hysteresis_requires_consecutive_flips() -> None:
    # Start positive, then 2 days negative, 1 day positive (should NOT flip yet),
    # then 3 more days negative → accumulated 5 consecutive → flips on the 5th.
    scores = [1.0, -1.0, -1.0, 0.5, -1.0, -1.0, -1.0]
    sides = apply_sign_hysteresis(scores, min_consecutive_days=5)
    # Day 0 positive; days 1-5 still positive because the negative streak resets
    # when day 3 comes back positive; only resumes thereafter but never hits 5.
    assert sides == [True, True, True, True, True, True, True]


def test_hysteresis_flips_after_enough_days() -> None:
    scores = [1.0, -1.0, -1.0, -1.0]
    sides = apply_sign_hysteresis(scores, min_consecutive_days=3)
    # Third consecutive negative triggers the flip.
    assert sides == [True, True, True, False]


def test_hysteresis_rejects_bad_window() -> None:
    with pytest.raises(ValueError):
        apply_sign_hysteresis([1.0], 0)


def test_quadrant_series_matches_length() -> None:
    g = [1.0, 1.0, -1.0, -1.0]
    i = [-1.0, 1.0, 1.0, -1.0]
    # Hysteresis=1 means immediate flip
    labels = quadrant_series(g, i, min_consecutive_days=1)
    assert labels == [
        QUADRANT_GOLDILOCKS,
        QUADRANT_REFLATION,
        QUADRANT_STAGFLATION,
        QUADRANT_DEFLATIONARY_SLOWDOWN,
    ]


def test_quadrant_series_enforces_equal_length() -> None:
    with pytest.raises(ValueError):
        quadrant_series([1.0, 2.0], [1.0], min_consecutive_days=1)


def test_compute_duration_days_resets_on_change() -> None:
    labels = ["A", "A", "A", "B", "B", "A"]
    assert compute_duration_days(labels) == [1, 2, 3, 1, 2, 1]


def test_quadrant_snapshot_roundtrip() -> None:
    axes = GrowthInflationAxes(
        as_of="2024-01-02",
        growth_score=0.4,
        inflation_score=-0.2,
        growth_drivers={"PAYEMS": 0.3},
        inflation_drivers={"CPIAUCSL": -0.1},
        confidence=0.42,
    )
    snap = QuadrantSnapshot(
        as_of="2024-01-02",
        quadrant=QUADRANT_GOLDILOCKS,
        axes=axes,
        crisis_flag=False,
        crisis_intensity=0.0,
        duration_days=5,
        diagnostics={"hysteresis_growth_positive": True},
    )
    round_tripped = QuadrantSnapshot.from_dict(snap.to_dict())
    assert round_tripped == snap
