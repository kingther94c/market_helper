"""Config-driven macro regime method.

The macro method consumes the FRED macro panel and classifies each date from
signed growth/inflation evidence. The aggregation is concept-based: each
``ConceptSpec`` (e.g. ``labor`` = UNRATE + PAYEMS, ``realized_broad`` = CPI +
core CPI + PCE + core PCE) aggregates several supporting series into one
latent measurement and carries its own ``weight`` for axis aggregation.
Within-concept weights compensate for redundancy among supporting series; the
concept weight expresses semantic importance.

All knobs (normalization window, clip, hysteresis, optional ``tanh``
compression) come from the ``engine:`` block of
``configs/regime_detection/fred_series.yml``; dataclass defaults exist only as
fallbacks when no config is provided.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Mapping, Sequence

import math

import numpy as np
import pandas as pd

from market_helper.data_sources.fred.macro_panel import (
    ConceptSpec,
    FRESHNESS_AGE_COLUMN_PREFIX,
    SeriesSpec,
    load_concept_specs,
    load_engine_block,
    specs_by_axis,
)
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
    default_normalization: str = "none"
    zscore_window_bdays: int = 2520
    min_periods: int = 252
    zscore_clip: float = 3.0
    minmax_default_window_bdays: int = 1260
    minmax_default_lower: float = -1.0
    minmax_default_upper: float = 1.0
    percentile_default_window_bdays: int = 1260
    # Optional smooth bound applied AFTER per-series normalization so a single
    # series can never dominate concept aggregation. Default is "none" to keep
    # the existing hard-clip behaviour; set to "tanh" with `compression_k` to
    # land each contribution in (-1, 1).
    compression: str = "none"  # "none" | "tanh"
    compression_k: float = 2.0
    # Concept-aggregation tuning.
    min_concept_coverage: float = 0.0  # min fraction of within-weight available
    recency_weighting_enabled: bool = False
    recency_half_life_bdays: float = 21.0
    recency_min_weight: float = 0.25
    min_consecutive_days: int = 10
    warmup_bdays: int = 0


def load_macro_regime_config(
    config_path: str | Path | None,
) -> MacroRegimeConfig:
    """Build a :class:`MacroRegimeConfig` from the ``engine:`` block of
    ``fred_series.yml``. Missing fields fall back to defaults."""
    if config_path is None:
        return MacroRegimeConfig()
    block = load_engine_block(config_path)
    defaults = MacroRegimeConfig()
    recency = block.get("recency_weighting", {})
    recency = recency if isinstance(recency, Mapping) else {}
    return MacroRegimeConfig(
        default_normalization=str(
            block.get("default_normalization", defaults.default_normalization)
        ),
        zscore_window_bdays=int(
            block.get("zscore_window_bdays", defaults.zscore_window_bdays)
        ),
        min_periods=int(
            block.get("zscore_min_periods", block.get("min_periods", defaults.min_periods))
        ),
        zscore_clip=float(block.get("zscore_clip", defaults.zscore_clip)),
        minmax_default_window_bdays=int(
            block.get("minmax_default_window_bdays", defaults.minmax_default_window_bdays)
        ),
        minmax_default_lower=float(
            block.get("minmax_default_lower", defaults.minmax_default_lower)
        ),
        minmax_default_upper=float(
            block.get("minmax_default_upper", defaults.minmax_default_upper)
        ),
        percentile_default_window_bdays=int(
            block.get(
                "percentile_default_window_bdays",
                defaults.percentile_default_window_bdays,
            )
        ),
        compression=str(block.get("compression", defaults.compression)),
        compression_k=float(block.get("compression_k", defaults.compression_k)),
        min_concept_coverage=float(
            block.get("min_concept_coverage", defaults.min_concept_coverage)
        ),
        recency_weighting_enabled=bool(
            recency.get(
                "enabled",
                block.get(
                    "recency_weighting_enabled",
                    defaults.recency_weighting_enabled,
                ),
            )
        ),
        recency_half_life_bdays=float(
            recency.get(
                "half_life_bdays",
                block.get("recency_half_life_bdays", defaults.recency_half_life_bdays),
            )
        ),
        recency_min_weight=float(
            recency.get(
                "min_weight",
                block.get("recency_min_weight", defaults.recency_min_weight),
            )
        ),
        min_consecutive_days=int(
            block.get("min_consecutive_days", defaults.min_consecutive_days)
        ),
        warmup_bdays=int(block.get("warmup_bdays", defaults.warmup_bdays)),
    )


def _rolling_zscore(series: pd.Series, window: int, min_periods: int) -> pd.Series:
    s = series.astype(float)
    roll = s.rolling(window=window, min_periods=min_periods)
    mu = roll.mean()
    sigma = roll.std(ddof=0)
    with np.errstate(invalid="ignore", divide="ignore"):
        z = (s - mu) / sigma
    return z.where(sigma > 0)


def _rolling_minmax(
    series: pd.Series,
    *,
    window: int,
    lower: float,
    upper: float,
) -> pd.Series:
    """Map series into [lower, upper] using a rolling min/max window.

    NaN where the window has not yet accumulated a min and max (i.e. before
    ``min_periods``); infinite-flat windows (min == max) collapse to the
    midpoint of [lower, upper]."""
    s = series.astype(float)
    min_periods = max(2, min(window, 30))
    roll = s.rolling(window=window, min_periods=min_periods)
    rmin = roll.min()
    rmax = roll.max()
    span = rmax - rmin
    midpoint = 0.5 * (lower + upper)
    with np.errstate(invalid="ignore", divide="ignore"):
        scaled = (s - rmin) / span
    out = lower + scaled * (upper - lower)
    out = out.where(span > 0, midpoint)
    return out


def _rolling_percentile(series: pd.Series, *, window: int) -> pd.Series:
    """Rolling rank in [-1, 1]: 2 * percentile - 1."""
    s = series.astype(float)
    min_periods = max(2, min(window, 30))

    def _rank(values: np.ndarray) -> float:
        last = values[-1]
        valid = values[~np.isnan(values)]
        if valid.size == 0 or np.isnan(last):
            return float("nan")
        rank = float((valid <= last).sum()) / float(valid.size)
        return 2.0 * rank - 1.0

    return s.rolling(window=window, min_periods=min_periods).apply(_rank, raw=True)


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
        # Clip after dividing by the threshold so a tail print (e.g. CPI 9% YoY
        # against a 0.5pp threshold and 2.5% neutral) can't dominate the bucket
        # score. Re-uses the z-score clip so all "signed" normalizations share
        # one tail bound.
        clip = spec.zscore_clip if spec.zscore_clip is not None else config.zscore_clip
        return _clip(signal / float(spec.threshold), clip)
    if mode == "zscore":
        window = spec.zscore_window_bdays or config.zscore_window_bdays
        min_periods = spec.zscore_min_periods or config.min_periods
        clip = spec.zscore_clip if spec.zscore_clip is not None else config.zscore_clip
        return _clip(
            _rolling_zscore(signal, window=window, min_periods=min_periods),
            clip,
        )
    if mode == "minmax":
        window = spec.minmax_window_bdays or config.minmax_default_window_bdays
        lower = (
            spec.minmax_lower
            if spec.minmax_lower is not None
            else config.minmax_default_lower
        )
        upper = (
            spec.minmax_upper
            if spec.minmax_upper is not None
            else config.minmax_default_upper
        )
        return _rolling_minmax(signal, window=window, lower=float(lower), upper=float(upper))
    if mode == "percentile":
        window = spec.percentile_window_bdays or config.percentile_default_window_bdays
        return _rolling_percentile(signal, window=window)
    raise ValueError(f"unsupported macro normalization: {mode!r}")


def _compress(series: pd.Series, config: MacroRegimeConfig) -> pd.Series:
    """Apply optional smooth compression after per-series normalization.

    ``tanh`` lands the contribution in (-1, 1) without a hard kink so a single
    series can never dominate concept aggregation, even before within-weights
    are applied. ``none`` is a passthrough — the upstream normalization may
    already clip.
    """
    if config.compression == "tanh":
        k = max(float(config.compression_k), 1e-9)
        return np.tanh(series.astype(float) / k)
    return series


def _recency_weight_for_series(
    frame: pd.DataFrame,
    series_id: str,
    *,
    config: MacroRegimeConfig,
) -> pd.Series:
    if not config.recency_weighting_enabled:
        return pd.Series(1.0, index=frame.index)
    half_life = max(float(config.recency_half_life_bdays), 1e-9)
    floor = min(max(float(config.recency_min_weight), 0.0), 1.0)
    age = _series_age_bdays(frame, series_id)
    with np.errstate(invalid="ignore"):
        weight = np.power(0.5, age.astype(float) / half_life)
    return weight.clip(lower=floor, upper=1.0).where(age.notna())


def _series_age_bdays(frame: pd.DataFrame, series_id: str) -> pd.Series:
    age_col = f"{FRESHNESS_AGE_COLUMN_PREFIX}{series_id}"
    if age_col in frame.columns:
        return pd.to_numeric(frame[age_col], errors="coerce")
    series = frame[series_id]
    valid = series.notna()
    changed_or_started = valid & (series.ne(series.shift()) | series.shift().isna())
    positions = pd.Series(np.arange(len(series), dtype=float), index=series.index)
    release_positions = positions.where(changed_or_started).ffill()
    return positions - release_positions


def compute_macro_axis_scores(
    panel: pd.DataFrame,
    specs: Sequence[SeriesSpec],
    concepts: Sequence[ConceptSpec],
    *,
    config: MacroRegimeConfig = MacroRegimeConfig(),
) -> pd.DataFrame:
    """Aggregate per-series signals into per-concept scores and per-axis scores.

    Pipeline per date:
        signed_signal -> normalize -> compress (optional tanh)
                      -> within-concept weighted mean
                      -> across-concept weighted mean
    Output columns:
        date, growth, inflation, growth_confidence, inflation_confidence,
        contrib:{series_id}, concept:{axis}:{concept_name}.
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

    spec_by_id = {s.series_id: s for s in specs}
    contribs: dict[str, pd.Series] = {}
    recency_weights: dict[str, pd.Series] = {}
    for sid, spec in spec_by_id.items():
        if sid not in frame.columns:
            continue
        signal = _signed_signal(frame[sid], spec)
        normalized = _normalize_signal(signal, spec, config=config)
        contribs[sid] = _compress(normalized, config)
        recency_weights[sid] = _recency_weight_for_series(
            frame,
            sid,
            config=config,
        )

    concepts_by_axis: dict[str, list[ConceptSpec]] = {"growth": [], "inflation": []}
    for c in concepts:
        concepts_by_axis.setdefault(c.axis, []).append(c)

    concept_scores: dict[tuple[str, str], pd.Series] = {}
    concept_avail: dict[tuple[str, str], pd.Series] = {}

    for axis, axis_concepts in concepts_by_axis.items():
        for concept in axis_concepts:
            available_members = [
                (sid, w) for sid, w in concept.members.items() if sid in contribs
            ]
            if not available_members:
                concept_scores[(axis, concept.name)] = pd.Series(np.nan, index=frame.index)
                concept_avail[(axis, concept.name)] = pd.Series(0.0, index=frame.index)
                continue
            cols = pd.DataFrame({sid: contribs[sid] for sid, _ in available_members})
            weights = pd.Series({sid: float(w) for sid, w in available_members}).reindex(cols.columns)
            freshness = pd.DataFrame(
                {sid: recency_weights[sid] for sid, _ in available_members}
            ).reindex(columns=cols.columns)
            mask = cols.notna().astype(float)
            effective_weights = mask.mul(weights, axis=1).mul(
                freshness.fillna(0.0),
                axis=1,
            )
            effective = effective_weights.sum(axis=1)
            score = cols.fillna(0.0).mul(effective_weights, axis=1).sum(axis=1) / effective.replace(0.0, np.nan)
            total_weight = float(sum(concept.members.values())) or 1.0
            availability = (effective / total_weight).clip(lower=0.0, upper=1.0)
            score = score.where(availability >= float(config.min_concept_coverage))
            concept_scores[(axis, concept.name)] = score
            concept_avail[(axis, concept.name)] = availability

    def _axis_score(axis: str) -> tuple[pd.Series, pd.Series]:
        axis_concepts = concepts_by_axis.get(axis, [])
        if not axis_concepts:
            empty = pd.Series(np.nan, index=frame.index)
            return empty, pd.Series(0.0, index=frame.index)
        weighted_sum = pd.Series(0.0, index=frame.index)
        weight_sum = pd.Series(0.0, index=frame.index)
        total_weight = float(sum(c.weight for c in axis_concepts)) or 1.0
        for concept in axis_concepts:
            score = concept_scores[(axis, concept.name)]
            availability = concept_avail[(axis, concept.name)]
            usable = (availability > 0) & score.notna()
            effective_concept_weight = availability.where(usable, 0.0) * float(concept.weight)
            weighted_sum = weighted_sum + score.where(usable, 0.0) * effective_concept_weight
            weight_sum = weight_sum + effective_concept_weight
        score = weighted_sum / weight_sum.replace(0.0, np.nan)
        confidence = (weight_sum / total_weight).clip(lower=0.0, upper=1.0)
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
    for (axis, name), score in concept_scores.items():
        out[f"concept:{axis}:{name}"] = score
    for (axis, name), availability in concept_avail.items():
        out[f"concept_availability:{axis}:{name}"] = availability
    for sid, series in contribs.items():
        out[f"contrib:{sid}"] = series
    for sid, series in recency_weights.items():
        out[f"recency_weight:{sid}"] = series
    return out.reset_index().rename(columns={"index": "date"})


