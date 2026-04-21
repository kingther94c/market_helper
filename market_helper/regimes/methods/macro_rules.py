"""Macro rule-based 2D regime method.

Reads the FRED macro panel (columns = FRED series IDs, index = business-day
dates) produced by ``market_helper.data_sources.fred.macro_panel``, normalizes
each series with a trailing rolling z-score, caps extreme moves, and takes a
weighted axis-wise mean to produce signed growth/inflation scores. Sign
hysteresis (per axis) stabilizes the quadrant label against release-day noise.

This method does NOT produce a crisis flag — crises are detected via the
legacy market-stress method and OR'd in by the ensemble layer.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List, Mapping, Sequence

import math

import numpy as np
import pandas as pd

from market_helper.data_sources.fred.macro_panel import SeriesSpec, specs_by_axis
from market_helper.regimes.axes import (
    GrowthInflationAxes,
    QuadrantSnapshot,
    apply_sign_hysteresis,
    compute_duration_days,
    quadrant_from_signs,
)
from market_helper.regimes.methods.base import MethodResult


@dataclass(frozen=True)
class MacroRulesConfig:
    """Tuning for the macro rules method.

    - ``zscore_window_bdays``: trailing business-day window for the per-series
      rolling z-score. Default 2520 ≈ 10 years.
    - ``min_periods``: minimum observations before a z-score is emitted;
      otherwise the series contributes NaN (dropped from that day's mean).
    - ``zscore_clip``: absolute cap applied to each series' z-score before
      weighting, so a single outlier print can't dominate.
    - ``min_consecutive_days``: sign-hysteresis window (per axis).
    - ``warmup_bdays``: emit no results for the first N bdays of the panel
      (normalization still unstable). 0 disables.
    """

    zscore_window_bdays: int = 2520
    min_periods: int = 252
    zscore_clip: float = 3.0
    min_consecutive_days: int = 10
    warmup_bdays: int = 0


def _rolling_zscore(series: pd.Series, window: int, min_periods: int) -> pd.Series:
    """Trailing rolling z-score. NaN until ``min_periods`` observations exist
    and when the rolling std is zero (no variation).
    """
    s = series.astype(float)
    roll = s.rolling(window=window, min_periods=min_periods)
    mu = roll.mean()
    sigma = roll.std(ddof=0)
    with np.errstate(invalid="ignore", divide="ignore"):
        z = (s - mu) / sigma
    z = z.where(sigma > 0)
    return z


def _clip(series: pd.Series, limit: float) -> pd.Series:
    if limit <= 0 or not math.isfinite(limit):
        return series
    return series.clip(lower=-limit, upper=limit)


def compute_axis_scores(
    panel: pd.DataFrame,
    specs: Sequence[SeriesSpec],
    *,
    config: MacroRulesConfig = MacroRulesConfig(),
) -> pd.DataFrame:
    """Return a DataFrame with columns ``growth``, ``inflation``,
    ``growth_confidence``, ``inflation_confidence``, plus per-series
    contribution columns ``contrib:{series_id}``.

    ``panel`` must have a ``date`` column or a DatetimeIndex plus one column
    per series id matching ``specs``.
    """
    if panel.empty:
        return pd.DataFrame(
            columns=[
                "date",
                "growth",
                "inflation",
                "growth_confidence",
                "inflation_confidence",
            ]
        )

    frame = panel.copy()
    if "date" in frame.columns:
        frame = frame.set_index(pd.to_datetime(frame["date"])).drop(columns=["date"])
    frame.index.name = "date"

    by_axis = specs_by_axis(specs)
    contribs: dict[str, pd.Series] = {}
    for spec in specs:
        if spec.series_id not in frame.columns:
            continue
        z = _rolling_zscore(
            frame[spec.series_id],
            window=config.zscore_window_bdays,
            min_periods=config.min_periods,
        )
        z = _clip(z, config.zscore_clip)
        contribs[spec.series_id] = z * float(spec.weight)

    def _axis_mean(axis: str) -> tuple[pd.Series, pd.Series]:
        axis_specs = [
            s for s in by_axis.get(axis, []) if s.series_id in contribs
        ]
        if not axis_specs:
            empty = pd.Series(np.nan, index=frame.index)
            return empty, empty
        cols = pd.DataFrame({s.series_id: contribs[s.series_id] for s in axis_specs})
        weights = pd.Series(
            {s.series_id: float(s.weight) for s in axis_specs}
        ).reindex(cols.columns)
        # Per-row effective total weight = sum of weights where value is present.
        mask = cols.notna().astype(float)
        effective = mask.mul(weights, axis=1).sum(axis=1)
        weighted_sum = cols.fillna(0.0).sum(axis=1)
        score = weighted_sum / effective.replace(0.0, np.nan)
        # Confidence proxy: fraction of available weight * |score|, squashed.
        availability = effective / float(weights.sum()) if weights.sum() else 0.0
        confidence = (score.abs().clip(upper=config.zscore_clip) / config.zscore_clip) * availability
        return score, confidence

    growth_score, growth_conf = _axis_mean("growth")
    inflation_score, inflation_conf = _axis_mean("inflation")

    out = pd.DataFrame(
        {
            "growth": growth_score,
            "inflation": inflation_score,
            "growth_confidence": growth_conf,
            "inflation_confidence": inflation_conf,
        },
        index=frame.index,
    )
    for sid, series in contribs.items():
        out[f"contrib:{sid}"] = series
    out = out.reset_index().rename(columns={"index": "date"})
    return out


class MacroRulesMethod:
    """v1 macro rule-based method — FRED panel → (growth, inflation) quadrant."""

    name = "macro_rules"

    def __init__(
        self,
        specs: Sequence[SeriesSpec],
        *,
        config: MacroRulesConfig | None = None,
    ) -> None:
        self.specs = list(specs)
        self.config = config or MacroRulesConfig()

    def classify(self, panel: pd.DataFrame) -> List[MethodResult]:
        scores = compute_axis_scores(panel, self.specs, config=self.config)
        if scores.empty:
            return []

        scores = scores.sort_values("date").reset_index(drop=True)
        # Drop the warm-up prefix entirely (no emission until the rolling
        # window has filled enough to be trusted).
        if self.config.warmup_bdays > 0:
            scores = scores.iloc[self.config.warmup_bdays :].reset_index(drop=True)

        # Drop rows where both axes are NaN (no contributions yet).
        usable = scores.dropna(subset=["growth", "inflation"], how="all").reset_index(drop=True)
        if usable.empty:
            return []

        growth_values = usable["growth"].fillna(0.0).tolist()
        inflation_values = usable["inflation"].fillna(0.0).tolist()

        growth_sides = apply_sign_hysteresis(
            growth_values, self.config.min_consecutive_days
        )
        inflation_sides = apply_sign_hysteresis(
            inflation_values, self.config.min_consecutive_days
        )
        quadrants = [
            quadrant_from_signs(g, i) for g, i in zip(growth_sides, inflation_sides)
        ]
        durations = compute_duration_days(quadrants)

        by_axis = specs_by_axis(self.specs)
        growth_ids = [s.series_id for s in by_axis.get("growth", [])]
        inflation_ids = [s.series_id for s in by_axis.get("inflation", [])]

        records = usable.to_dict(orient="records")
        results: List[MethodResult] = []
        for row_dict, qlabel, duration, g_pos, i_pos in zip(
            records,
            quadrants,
            durations,
            growth_sides,
            inflation_sides,
        ):
            as_of = pd.Timestamp(row_dict["date"]).strftime("%Y-%m-%d")
            growth_drivers = {
                sid: float(row_dict.get(f"contrib:{sid}", float("nan")))
                for sid in growth_ids
                if f"contrib:{sid}" in row_dict
                and not _is_nan(row_dict.get(f"contrib:{sid}"))
            }
            inflation_drivers = {
                sid: float(row_dict.get(f"contrib:{sid}", float("nan")))
                for sid in inflation_ids
                if f"contrib:{sid}" in row_dict
                and not _is_nan(row_dict.get(f"contrib:{sid}"))
            }
            confidence = _combine_confidence(
                row_dict.get("growth_confidence"),
                row_dict.get("inflation_confidence"),
            )
            axes = GrowthInflationAxes(
                as_of=as_of,
                growth_score=_safe_float(row_dict.get("growth")),
                inflation_score=_safe_float(row_dict.get("inflation")),
                growth_drivers=growth_drivers,
                inflation_drivers=inflation_drivers,
                confidence=confidence,
            )
            quadrant_snapshot = QuadrantSnapshot(
                as_of=as_of,
                quadrant=qlabel,
                axes=axes,
                crisis_flag=False,
                crisis_intensity=0.0,
                duration_days=int(duration),
                diagnostics={
                    "raw_growth_sign_positive": bool(
                        _safe_float(row_dict.get("growth")) >= 0.0
                    ),
                    "raw_inflation_sign_positive": bool(
                        _safe_float(row_dict.get("inflation")) >= 0.0
                    ),
                    "hysteresis_growth_positive": bool(g_pos),
                    "hysteresis_inflation_positive": bool(i_pos),
                },
            )
            results.append(
                MethodResult(
                    as_of=as_of,
                    method_name=self.name,
                    quadrant=quadrant_snapshot,
                    native_label=qlabel,
                    native_detail={
                        "growth_confidence": _safe_float(
                            row_dict.get("growth_confidence")
                        ),
                        "inflation_confidence": _safe_float(
                            row_dict.get("inflation_confidence")
                        ),
                    },
                )
            )
        return results


def _safe_float(value: object) -> float:
    if value is None:
        return 0.0
    try:
        f = float(value)
    except (TypeError, ValueError):
        return 0.0
    if math.isnan(f):
        return 0.0
    return f


def _is_nan(value: object) -> bool:
    try:
        return math.isnan(float(value))
    except (TypeError, ValueError):
        return True


def _combine_confidence(g: object, i: object) -> float:
    gf = _safe_float(g)
    inf = _safe_float(i)
    return max(0.0, min(1.0, 0.5 * (gf + inf)))


__all__ = [
    "MacroRulesConfig",
    "MacroRulesMethod",
    "compute_axis_scores",
]
