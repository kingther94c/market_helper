"""Growth vs. inflation 2D regime axes.

A method classifies each date into a quadrant defined by the sign of two
composite scores (``growth_score``, ``inflation_score``). An optional
hysteresis layer smooths quadrant flips on either axis: require N consecutive
business days with the sign consistent on an axis before flipping that axis.

A ``QuadrantSnapshot`` also carries a crisis flag (intensity 0..1) that is
orthogonal to the quadrant so methods can surface acute risk-off episodes
without collapsing the underlying growth/inflation view.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Iterable, List, Sequence

QUADRANT_GOLDILOCKS = "Goldilocks"
QUADRANT_REFLATION = "Reflation"
QUADRANT_STAGFLATION = "Stagflation"
QUADRANT_DEFLATIONARY_SLOWDOWN = "Deflationary Slowdown"

QUADRANT_LABELS = (
    QUADRANT_GOLDILOCKS,
    QUADRANT_REFLATION,
    QUADRANT_STAGFLATION,
    QUADRANT_DEFLATIONARY_SLOWDOWN,
)


def quadrant_from_signs(growth_positive: bool, inflation_positive: bool) -> str:
    if growth_positive and not inflation_positive:
        return QUADRANT_GOLDILOCKS
    if growth_positive and inflation_positive:
        return QUADRANT_REFLATION
    if (not growth_positive) and inflation_positive:
        return QUADRANT_STAGFLATION
    return QUADRANT_DEFLATIONARY_SLOWDOWN


def quadrant_from_scores(growth_score: float, inflation_score: float) -> str:
    """Map a signed (growth, inflation) pair to a quadrant.

    Zero is treated as the positive-side for determinism. Callers that want
    hysteresis should use :func:`apply_sign_hysteresis` on the raw score
    series first and then build quadrants from the stabilized signs.
    """
    return quadrant_from_signs(growth_score >= 0.0, inflation_score >= 0.0)


@dataclass(frozen=True)
class GrowthInflationAxes:
    """Composite signed scores for the growth and inflation axes at one date.

    Scores are z-score-like (unbounded) with 0 at trend. ``*_drivers`` holds
    the signed post-clip contribution of each underlying series so the report
    can show "why" a method voted a direction.
    """

    as_of: str
    growth_score: float
    inflation_score: float
    growth_drivers: dict[str, float] = field(default_factory=dict)
    inflation_drivers: dict[str, float] = field(default_factory=dict)
    confidence: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class QuadrantSnapshot:
    """A method's 2D verdict for one date."""

    as_of: str
    quadrant: str
    axes: GrowthInflationAxes
    crisis_flag: bool = False
    crisis_intensity: float = 0.0
    duration_days: int = 1
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["axes"] = self.axes.to_dict()
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "QuadrantSnapshot":
        axes_payload = dict(payload.get("axes", {}))
        axes = GrowthInflationAxes(
            as_of=str(axes_payload.get("as_of", payload.get("as_of", ""))),
            growth_score=float(axes_payload.get("growth_score", 0.0)),
            inflation_score=float(axes_payload.get("inflation_score", 0.0)),
            growth_drivers={
                str(k): float(v)
                for k, v in dict(axes_payload.get("growth_drivers", {})).items()
            },
            inflation_drivers={
                str(k): float(v)
                for k, v in dict(axes_payload.get("inflation_drivers", {})).items()
            },
            confidence=float(axes_payload.get("confidence", 0.0)),
        )
        return cls(
            as_of=str(payload["as_of"]),
            quadrant=str(payload["quadrant"]),
            axes=axes,
            crisis_flag=bool(payload.get("crisis_flag", False)),
            crisis_intensity=float(payload.get("crisis_intensity", 0.0)),
            duration_days=int(payload.get("duration_days", 1)),
            diagnostics=dict(payload.get("diagnostics", {})),
        )


def apply_sign_hysteresis(
    scores: Sequence[float], min_consecutive_days: int = 10
) -> List[bool]:
    """Stabilize the sign of a score series.

    Returns a list of booleans (``True`` = positive side) where the sign only
    flips after ``min_consecutive_days`` consecutive observations on the new
    side. The first observation seeds the state.

    This is a deliberately simple analog of
    ``RulebookConfig.min_non_crisis_days`` from the legacy rulebook, adapted
    to work per axis instead of per regime label.
    """
    if min_consecutive_days < 1:
        raise ValueError("min_consecutive_days must be >= 1")
    out: List[bool] = []
    current: bool | None = None
    pending_side: bool | None = None
    pending_count = 0
    for value in scores:
        side = value >= 0.0
        if current is None:
            current = side
            pending_side = None
            pending_count = 0
        elif side == current:
            pending_side = None
            pending_count = 0
        else:
            if pending_side == side:
                pending_count += 1
            else:
                pending_side = side
                pending_count = 1
            if pending_count >= min_consecutive_days:
                current = side
                pending_side = None
                pending_count = 0
        out.append(bool(current))
    return out


def quadrant_series(
    growth_scores: Sequence[float],
    inflation_scores: Sequence[float],
    *,
    min_consecutive_days: int = 10,
) -> List[str]:
    """Apply per-axis hysteresis and produce a quadrant label per date."""
    if len(growth_scores) != len(inflation_scores):
        raise ValueError("growth and inflation score series must have equal length")
    growth_sides = apply_sign_hysteresis(growth_scores, min_consecutive_days)
    inflation_sides = apply_sign_hysteresis(
        inflation_scores, min_consecutive_days
    )
    return [
        quadrant_from_signs(g, i) for g, i in zip(growth_sides, inflation_sides)
    ]


def compute_duration_days(quadrants: Iterable[str]) -> List[int]:
    """For each position, return the run length ending at that position."""
    out: List[int] = []
    current: str | None = None
    run = 0
    for label in quadrants:
        if label == current:
            run += 1
        else:
            current = label
            run = 1
        out.append(run)
    return out


__all__ = [
    "QUADRANT_GOLDILOCKS",
    "QUADRANT_REFLATION",
    "QUADRANT_STAGFLATION",
    "QUADRANT_DEFLATIONARY_SLOWDOWN",
    "QUADRANT_LABELS",
    "GrowthInflationAxes",
    "QuadrantSnapshot",
    "quadrant_from_signs",
    "quadrant_from_scores",
    "apply_sign_hysteresis",
    "quadrant_series",
    "compute_duration_days",
]
