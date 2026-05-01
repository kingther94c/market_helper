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
    zscore_window_days: int = 756
    threshold: float = 0.0

    def validate(self) -> None:
        if self.axis not in {"growth", "inflation", "risk"}:
            raise ValueError(f"{self.name}: unsupported axis {self.axis!r}")
        if self.direction not in {"positive", "negative"}:
            raise ValueError(f"{self.name}: unsupported direction {self.direction!r}")
        if self.transform not in {
            "return",
            "relative_return",
            "spread",
            "level_zscore",
            "change_zscore",
            "realized_vol_zscore",
            "raw_sign",
        }:
            raise ValueError(f"{self.name}: unsupported transform {self.transform!r}")


@dataclass(frozen=True)
class MarketRegimeConfig:
    signals: Sequence[MarketSignalSpec]
    risk_enter_threshold: float = 0.75
    risk_exit_threshold: float = 0.55
    min_consecutive_days: int = 5
    risk_min_consecutive_days: int = 3
    zscore_clip: float = 3.0


def load_market_regime_config(path: str | Path) -> MarketRegimeConfig:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, Mapping):
        raise ValueError(f"{path}: expected YAML mapping")
    signals: list[MarketSignalSpec] = []
    for axis in ("growth", "inflation"):
        for entry in raw.get(axis, {}).get("signals", []):
            if not isinstance(entry, Mapping):
                continue
            signals.append(_signal_from_entry(axis, entry))
    for entry in raw.get("risk_overlay", {}).get("signals", []):
        if not isinstance(entry, Mapping):
            continue
        signals.append(_signal_from_entry("risk", entry))
    risk = raw.get("risk_overlay", {}) if isinstance(raw.get("risk_overlay"), Mapping) else {}
    hysteresis = raw.get("hysteresis", {}) if isinstance(raw.get("hysteresis"), Mapping) else {}
    normalization = raw.get("normalization", {}) if isinstance(raw.get("normalization"), Mapping) else {}
    cfg = MarketRegimeConfig(
        signals=signals,
        risk_enter_threshold=float(risk.get("enter_threshold", 0.75)),
        risk_exit_threshold=float(risk.get("exit_threshold", 0.55)),
        min_consecutive_days=int(hysteresis.get("min_consecutive_days", 5)),
        risk_min_consecutive_days=int(risk.get("min_consecutive_days", 3)),
        zscore_clip=float(normalization.get("zscore_clip", 3.0)),
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

    contribs: dict[str, pd.Series] = {}
    for signal in config.signals:
        raw = _compute_signal(frame, signal)
        if raw is None:
            continue
        if signal.direction == "negative":
            raw = -raw
        if signal.threshold > 0:
            raw = raw.where(raw.abs() >= float(signal.threshold), 0.0)
        contribs[signal.name] = _clip(raw, config.zscore_clip) * float(signal.weight)

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
    return out.reset_index().rename(columns={"index": "date"})


class MarketRegimeMethod:
    name = "market_regime"

    def __init__(self, config: MarketRegimeConfig) -> None:
        self.config = config

    def classify(self, panel: pd.DataFrame) -> List[MethodResult]:
        scores = compute_market_axis_scores(panel, self.config)
        if scores.empty:
            return []
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
        crisis_flags, crisis_intensities, risk_regimes = _risk_overlay(
            usable["risk_score"].fillna(0.0).tolist(),
            enter_threshold=self.config.risk_enter_threshold,
            exit_threshold=self.config.risk_exit_threshold,
            min_consecutive_days=self.config.risk_min_consecutive_days,
            zscore_clip=self.config.zscore_clip,
        )
        records = usable.to_dict(orient="records")
        growth_names = [s.name for s in self.config.signals if s.axis == "growth"]
        inflation_names = [s.name for s in self.config.signals if s.axis == "inflation"]
        risk_names = [s.name for s in self.config.signals if s.axis == "risk"]
        results: List[MethodResult] = []
        for row, qlabel, duration, g_pos, i_pos, crisis, intensity, risk_regime in zip(
            records,
            quadrants,
            durations,
            growth_sides,
            inflation_sides,
            crisis_flags,
            crisis_intensities,
            risk_regimes,
        ):
            as_of = pd.Timestamp(row["date"]).strftime("%Y-%m-%d")
            axes = GrowthInflationAxes(
                as_of=as_of,
                growth_score=_safe_float(row.get("growth")),
                inflation_score=_safe_float(row.get("inflation")),
                growth_drivers=_driver_map(row, growth_names),
                inflation_drivers=_driver_map(row, inflation_names),
                confidence=_combine_confidence(
                    row.get("growth_confidence"), row.get("inflation_confidence")
                ),
            )
            quadrant = QuadrantSnapshot(
                as_of=as_of,
                quadrant=qlabel,
                axes=axes,
                crisis_flag=bool(crisis),
                crisis_intensity=float(intensity),
                duration_days=int(duration),
                diagnostics={
                    "risk_regime": risk_regime,
                    "risk_score": _safe_float(row.get("risk_score")),
                    "risk_drivers": _driver_map(row, risk_names),
                    "hysteresis_growth_positive": bool(g_pos),
                    "hysteresis_inflation_positive": bool(i_pos),
                },
            )
            results.append(
                MethodResult(
                    as_of=as_of,
                    method_name=self.name,
                    quadrant=quadrant,
                    native_label=f"{qlabel} / {risk_regime}",
                    native_detail={
                        "risk_score": _safe_float(row.get("risk_score")),
                        "risk_regime": risk_regime,
                    },
                )
            )
        return results


def _signal_from_entry(axis: str, entry: Mapping[str, Any]) -> MarketSignalSpec:
    return MarketSignalSpec(
        name=str(entry["name"]),
        axis=axis,
        transform=str(entry.get("transform", "return")),
        symbol=str(entry["symbol"]) if entry.get("symbol") is not None else None,
        numerator=str(entry["numerator"]) if entry.get("numerator") is not None else None,
        denominator=str(entry["denominator"]) if entry.get("denominator") is not None else None,
        direction=str(entry.get("direction", "positive")),
        weight=float(entry.get("weight", 1.0)),
        lookback_days=int(entry.get("lookback_days", 63)),
        zscore_window_days=int(entry.get("zscore_window_days", 756)),
        threshold=float(entry.get("threshold", 0.0)),
    )


def _collect_symbols(symbols: dict[str, MarketSymbolSpec], entry: object) -> None:
    if not isinstance(entry, Mapping):
        return
    for key in ("symbol", "numerator", "denominator"):
        value = entry.get(key)
        if value:
            text = str(value)
            symbols.setdefault(text, MarketSymbolSpec(symbol=text, alias=text))


def _compute_signal(frame: pd.DataFrame, signal: MarketSignalSpec) -> pd.Series | None:
    if signal.transform in {"return", "raw_sign"}:
        if signal.symbol not in frame.columns:
            return None
        ret = frame[signal.symbol].pct_change(signal.lookback_days)
        return ret if signal.transform == "raw_sign" else _zscore(ret, signal.zscore_window_days)
    if signal.transform == "relative_return":
        if signal.numerator not in frame.columns or signal.denominator not in frame.columns:
            return None
        rel = frame[signal.numerator].pct_change(signal.lookback_days) - frame[
            signal.denominator
        ].pct_change(signal.lookback_days)
        return _zscore(rel, signal.zscore_window_days)
    if signal.transform == "spread":
        if signal.numerator not in frame.columns or signal.denominator not in frame.columns:
            return None
        spread = frame[signal.numerator] / frame[signal.denominator] - 1.0
        return _zscore(spread, signal.zscore_window_days)
    if signal.transform == "level_zscore":
        if signal.symbol not in frame.columns:
            return None
        return _zscore(frame[signal.symbol], signal.zscore_window_days)
    if signal.transform == "change_zscore":
        if signal.symbol not in frame.columns:
            return None
        return _zscore(frame[signal.symbol].diff(signal.lookback_days), signal.zscore_window_days)
    if signal.transform == "realized_vol_zscore":
        if signal.symbol not in frame.columns:
            return None
        realized = frame[signal.symbol].pct_change().rolling(signal.lookback_days).std()
        return _zscore(realized, signal.zscore_window_days)
    raise ValueError(f"unsupported transform {signal.transform!r}")


def _zscore(series: pd.Series, window: int) -> pd.Series:
    roll = series.astype(float).rolling(window=window, min_periods=max(20, min(window, 63)))
    mu = roll.mean()
    sigma = roll.std(ddof=0)
    with np.errstate(invalid="ignore", divide="ignore"):
        z = (series - mu) / sigma
    return z.where(sigma > 0)


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
    "MarketRegimeConfig",
    "MarketRegimeMethod",
    "MarketSignalSpec",
    "compute_market_axis_scores",
    "load_market_regime_config",
    "market_symbol_specs_from_config",
]
