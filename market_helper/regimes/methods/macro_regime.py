"""Config-driven macro regime method.

The macro method consumes the FRED macro panel and classifies each date from
signed growth/inflation evidence. Series are grouped into fast/slow buckets per
axis; defaults weight fast data at 70% and slow data at 30%.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Mapping, Sequence

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
class MacroRegimeConfig:
    bucket_weights: Mapping[str, float] = field(
        default_factory=lambda: {"fast": 0.70, "slow": 0.30}
    )
    min_available_bucket_weight: float = 0.0
    default_normalization: str = "none"
    zscore_window_bdays: int = 2520
    min_periods: int = 252
    zscore_clip: float = 3.0
    min_consecutive_days: int = 10
    warmup_bdays: int = 0


def _rolling_zscore(series: pd.Series, window: int, min_periods: int) -> pd.Series:
    s = series.astype(float)
    roll = s.rolling(window=window, min_periods=min_periods)
    mu = roll.mean()
    sigma = roll.std(ddof=0)
    with np.errstate(invalid="ignore", divide="ignore"):
        z = (s - mu) / sigma
    return z.where(sigma > 0)


def _clip(series: pd.Series, limit: float) -> pd.Series:
    if limit <= 0 or not math.isfinite(limit):
        return series
    return series.clip(lower=-limit, upper=limit)


def _signed_signal(series: pd.Series, spec: SeriesSpec) -> pd.Series:
    signal = series.astype(float)
    if spec.neutral_level is not None:
        signal = signal - float(spec.neutral_level)
    if spec.direction == "negative":
        signal = -signal
    if spec.threshold is not None and spec.threshold > 0:
        threshold = float(spec.threshold)
        signal = signal.where(signal.abs() >= threshold, 0.0)
    return signal


def _normalize_signal(
    signal: pd.Series,
    spec: SeriesSpec,
    *,
    config: MacroRegimeConfig,
) -> pd.Series:
    mode = spec.normalization or config.default_normalization
    if mode == "none":
        return signal
    if mode == "centered":
        return signal - signal.expanding(min_periods=1).mean()
    if mode == "threshold":
        if spec.threshold is None or spec.threshold <= 0:
            return signal
        return signal / float(spec.threshold)
    if mode == "zscore":
        return _clip(
            _rolling_zscore(
                signal,
                window=config.zscore_window_bdays,
                min_periods=config.min_periods,
            ),
            config.zscore_clip,
        )
    raise ValueError(f"unsupported macro normalization: {mode!r}")


def compute_macro_axis_scores(
    panel: pd.DataFrame,
    specs: Sequence[SeriesSpec],
    *,
    config: MacroRegimeConfig = MacroRegimeConfig(),
) -> pd.DataFrame:
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
        signal = _signed_signal(frame[spec.series_id], spec)
        normalized = _normalize_signal(signal, spec, config=config)
        contribs[spec.series_id] = normalized * float(spec.weight)

    bucket_scores: dict[tuple[str, str], pd.Series] = {}
    bucket_available: dict[tuple[str, str], pd.Series] = {}

    def _bucket_mean(axis: str, bucket: str) -> tuple[pd.Series, pd.Series]:
        axis_specs = [
            s
            for s in by_axis.get(axis, [])
            if s.bucket == bucket and s.series_id in contribs
        ]
        if not axis_specs:
            empty = pd.Series(np.nan, index=frame.index)
            return empty, pd.Series(0.0, index=frame.index)
        cols = pd.DataFrame({s.series_id: contribs[s.series_id] for s in axis_specs})
        weights = pd.Series(
            {s.series_id: float(s.weight) for s in axis_specs}
        ).reindex(cols.columns)
        mask = cols.notna().astype(float)
        effective = mask.mul(weights, axis=1).sum(axis=1)
        score = cols.fillna(0.0).sum(axis=1) / effective.replace(0.0, np.nan)
        availability = effective / float(weights.sum()) if weights.sum() else 0.0
        return score, availability

    for axis in ("growth", "inflation"):
        for bucket in ("fast", "slow"):
            score, availability = _bucket_mean(axis, bucket)
            bucket_scores[(axis, bucket)] = score
            bucket_available[(axis, bucket)] = availability

    def _axis_score(axis: str) -> tuple[pd.Series, pd.Series]:
        parts = []
        avail_parts = []
        total_available_weight = pd.Series(0.0, index=frame.index)
        for bucket, bucket_weight in config.bucket_weights.items():
            score = bucket_scores.get((axis, bucket), pd.Series(np.nan, index=frame.index))
            availability = bucket_available.get((axis, bucket), pd.Series(0.0, index=frame.index))
            usable = availability > 0
            weighted = score.where(usable) * float(bucket_weight)
            parts.append(weighted)
            available_weight = usable.astype(float) * float(bucket_weight)
            avail_parts.append(available_weight)
            total_available_weight = total_available_weight + available_weight
        weighted_sum = pd.concat(parts, axis=1).sum(axis=1, min_count=1)
        available_weight_sum = pd.concat(avail_parts, axis=1).sum(axis=1)
        score = weighted_sum / available_weight_sum.replace(0.0, np.nan)
        score = score.where(
            available_weight_sum >= float(config.min_available_bucket_weight)
        )
        confidence = (available_weight_sum / max(1e-9, sum(config.bucket_weights.values()))).clip(
            lower=0.0, upper=1.0
        )
        return score, confidence

    growth_score, growth_conf = _axis_score("growth")
    inflation_score, inflation_conf = _axis_score("inflation")
    out = pd.DataFrame(
        {
            "growth": growth_score,
            "inflation": inflation_score,
            "growth_confidence": growth_conf,
            "inflation_confidence": inflation_conf,
        },
        index=frame.index,
    )
    for axis in ("growth", "inflation"):
        for bucket in ("fast", "slow"):
            out[f"bucket:{axis}:{bucket}"] = bucket_scores[(axis, bucket)]
    for sid, series in contribs.items():
        out[f"contrib:{sid}"] = series
    return out.reset_index().rename(columns={"index": "date"})


class MacroRegimeMethod:
    name = "macro_regime"

    def __init__(
        self,
        specs: Sequence[SeriesSpec],
        *,
        config: MacroRegimeConfig | None = None,
    ) -> None:
        self.specs = list(specs)
        self.config = config or MacroRegimeConfig()

    def classify(self, panel: pd.DataFrame) -> List[MethodResult]:
        scores = compute_macro_axis_scores(panel, self.specs, config=self.config)
        if scores.empty:
            return []
        scores = scores.sort_values("date").reset_index(drop=True)
        if self.config.warmup_bdays > 0:
            scores = scores.iloc[self.config.warmup_bdays :].reset_index(drop=True)
        usable = scores.dropna(subset=["growth", "inflation"], how="all").reset_index(drop=True)
        if usable.empty:
            return []

        growth_values = usable["growth"].fillna(0.0).tolist()
        inflation_values = usable["inflation"].fillna(0.0).tolist()
        growth_sides = apply_sign_hysteresis(growth_values, self.config.min_consecutive_days)
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
            records, quadrants, durations, growth_sides, inflation_sides
        ):
            as_of = pd.Timestamp(row_dict["date"]).strftime("%Y-%m-%d")
            growth_drivers = _driver_map(row_dict, growth_ids)
            inflation_drivers = _driver_map(row_dict, inflation_ids)
            confidence = _combine_confidence(
                row_dict.get("growth_confidence"), row_dict.get("inflation_confidence")
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
                    "raw_growth_sign_positive": bool(_safe_float(row_dict.get("growth")) >= 0.0),
                    "raw_inflation_sign_positive": bool(_safe_float(row_dict.get("inflation")) >= 0.0),
                    "hysteresis_growth_positive": bool(g_pos),
                    "hysteresis_inflation_positive": bool(i_pos),
                    "bucket_scores": {
                        "growth": {
                            "fast": _safe_float(row_dict.get("bucket:growth:fast")),
                            "slow": _safe_float(row_dict.get("bucket:growth:slow")),
                        },
                        "inflation": {
                            "fast": _safe_float(row_dict.get("bucket:inflation:fast")),
                            "slow": _safe_float(row_dict.get("bucket:inflation:slow")),
                        },
                    },
                },
            )
            results.append(
                MethodResult(
                    as_of=as_of,
                    method_name=self.name,
                    quadrant=quadrant_snapshot,
                    native_label=qlabel,
                    native_detail={
                        "growth_confidence": _safe_float(row_dict.get("growth_confidence")),
                        "inflation_confidence": _safe_float(row_dict.get("inflation_confidence")),
                        "bucket_weights": dict(self.config.bucket_weights),
                    },
                )
            )
        return results


def _driver_map(row_dict: Mapping[str, object], ids: Sequence[str]) -> dict[str, float]:
    return {
        sid: float(row_dict.get(f"contrib:{sid}", float("nan")))
        for sid in ids
        if f"contrib:{sid}" in row_dict and not _is_nan(row_dict.get(f"contrib:{sid}"))
    }


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


__all__ = ["MacroRegimeConfig", "MacroRegimeMethod", "compute_macro_axis_scores"]
