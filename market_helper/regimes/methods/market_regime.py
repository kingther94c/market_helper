"""Market-price based regime method."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, List, Mapping, Sequence

import math

import numpy as np
import pandas as pd
import yaml

from market_helper.data_sources.yahoo_finance.market_panel import MarketSymbolSpec
from market_helper.regimes.axes import (
    GrowthInflationAxes,
    QuadrantSnapshot,
    apply_sign_hysteresis,
    compute_duration_days,
    quadrant_from_signs,
)
from market_helper.regimes.methods.base import MethodResult


_ALLOWED_TRANSFORMS = {
    "return",
    "relative_return",
    "beta_adjusted_relative_return",
    "spread",
    "level",
    "change",
    "realized_vol",
    "raw_sign",
    # legacy aliases retained so the new schema can be adopted incrementally
    "level_zscore",
    "change_zscore",
    "realized_vol_zscore",
}

_ALLOWED_NORMALIZATIONS = {"zscore", "minmax", "percentile", "raw"}


@dataclass(frozen=True)
class MarketConceptSpec:
    """A market concept aggregates several supporting signals into one latent
    measurement of the same market narrative. Mirrors macro `ConceptSpec`:
    concept ``weight`` is semantic importance on the axis; ``members`` maps
    signal name to within-concept weight (compensates for redundancy among
    correlated signals like SPY/QQQ/IWM)."""

    name: str
    axis: str  # "growth" | "inflation" | "risk"
    weight: float
    members: Mapping[str, float]

    def validate(self) -> None:
        if self.axis not in {"growth", "inflation", "risk"}:
            raise ValueError(f"market concept {self.name!r}: unsupported axis {self.axis!r}")
        if self.weight < 0:
            raise ValueError(f"market concept {self.name!r}: weight must be non-negative")
        if not self.members:
            raise ValueError(f"market concept {self.name!r}: must have at least one member")
        for sid, w in self.members.items():
            if w < 0:
                raise ValueError(
                    f"market concept {self.name!r}: within-weight for {sid} must be non-negative"
                )


@dataclass(frozen=True)
class MarketSignalSpec:
    name: str
    axis: str
    transform: str
    symbol: str | None = None
    numerator: str | None = None
    denominator: str | None = None
    direction: str = "positive"
    weight: float = 1.0
    lookback_days: int = 63
    normalization: str = "zscore"
    zscore_window_days: int = 756
    threshold: float = 0.0
    minmax_lower: float | None = None
    minmax_upper: float | None = None
    minmax_window_days: int | None = None
    percentile_window_days: int | None = None
    # Beta-adjusted-relative-return tuning. EWMA span for the rolling beta of
    # numerator returns regressed on denominator returns; clipping bounds the
    # estimate so a tail print can't flip beta sign.
    beta_window_days: int = 60
    beta_clip: float = 3.0

    def validate(self) -> None:
        if self.axis not in {"growth", "inflation", "risk"}:
            raise ValueError(f"{self.name}: unsupported axis {self.axis!r}")
        if self.direction not in {"positive", "negative"}:
            raise ValueError(f"{self.name}: unsupported direction {self.direction!r}")
        if self.transform not in _ALLOWED_TRANSFORMS:
            raise ValueError(f"{self.name}: unsupported transform {self.transform!r}")
        if self.normalization not in _ALLOWED_NORMALIZATIONS:
            raise ValueError(
                f"{self.name}: unsupported normalization {self.normalization!r}"
            )

    @property
    def effective_transform(self) -> str:
        # Map legacy combined tokens onto the new (transform, normalization) pair.
        if self.transform == "level_zscore":
            return "level"
        if self.transform == "change_zscore":
            return "change"
        if self.transform == "realized_vol_zscore":
            return "realized_vol"
        return self.transform

    @property
    def effective_normalization(self) -> str:
        if self.transform in {"level_zscore", "change_zscore", "realized_vol_zscore"}:
            return "zscore"
        if self.transform == "raw_sign":
            return "raw"
        return self.normalization


@dataclass(frozen=True)
class MarketRegimeConfig:
    signals: Sequence[MarketSignalSpec]
    concepts: Sequence[MarketConceptSpec] = field(default_factory=tuple)
    risk_enter_threshold: float = 0.75
    risk_exit_threshold: float = 0.55
    min_consecutive_days: int = 5
    risk_min_consecutive_days: int = 3
    zscore_clip: float = 3.0
    default_normalization: str = "zscore"
    zscore_default_window_days: int = 756
    minmax_default_window_days: int = 504
    minmax_default_lower: float = -1.0
    minmax_default_upper: float = 1.0
    percentile_default_window_days: int = 504
    # Optional smooth bound applied AFTER per-signal normalization so the
    # market layer lives in the same (-1, 1) latent space as the macro layer
    # post-Q2. Mirror of MacroRegimeConfig.compression.
    compression: str = "none"  # "none" | "tanh"
    compression_k: float = 2.0
    # Min fraction of within-concept weight that must be present for a concept
    # score to be defined; reweights remaining members across the available set.
    min_concept_coverage: float = 0.0


def load_market_regime_config(path: str | Path) -> MarketRegimeConfig:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, Mapping):
        raise ValueError(f"{path}: expected YAML mapping")
    normalization = raw.get("normalization", {}) if isinstance(raw.get("normalization"), Mapping) else {}
    default_normalization = str(normalization.get("default", "zscore"))
    zscore_default_window_days = int(normalization.get("zscore_window_days", 756))
    signals: list[MarketSignalSpec] = []
    for axis in ("growth", "inflation"):
        for entry in raw.get(axis, {}).get("signals", []):
            if not isinstance(entry, Mapping):
                continue
            signals.append(
                _signal_from_entry(
                    axis,
                    entry,
                    default_normalization=default_normalization,
                    default_zscore_window=zscore_default_window_days,
                )
            )
    for entry in raw.get("risk_overlay", {}).get("signals", []):
        if not isinstance(entry, Mapping):
            continue
        signals.append(
            _signal_from_entry(
                "risk",
                entry,
                default_normalization=default_normalization,
                default_zscore_window=zscore_default_window_days,
            )
        )
    risk = raw.get("risk_overlay", {}) if isinstance(raw.get("risk_overlay"), Mapping) else {}
    hysteresis = raw.get("hysteresis", {}) if isinstance(raw.get("hysteresis"), Mapping) else {}

    concepts: list[MarketConceptSpec] = []
    for axis_key, axis in (
        ("growth_concepts", "growth"),
        ("inflation_concepts", "inflation"),
        ("risk_concepts", "risk"),
    ):
        block = raw.get(axis_key)
        if block is None:
            continue
        if not isinstance(block, Mapping):
            raise ValueError(f"{path}: {axis_key!r} must be a mapping")
        for cname, body in block.items():
            if not isinstance(body, Mapping):
                raise ValueError(f"{path}: market concept {cname!r} must be a mapping")
            cweight = float(body.get("weight", 1.0))
            members_raw = body.get("signals", body.get("members", {}))
            if not isinstance(members_raw, Mapping):
                raise ValueError(
                    f"{path}: concept {cname!r} 'signals' must map signal name -> within_weight"
                )
            members = {str(name): float(w) for name, w in members_raw.items()}
            spec = MarketConceptSpec(name=str(cname), axis=axis, weight=cweight, members=members)
            spec.validate()
            concepts.append(spec)

    cfg = MarketRegimeConfig(
        signals=signals,
        concepts=tuple(concepts),
        risk_enter_threshold=float(risk.get("enter_threshold", 0.75)),
        risk_exit_threshold=float(risk.get("exit_threshold", 0.55)),
        min_consecutive_days=int(hysteresis.get("min_consecutive_days", 5)),
        risk_min_consecutive_days=int(risk.get("min_consecutive_days", 3)),
        zscore_clip=float(normalization.get("zscore_clip", 3.0)),
        default_normalization=default_normalization,
        zscore_default_window_days=zscore_default_window_days,
        minmax_default_window_days=int(
            normalization.get("minmax_default_window_days", 504)
        ),
        minmax_default_lower=float(normalization.get("minmax_default_lower", -1.0)),
        minmax_default_upper=float(normalization.get("minmax_default_upper", 1.0)),
        percentile_default_window_days=int(
            normalization.get("percentile_default_window_days", 504)
        ),
        compression=str(normalization.get("compression", "none")),
        compression_k=float(normalization.get("compression_k", 2.0)),
    )
    for signal in cfg.signals:
        signal.validate()
    return cfg


def market_symbol_specs_from_config(path: str | Path) -> list[MarketSymbolSpec]:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, Mapping):
        raise ValueError(f"{path}: expected YAML mapping")
    symbols: dict[str, MarketSymbolSpec] = {}
    for entry in raw.get("data_sources", {}).get("symbols", []):
        if not isinstance(entry, Mapping):
            continue
        symbol = str(entry["symbol"])
        alias = str(entry.get("alias") or symbol)
        symbols[alias] = MarketSymbolSpec(symbol=symbol, alias=alias)
    for section in ("growth", "inflation"):
        for entry in raw.get(section, {}).get("signals", []):
            _collect_symbols(symbols, entry)
    for entry in raw.get("risk_overlay", {}).get("signals", []):
        _collect_symbols(symbols, entry)
    return list(symbols.values())


def compute_market_axis_scores(
    panel: pd.DataFrame,
    config: MarketRegimeConfig,
) -> pd.DataFrame:
    if panel.empty:
        return pd.DataFrame(columns=["date", "growth", "inflation", "risk_score"])
    frame = panel.copy()
    if "date" in frame.columns:
        frame = frame.set_index(pd.to_datetime(frame["date"])).drop(columns=["date"])
    frame.index.name = "date"

    # Per-signal contributions live in (-1, 1) post-tanh. We store the
    # *normalized* contribution (no within-weight applied yet) so the concept
    # aggregator can apply within-weights cleanly. When concepts are absent we
    # fall back to flat per-signal aggregation using the signal's own weight.
    contribs: dict[str, pd.Series] = {}
    contribs_signal_only: dict[str, pd.Series] = {}
    for signal in config.signals:
        raw = _compute_signal(frame, signal, config)
        if raw is None:
            continue
        if signal.direction == "negative":
            raw = -raw
        if signal.threshold > 0:
            raw = raw.where(raw.abs() >= float(signal.threshold), 0.0)
        bounded = _clip(raw, config.zscore_clip)
        if config.compression == "tanh":
            k = max(float(config.compression_k), 1e-9)
            bounded = np.tanh(bounded / k)
        contribs_signal_only[signal.name] = bounded
        contribs[signal.name] = bounded * float(signal.weight)

    if config.concepts:
        # Concept aggregation: signal -> concept (within-weighted) -> axis
        # (concept-weighted). Mirror of the macro side.
        concepts_by_axis: dict[str, list[MarketConceptSpec]] = {"growth": [], "inflation": [], "risk": []}
        for c in config.concepts:
            concepts_by_axis.setdefault(c.axis, []).append(c)

        concept_scores: dict[tuple[str, str], pd.Series] = {}

        for axis, axis_concepts in concepts_by_axis.items():
            for concept in axis_concepts:
                available = [
                    (sid, w) for sid, w in concept.members.items() if sid in contribs_signal_only
                ]
                if not available:
                    concept_scores[(axis, concept.name)] = pd.Series(np.nan, index=frame.index)
                    continue
                cols = pd.DataFrame({sid: contribs_signal_only[sid] for sid, _ in available})
                weights = pd.Series({sid: float(w) for sid, w in available}).reindex(cols.columns)
                mask = cols.notna().astype(float)
                effective = mask.mul(weights, axis=1).sum(axis=1)
                score = cols.fillna(0.0).mul(weights, axis=1).sum(axis=1) / effective.replace(0.0, np.nan)
                total_weight = float(sum(concept.members.values())) or 1.0
                availability = (effective / total_weight).clip(lower=0.0, upper=1.0)
                score = score.where(availability >= float(config.min_concept_coverage))
                concept_scores[(axis, concept.name)] = score

        def _axis_mean(axis: str) -> tuple[pd.Series, pd.Series]:
            axis_concepts = concepts_by_axis.get(axis, [])
            if not axis_concepts:
                empty = pd.Series(np.nan, index=frame.index)
                return empty, pd.Series(0.0, index=frame.index)
            weighted_sum = pd.Series(0.0, index=frame.index)
            weight_sum = pd.Series(0.0, index=frame.index)
            total_weight = float(sum(c.weight for c in axis_concepts)) or 1.0
            for concept in axis_concepts:
                score = concept_scores[(axis, concept.name)]
                usable = score.notna()
                w = float(concept.weight)
                weighted_sum = weighted_sum + score.where(usable, 0.0) * w
                weight_sum = weight_sum + usable.astype(float) * w
            score = weighted_sum / weight_sum.replace(0.0, np.nan)
            confidence = (weight_sum / total_weight).clip(lower=0.0, upper=1.0)
            return score, confidence
    else:
        # Backward-compatible flat per-signal aggregation when no concepts
        # block is present in the YAML.
        def _axis_mean(axis: str) -> tuple[pd.Series, pd.Series]:
            axis_signals = [s for s in config.signals if s.axis == axis and s.name in contribs]
            if not axis_signals:
                empty = pd.Series(np.nan, index=frame.index)
                return empty, pd.Series(0.0, index=frame.index)
            cols = pd.DataFrame({s.name: contribs[s.name] for s in axis_signals})
            weights = pd.Series({s.name: float(s.weight) for s in axis_signals}).reindex(cols.columns)
            mask = cols.notna().astype(float)
            effective = mask.mul(weights, axis=1).sum(axis=1)
            score = cols.fillna(0.0).sum(axis=1) / effective.replace(0.0, np.nan)
            confidence = (effective / float(weights.sum())).clip(lower=0.0, upper=1.0)
            return score, confidence

    growth, growth_conf = _axis_mean("growth")
    inflation, inflation_conf = _axis_mean("inflation")
    risk_score, risk_conf = _axis_mean("risk")
    out = pd.DataFrame(
        {
            "growth": growth,
            "inflation": inflation,
            "risk_score": risk_score,
            "growth_confidence": growth_conf,
            "inflation_confidence": inflation_conf,
            "risk_confidence": risk_conf,
        },
        index=frame.index,
    )
    for name, series in contribs.items():
        out[f"contrib:{name}"] = series
    if config.concepts:
        for (axis, name), score in concept_scores.items():
            out[f"concept:{axis}:{name}"] = score
    return out.reset_index().rename(columns={"index": "date"})


def compute_market_risk_overlay_states(
    panel: pd.DataFrame,
    config: MarketRegimeConfig,
) -> pd.DataFrame:
    """Compute the independent market risk overlay without requiring axis data.

    The v2 engine treats risk/stress as a standalone overlay. That means risk
    rows must remain available even when growth/inflation signals are disabled
    or missing on a given date.
    """
    scores = compute_market_axis_scores(panel, config)
    return _risk_overlay_rows(scores, config)


class MarketRegimeMethod:
    name = "market_regime"

    def __init__(self, config: MarketRegimeConfig) -> None:
        self.config = config

    def classify(self, panel: pd.DataFrame) -> List[MethodResult]:
        scores = compute_market_axis_scores(panel, self.config)
        if scores.empty:
            return []
        risk_rows = _risk_overlay_rows(scores, self.config)
        risk_by_date = {
            pd.Timestamp(row["date"]).strftime("%Y-%m-%d"): {
                "risk_overlay_on": bool(row["risk_overlay_on"]),
                "risk_intensity": float(row["risk_intensity"]),
                "risk_regime": str(row["risk_regime"]),
            }
            for row in risk_rows.to_dict(orient="records")
        }
        usable = scores.sort_values("date").dropna(
            subset=["growth", "inflation"], how="all"
        ).reset_index(drop=True)
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
        records = usable.to_dict(orient="records")
        growth_signal_names = [s.name for s in self.config.signals if s.axis == "growth"]
        inflation_signal_names = [s.name for s in self.config.signals if s.axis == "inflation"]
        risk_signal_names = [s.name for s in self.config.signals if s.axis == "risk"]
        growth_concept_names = [c.name for c in self.config.concepts if c.axis == "growth"]
        inflation_concept_names = [c.name for c in self.config.concepts if c.axis == "inflation"]
        risk_concept_names = [c.name for c in self.config.concepts if c.axis == "risk"]
        # When concepts are present, drivers expose CONCEPT contributions so
        # downstream consumers (regime HTML, top-contributor lists) speak the
        # same semantic vocabulary as the macro layer. Without concepts the
        # signal-level drivers are kept for backward compat.
        use_concepts = bool(self.config.concepts)

        def _growth_drivers(row_dict: Mapping[str, object]) -> dict[str, float]:
            if use_concepts:
                return _concept_driver_map_market(row_dict, "growth", growth_concept_names)
            return _driver_map(row_dict, growth_signal_names)

        def _inflation_drivers(row_dict: Mapping[str, object]) -> dict[str, float]:
            if use_concepts:
                return _concept_driver_map_market(row_dict, "inflation", inflation_concept_names)
            return _driver_map(row_dict, inflation_signal_names)

        def _risk_drivers(row_dict: Mapping[str, object]) -> dict[str, float]:
            if use_concepts:
                return _concept_driver_map_market(row_dict, "risk", risk_concept_names)
            return _driver_map(row_dict, risk_signal_names)

        results: List[MethodResult] = []
        for row, qlabel, duration, g_pos, i_pos in zip(
            records,
            quadrants,
            durations,
            growth_sides,
            inflation_sides,
        ):
            as_of = pd.Timestamp(row["date"]).strftime("%Y-%m-%d")
            risk_meta = risk_by_date.get(
                as_of,
                {
                    "risk_overlay_on": False,
                    "risk_intensity": 0.0,
                    "risk_regime": "neutral",
                },
            )
            axes = GrowthInflationAxes(
                as_of=as_of,
                growth_score=_safe_float(row.get("growth")),
                inflation_score=_safe_float(row.get("inflation")),
                growth_drivers=_growth_drivers(row),
                inflation_drivers=_inflation_drivers(row),
                confidence=_combine_confidence(
                    row.get("growth_confidence"), row.get("inflation_confidence")
                ),
            )
            diag: dict[str, Any] = {
                "risk_regime": risk_meta["risk_regime"],
                "risk_score": _safe_float(row.get("risk_score")),
                "risk_drivers": _risk_drivers(row),
                "hysteresis_growth_positive": bool(g_pos),
                "hysteresis_inflation_positive": bool(i_pos),
            }
            if use_concepts:
                diag["concept_scores"] = {
                    "growth": {
                        name: _safe_float(row.get(f"concept:growth:{name}"))
                        for name in growth_concept_names
                    },
                    "inflation": {
                        name: _safe_float(row.get(f"concept:inflation:{name}"))
                        for name in inflation_concept_names
                    },
                    "risk": {
                        name: _safe_float(row.get(f"concept:risk:{name}"))
                        for name in risk_concept_names
                    },
                }
                diag["concept_weights"] = {
                    axis: {
                        c.name: float(c.weight)
                        for c in self.config.concepts
                        if c.axis == axis
                    }
                    for axis in ("growth", "inflation", "risk")
                }
            quadrant = QuadrantSnapshot(
                as_of=as_of,
                quadrant=qlabel,
                axes=axes,
                crisis_flag=bool(risk_meta["risk_overlay_on"]),
                crisis_intensity=float(risk_meta["risk_intensity"]),
                duration_days=int(duration),
                diagnostics=diag,
            )
            results.append(
                MethodResult(
                    as_of=as_of,
                    method_name=self.name,
                    quadrant=quadrant,
                    native_label=f"{qlabel} / {risk_meta['risk_regime']}",
                    native_detail={
                        "risk_score": _safe_float(row.get("risk_score")),
                        "risk_regime": risk_meta["risk_regime"],
                    },
                )
            )
        return results


def _signal_from_entry(
    axis: str,
    entry: Mapping[str, Any],
    *,
    default_normalization: str = "zscore",
    default_zscore_window: int = 756,
) -> MarketSignalSpec:
    transform = str(entry.get("transform", "return"))
    legacy_zscore_token = transform in {
        "level_zscore",
        "change_zscore",
        "realized_vol_zscore",
    }
    if "normalization" in entry:
        normalization = str(entry["normalization"])
    elif legacy_zscore_token:
        normalization = "zscore"
    elif transform == "raw_sign":
        normalization = "raw"
    else:
        normalization = default_normalization

    def _opt_float(key: str) -> float | None:
        value = entry.get(key)
        return float(value) if value is not None else None

    def _opt_int(key: str) -> int | None:
        value = entry.get(key)
        return int(value) if value is not None else None

    return MarketSignalSpec(
        name=str(entry["name"]),
        axis=axis,
        transform=transform,
        symbol=str(entry["symbol"]) if entry.get("symbol") is not None else None,
        numerator=str(entry["numerator"]) if entry.get("numerator") is not None else None,
        denominator=str(entry["denominator"]) if entry.get("denominator") is not None else None,
        direction=str(entry.get("direction", "positive")),
        weight=float(entry.get("weight", 1.0)),
        lookback_days=int(entry.get("lookback_days", 63)),
        normalization=normalization,
        zscore_window_days=int(entry.get("zscore_window_days", default_zscore_window)),
        threshold=float(entry.get("threshold", 0.0)),
        minmax_lower=_opt_float("minmax_lower"),
        minmax_upper=_opt_float("minmax_upper"),
        minmax_window_days=_opt_int("minmax_window_days"),
        percentile_window_days=_opt_int("percentile_window_days"),
        beta_window_days=int(entry.get("beta_window_days", 60)),
        beta_clip=float(entry.get("beta_clip", 3.0)),
    )


def _collect_symbols(symbols: dict[str, MarketSymbolSpec], entry: object) -> None:
    if not isinstance(entry, Mapping):
        return
    for key in ("symbol", "numerator", "denominator"):
        value = entry.get(key)
        if value:
            text = str(value)
            symbols.setdefault(text, MarketSymbolSpec(symbol=text, alias=text))


def _compute_signal(
    frame: pd.DataFrame,
    signal: MarketSignalSpec,
    config: MarketRegimeConfig,
) -> pd.Series | None:
    raw = _raw_transform(frame, signal)
    if raw is None:
        return None
    return _normalize(raw, signal, config)


def _raw_transform(frame: pd.DataFrame, signal: MarketSignalSpec) -> pd.Series | None:
    transform = signal.effective_transform
    if transform in {"return"}:
        if signal.symbol not in frame.columns:
            return None
        return frame[signal.symbol].pct_change(signal.lookback_days)
    if transform == "raw_sign":
        if signal.symbol not in frame.columns:
            return None
        return frame[signal.symbol].pct_change(signal.lookback_days)
    if transform == "relative_return":
        if signal.numerator not in frame.columns or signal.denominator not in frame.columns:
            return None
        return frame[signal.numerator].pct_change(signal.lookback_days) - frame[
            signal.denominator
        ].pct_change(signal.lookback_days)
    if transform == "beta_adjusted_relative_return":
        if signal.numerator not in frame.columns or signal.denominator not in frame.columns:
            return None
        # Daily returns of numerator and denominator
        num_daily = frame[signal.numerator].pct_change()
        den_daily = frame[signal.denominator].pct_change()
        span = max(int(signal.beta_window_days), 5)
        cov = num_daily.ewm(span=span, adjust=False, min_periods=max(20, span // 2)).cov(den_daily)
        var = den_daily.ewm(span=span, adjust=False, min_periods=max(20, span // 2)).var()
        beta = (cov / var.replace(0.0, np.nan)).clip(
            lower=-float(signal.beta_clip), upper=float(signal.beta_clip)
        )
        # Daily residual: numerator return minus market-beta * benchmark return
        residual_daily = num_daily - beta * den_daily
        # Cumulative residual over the lookback window
        return residual_daily.rolling(
            signal.lookback_days,
            min_periods=max(20, signal.lookback_days // 2),
        ).sum()
    if transform == "spread":
        if signal.numerator not in frame.columns or signal.denominator not in frame.columns:
            return None
        return frame[signal.numerator] / frame[signal.denominator] - 1.0
    if transform == "level":
        if signal.symbol not in frame.columns:
            return None
        return frame[signal.symbol].astype(float)
    if transform == "change":
        if signal.symbol not in frame.columns:
            return None
        return frame[signal.symbol].diff(signal.lookback_days)
    if transform == "realized_vol":
        if signal.symbol not in frame.columns:
            return None
        return frame[signal.symbol].pct_change().rolling(signal.lookback_days).std()
    raise ValueError(f"unsupported transform {signal.transform!r}")


def _normalize(
    series: pd.Series,
    signal: MarketSignalSpec,
    config: MarketRegimeConfig,
) -> pd.Series:
    mode = signal.effective_normalization
    if mode == "raw":
        return series.astype(float)
    if mode == "zscore":
        return _zscore(series, signal.zscore_window_days or config.zscore_default_window_days)
    if mode == "minmax":
        window = signal.minmax_window_days or config.minmax_default_window_days
        lower = (
            signal.minmax_lower
            if signal.minmax_lower is not None
            else config.minmax_default_lower
        )
        upper = (
            signal.minmax_upper
            if signal.minmax_upper is not None
            else config.minmax_default_upper
        )
        return _rolling_minmax(series, window=window, lower=float(lower), upper=float(upper))
    if mode == "percentile":
        window = signal.percentile_window_days or config.percentile_default_window_days
        return _rolling_percentile(series, window=window)
    raise ValueError(f"unsupported market normalization: {mode!r}")


def _zscore(series: pd.Series, window: int) -> pd.Series:
    roll = series.astype(float).rolling(window=window, min_periods=max(20, min(window, 63)))
    mu = roll.mean()
    sigma = roll.std(ddof=0)
    with np.errstate(invalid="ignore", divide="ignore"):
        z = (series - mu) / sigma
    return z.where(sigma > 0)


def _rolling_minmax(
    series: pd.Series,
    *,
    window: int,
    lower: float,
    upper: float,
) -> pd.Series:
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
    return out.where(span > 0, midpoint)


def _rolling_percentile(series: pd.Series, *, window: int) -> pd.Series:
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


def _risk_overlay(
    scores: Sequence[float],
    *,
    enter_threshold: float,
    exit_threshold: float,
    min_consecutive_days: int,
    zscore_clip: float,
) -> tuple[list[bool], list[float], list[str]]:
    flags: list[bool] = []
    intensities: list[float] = []
    regimes: list[str] = []
    active = False
    pending_exit = 0
    pending_enter = 0
    for score in scores:
        if active:
            if score <= exit_threshold:
                pending_exit += 1
            else:
                pending_exit = 0
            if pending_exit >= min_consecutive_days:
                active = False
                pending_exit = 0
        else:
            if score >= enter_threshold:
                pending_enter += 1
            else:
                pending_enter = 0
            if pending_enter >= min_consecutive_days:
                active = True
                pending_enter = 0
        intensity = max(0.0, min(1.0, score / max(enter_threshold, zscore_clip, 1e-9)))
        flags.append(bool(active))
        intensities.append(float(intensity if active else 0.0))
        regimes.append("risk_off" if active else ("risk_on" if score < 0 else "neutral"))
    return flags, intensities, regimes


def _risk_overlay_rows(
    scores: pd.DataFrame,
    config: MarketRegimeConfig,
) -> pd.DataFrame:
    if scores.empty or "risk_score" not in scores.columns:
        return pd.DataFrame()
    usable = scores.sort_values("date").dropna(subset=["risk_score"]).reset_index(drop=True)
    if usable.empty:
        return usable
    flags, intensities, regimes = _risk_overlay(
        usable["risk_score"].tolist(),
        enter_threshold=config.risk_enter_threshold,
        exit_threshold=config.risk_exit_threshold,
        min_consecutive_days=config.risk_min_consecutive_days,
        zscore_clip=config.zscore_clip,
    )
    out = usable.copy()
    out["risk_overlay_on"] = flags
    out["risk_intensity"] = intensities
    out["risk_regime"] = regimes
    return out


def _clip(series: pd.Series, limit: float) -> pd.Series:
    if limit <= 0 or not math.isfinite(limit):
        return series
    return series.clip(lower=-limit, upper=limit)


def _driver_map(row: Mapping[str, object], names: Sequence[str]) -> dict[str, float]:
    return {
        name: float(row.get(f"contrib:{name}", float("nan")))
        for name in names
        if f"contrib:{name}" in row and not _is_nan(row.get(f"contrib:{name}"))
    }


def _concept_driver_map_market(
    row: Mapping[str, object], axis: str, concept_names: Sequence[str]
) -> dict[str, float]:
    out: dict[str, float] = {}
    for name in concept_names:
        key = f"concept:{axis}:{name}"
        if key in row and not _is_nan(row.get(key)):
            out[name] = float(row[key])
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
    return max(0.0, min(1.0, 0.5 * (_safe_float(g) + _safe_float(i))))


__all__ = [
    "MarketConceptSpec",
    "MarketRegimeConfig",
    "MarketRegimeMethod",
    "MarketSignalSpec",
    "compute_market_axis_scores",
    "compute_market_risk_overlay_states",
    "load_market_regime_config",
    "market_symbol_specs_from_config",
]
