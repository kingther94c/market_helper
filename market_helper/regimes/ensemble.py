"""Consensus aggregation across regime methods.

Each method emits a list of :class:`MethodResult` carrying a
:class:`QuadrantSnapshot`. The ensemble layer aligns them by date, votes on
each axis (growth, inflation) with per-method confidence as the weight, and
returns one ensemble :class:`QuadrantSnapshot` per overlapping date.

Crisis flags are OR'd across methods and intensity is the max. A
"method_agreement" diagnostic reports the fraction of methods whose quadrant
matches the ensemble quadrant, so the report surfaces moments when the
methods disagree.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Mapping, Sequence, Tuple

from market_helper.regimes.axes import (
    GrowthInflationAxes,
    QuadrantSnapshot,
    apply_sign_hysteresis,
    compute_duration_days,
    quadrant_from_signs,
)
from market_helper.regimes.methods.base import MethodResult


@dataclass(frozen=True)
class EnsembleConfig:
    method_weights: Mapping[str, float] | None = None
    min_consecutive_days: int = 5
    use_confidence_weighting: bool = True


def _method_weight(name: str, cfg: EnsembleConfig) -> float:
    if cfg.method_weights is None:
        return 1.0
    return float(cfg.method_weights.get(name, 1.0))


def _align_by_date(
    per_method: Mapping[str, Sequence[MethodResult]],
) -> List[Tuple[str, Dict[str, MethodResult]]]:
    """Return (date, {method_name: MethodResult}) pairs over the dates where
    *all* methods emit a result."""
    if not per_method:
        return []
    indexed: Dict[str, Dict[str, MethodResult]] = {}
    name_set = set(per_method.keys())
    for name, results in per_method.items():
        for result in results:
            indexed.setdefault(result.as_of, {})[name] = result
    common = sorted(d for d, by_name in indexed.items() if name_set.issubset(by_name))
    return [(d, indexed[d]) for d in common]


def aggregate(
    per_method: Mapping[str, Sequence[MethodResult]],
    *,
    config: EnsembleConfig | None = None,
) -> List[QuadrantSnapshot]:
    """Produce the ensemble quadrant series.

    Voting:
      - ``vote_axis`` per date and axis = Σ (sign * method_weight * w_conf),
        where ``w_conf`` = method confidence if
        ``config.use_confidence_weighting`` else 1.
      - Positive side if vote > 0, negative if < 0. Ties carry forward the
        previous-day side (defaults to positive on the first date).
      - A per-axis :func:`apply_sign_hysteresis` pass smooths single-day flips.
    """
    cfg = config or EnsembleConfig()
    aligned = _align_by_date(per_method)
    if not aligned:
        return []

    raw_growth_votes: List[float] = []
    raw_inflation_votes: List[float] = []
    crisis_flags: List[bool] = []
    crisis_intensities: List[float] = []
    per_date_info: List[Dict[str, MethodResult]] = []
    for _, by_name in aligned:
        g_vote = 0.0
        i_vote = 0.0
        crisis = False
        intensity = 0.0
        for name, result in by_name.items():
            mw = _method_weight(name, cfg)
            conf_g = (
                max(0.05, result.quadrant.axes.confidence)
                if cfg.use_confidence_weighting
                else 1.0
            )
            conf_i = conf_g
            g_sign = 1.0 if result.quadrant.axes.growth_score >= 0.0 else -1.0
            i_sign = 1.0 if result.quadrant.axes.inflation_score >= 0.0 else -1.0
            g_vote += mw * conf_g * g_sign
            i_vote += mw * conf_i * i_sign
            if result.quadrant.crisis_flag:
                crisis = True
                intensity = max(intensity, float(result.quadrant.crisis_intensity))
        raw_growth_votes.append(g_vote)
        raw_inflation_votes.append(i_vote)
        crisis_flags.append(crisis)
        crisis_intensities.append(intensity)
        per_date_info.append(by_name)

    # Resolve ties by carrying forward.
    growth_raw_sides = _resolve_ties(raw_growth_votes)
    inflation_raw_sides = _resolve_ties(raw_inflation_votes)
    # Hysteresis-smoothed final sides — operate on the raw score via sign.
    growth_scores_for_hyst = [
        (1.0 if s else -1.0) for s in growth_raw_sides
    ]
    inflation_scores_for_hyst = [
        (1.0 if s else -1.0) for s in inflation_raw_sides
    ]
    growth_sides = apply_sign_hysteresis(
        growth_scores_for_hyst, cfg.min_consecutive_days
    )
    inflation_sides = apply_sign_hysteresis(
        inflation_scores_for_hyst, cfg.min_consecutive_days
    )
    quadrants = [
        quadrant_from_signs(g, i) for g, i in zip(growth_sides, inflation_sides)
    ]
    durations = compute_duration_days(quadrants)

    out: List[QuadrantSnapshot] = []
    for (date, _), qlabel, duration, g_pos, i_pos, crisis, intensity, by_name in zip(
        aligned,
        quadrants,
        durations,
        growth_sides,
        inflation_sides,
        crisis_flags,
        crisis_intensities,
        per_date_info,
    ):
        # Agreement fraction on the final quadrant.
        matching = sum(1 for r in by_name.values() if r.quadrant.quadrant == qlabel)
        agreement = matching / max(1, len(by_name))
        # Ensemble axis scores as the mean of member axis scores (post-sign-vote
        # magnitudes are not meaningful; use the average of member scores so
        # the caller still sees how "strong" the consensus was on each axis).
        growth_score = _mean_score(by_name, "growth")
        inflation_score = _mean_score(by_name, "inflation")
        axes = GrowthInflationAxes(
            as_of=date,
            growth_score=growth_score,
            inflation_score=inflation_score,
            growth_drivers={name: r.quadrant.axes.growth_score for name, r in by_name.items()},
            inflation_drivers={
                name: r.quadrant.axes.inflation_score for name, r in by_name.items()
            },
            confidence=agreement,
        )
        out.append(
            QuadrantSnapshot(
                as_of=date,
                quadrant=qlabel,
                axes=axes,
                crisis_flag=bool(crisis),
                crisis_intensity=float(intensity),
                duration_days=int(duration),
                diagnostics={
                    "method_agreement": agreement,
                    "per_method_quadrant": {
                        name: r.quadrant.quadrant for name, r in by_name.items()
                    },
                    "hysteresis_growth_positive": bool(g_pos),
                    "hysteresis_inflation_positive": bool(i_pos),
                },
            )
        )
    return out


def _resolve_ties(votes: Sequence[float]) -> List[bool]:
    """Turn signed vote tallies into booleans (True = positive side); carry
    the previous side on exact ties. Defaults to positive on the first tie."""
    sides: List[bool] = []
    current: bool | None = None
    for vote in votes:
        if vote > 0.0:
            current = True
        elif vote < 0.0:
            current = False
        else:  # exact tie
            if current is None:
                current = True
        sides.append(bool(current))
    return sides


def _mean_score(by_name: Mapping[str, MethodResult], axis: str) -> float:
    values = [
        getattr(result.quadrant.axes, f"{axis}_score")
        for result in by_name.values()
    ]
    if not values:
        return 0.0
    return float(sum(values) / len(values))


__all__ = ["EnsembleConfig", "aggregate"]