class MacroRegimeMethod:
    name = "macro_regime"

    def __init__(
        self,
        specs: Sequence[SeriesSpec],
        concepts: Sequence[ConceptSpec],
        *,
        config: MacroRegimeConfig | None = None,
    ) -> None:
        self.specs = list(specs)
        self.concepts = list(concepts)
        self.config = config or MacroRegimeConfig()

    def classify(self, panel: pd.DataFrame) -> List[MethodResult]:
        scores = compute_macro_axis_scores(panel, self.specs, self.concepts, config=self.config)
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

        concept_growth = [c.name for c in self.concepts if c.axis == "growth"]
        concept_inflation = [c.name for c in self.concepts if c.axis == "inflation"]
        records = usable.to_dict(orient="records")
        results: List[MethodResult] = []
        for row_dict, qlabel, duration, g_pos, i_pos in zip(
            records, quadrants, durations, growth_sides, inflation_sides
        ):
            as_of = pd.Timestamp(row_dict["date"]).strftime("%Y-%m-%d")
            growth_drivers = _concept_driver_map(row_dict, "growth", concept_growth)
            inflation_drivers = _concept_driver_map(row_dict, "inflation", concept_inflation)
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
                    "concept_scores": {
                        axis: {
                            name: _safe_float(row_dict.get(f"concept:{axis}:{name}"))
                            for name in (concept_growth if axis == "growth" else concept_inflation)
                        }
                        for axis in ("growth", "inflation")
                    },
                    "concept_availability": {
                        axis: {
                            name: _safe_float(row_dict.get(f"concept_availability:{axis}:{name}"))
                            for name in (concept_growth if axis == "growth" else concept_inflation)
                        }
                        for axis in ("growth", "inflation")
                    },
                    "concept_weights": {
                        axis: {
                            c.name: float(c.weight)
                            for c in self.concepts
                            if c.axis == axis
                        }
                        for axis in ("growth", "inflation")
                    },
                    "recency_weighting": {
                        "enabled": bool(self.config.recency_weighting_enabled),
                        "half_life_bdays": float(self.config.recency_half_life_bdays),
                        "min_weight": float(self.config.recency_min_weight),
                    },
                    "recency_weights": {
                        sid: _safe_float(row_dict.get(f"recency_weight:{sid}"))
                        for sid in _active_concept_members(self.concepts)
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
                        "concept_weights": {
                            c.name: float(c.weight) for c in self.concepts
                        },
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


def _concept_driver_map(
    row_dict: Mapping[str, object], axis: str, names: Sequence[str]
) -> dict[str, float]:
    return {
        name: float(row_dict.get(f"concept:{axis}:{name}", float("nan")))
        for name in names
        if f"concept:{axis}:{name}" in row_dict
        and not _is_nan(row_dict.get(f"concept:{axis}:{name}"))
    }


def _active_concept_members(concepts: Sequence[ConceptSpec]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for concept in concepts:
        for sid in concept.members:
            if sid not in seen:
                seen.add(sid)
                out.append(sid)
    return out


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
    "ConceptSpec",
    "MacroRegimeConfig",
    "MacroRegimeMethod",
    "compute_macro_axis_scores",
    "load_concept_specs",
    "load_macro_regime_config",
]
