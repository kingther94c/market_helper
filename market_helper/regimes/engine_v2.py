"""Regime Engine v2 coordinator.

V2 keeps growth and inflation as the only macro axes. Risk/stress is an
independent overlay that annotates the final regime label but never changes
the final growth or inflation scores.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any, Mapping, Sequence

import math

import pandas as pd
import yaml

from market_helper.data_sources.fred.macro_panel import SeriesSpec
from market_helper.regimes.axes import QuadrantSnapshot
from market_helper.regimes.methods.macro_regime import MacroRegimeConfig, MacroRegimeMethod
from market_helper.regimes.methods.market_regime import (
    MarketRegimeConfig,
    MarketRegimeMethod,
    compute_market_axis_scores,
)
from market_helper.regimes.ml import (
    ConfiguredRegimeModelSelector,
    RegimeModelSelector,
)

STATE_UP = "Up"
STATE_DOWN = "Down"
STATE_NEUTRAL = "Neutral/Mixed"
STATE_DISABLED = "Disabled"
STATE_UNAVAILABLE = "Not available"

CONFIDENCE_HIGH = "High"
CONFIDENCE_MEDIUM = "Medium"
CONFIDENCE_LOW = "Low"


@dataclass(frozen=True)
class LayerConfig:
    enabled: bool = True
    available_required: bool = False
    weight_growth: float = 0.0
    weight_inflation: float = 0.0
    model_type: str | None = None
    model_artifact: str | None = None
    feature_schema: tuple[str, ...] = ()

    def to_model_config(self) -> dict[str, Any]:
        return {
            "model_type": self.model_type,
            "model_artifact": self.model_artifact,
            "feature_schema": list(self.feature_schema),
        }


@dataclass(frozen=True)
class RiskOverlayConfig:
    enabled: bool = True
    independent: bool = True
    enter_threshold: float = 0.75
    exit_threshold: float = 0.55
    min_consecutive_days: int = 3


@dataclass(frozen=True)
class RegimeThresholds:
    growth_up: float = 0.35
    growth_down: float = -0.35
    inflation_up: float = 0.50
    inflation_down: float = -0.50


@dataclass(frozen=True)
class ConfidenceConfig:
    enabled: bool = True
    medium: float = 0.35
    high: float = 0.75
    disagreement_penalty: bool = True


@dataclass(frozen=True)
class DisagreementConfig:
    enabled: bool = True
    strong_disagreement_threshold: float = 0.70


@dataclass(frozen=True)
class RegimeEngineConfig:
    version: int = 2
    layers: Mapping[str, LayerConfig] = field(
        default_factory=lambda: {
            "macro_nowcast": LayerConfig(enabled=True, weight_growth=0.45, weight_inflation=0.40),
            "market_implied": LayerConfig(enabled=True, weight_growth=0.55, weight_inflation=0.60),
            "macro_truth_ml": LayerConfig(enabled=False, weight_growth=0.0, weight_inflation=0.0, model_type="svm"),
            "return_truth_ml": LayerConfig(enabled=False, weight_growth=0.0, weight_inflation=0.0, model_type="svm"),
        }
    )
    risk_overlay: RiskOverlayConfig = field(default_factory=RiskOverlayConfig)
    regime_thresholds: RegimeThresholds = field(default_factory=RegimeThresholds)
    confidence: ConfidenceConfig = field(default_factory=ConfidenceConfig)
    disagreement: DisagreementConfig = field(default_factory=DisagreementConfig)


@dataclass(frozen=True)
class RegimeLayerResult:
    layer_name: str
    enabled: bool
    available: bool
    growth_score: float | None = None
    inflation_score: float | None = None
    growth_state: str = STATE_UNAVAILABLE
    inflation_state: str = STATE_UNAVAILABLE
    confidence: float | None = None
    top_positive_contributors: list[tuple[str, float]] = field(default_factory=list)
    top_negative_contributors: list[tuple[str, float]] = field(default_factory=list)
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["top_positive_contributors"] = [list(item) for item in self.top_positive_contributors]
        payload["top_negative_contributors"] = [list(item) for item in self.top_negative_contributors]
        return payload


@dataclass(frozen=True)
class RiskOverlayResult:
    risk_score: float
    risk_overlay_on: bool
    risk_state: str
    liquidity_score: float | None = None
    confidence: float | None = None
    top_positive_contributors: list[tuple[str, float]] = field(default_factory=list)
    top_negative_contributors: list[tuple[str, float]] = field(default_factory=list)
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["top_positive_contributors"] = [list(item) for item in self.top_positive_contributors]
        payload["top_negative_contributors"] = [list(item) for item in self.top_negative_contributors]
        return payload


@dataclass(frozen=True)
class FinalRegimeResult:
    date: str
    final_regime: str
    base_regime: str
    confidence: str
    disagreement_flag: bool
    disagreement_summary: str
    final_growth_score: float
    final_inflation_score: float
    risk_score: float
    risk_overlay_on: bool
    macro_growth_score: float | None
    macro_inflation_score: float | None
    market_growth_score: float | None
    market_inflation_score: float | None
    ml_macro_growth_score: float | None
    ml_macro_inflation_score: float | None
    ml_return_growth_score: float | None
    ml_return_inflation_score: float | None
    layer_outputs: list[RegimeLayerResult]
    risk_output: RiskOverlayResult
    top_contributors: list[tuple[str, float]] = field(default_factory=list)
    version: str = "regime-engine-v2"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["layer_outputs"] = [item.to_dict() for item in self.layer_outputs]
        payload["risk_output"] = self.risk_output.to_dict()
        payload["top_contributors"] = [list(item) for item in self.top_contributors]
        return payload


def load_regime_engine_config(path: str | Path | None = None) -> RegimeEngineConfig:
    if path is None:
        return RegimeEngineConfig()
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    if not isinstance(raw, Mapping):
        raise ValueError("regime engine config must be a mapping")
    root = raw.get("regime_engine", raw)
    if not isinstance(root, Mapping):
        raise ValueError("regime_engine config must be a mapping")
    defaults = RegimeEngineConfig()
    layers_raw = root.get("layers", {})
    layers: dict[str, LayerConfig] = dict(defaults.layers)
    if isinstance(layers_raw, Mapping):
        for name, entry in layers_raw.items():
            if not isinstance(entry, Mapping):
                continue
            base = layers.get(str(name), LayerConfig())
            layers[str(name)] = LayerConfig(
                enabled=bool(entry.get("enabled", base.enabled)),
                available_required=bool(entry.get("available_required", base.available_required)),
                weight_growth=float(entry.get("weight_growth", base.weight_growth)),
                weight_inflation=float(entry.get("weight_inflation", base.weight_inflation)),
                model_type=entry.get("model_type", base.model_type),
                model_artifact=entry.get("model_artifact", base.model_artifact),
                feature_schema=tuple(str(item) for item in entry.get("feature_schema", base.feature_schema) or ()),
            )
    risk_raw = root.get("risk_overlay", {})
    risk = defaults.risk_overlay
    if isinstance(risk_raw, Mapping):
        risk = RiskOverlayConfig(
            enabled=bool(risk_raw.get("enabled", risk.enabled)),
            independent=bool(risk_raw.get("independent", risk.independent)),
            enter_threshold=float(risk_raw.get("enter_threshold", risk.enter_threshold)),
            exit_threshold=float(risk_raw.get("exit_threshold", risk.exit_threshold)),
            min_consecutive_days=int(risk_raw.get("min_consecutive_days", risk.min_consecutive_days)),
        )
    thresholds_raw = root.get("regime_thresholds", {})
    thresholds = defaults.regime_thresholds
    if isinstance(thresholds_raw, Mapping):
        thresholds = RegimeThresholds(
            growth_up=float(thresholds_raw.get("growth_up", thresholds.growth_up)),
            growth_down=float(thresholds_raw.get("growth_down", thresholds.growth_down)),
            inflation_up=float(thresholds_raw.get("inflation_up", thresholds.inflation_up)),
            inflation_down=float(thresholds_raw.get("inflation_down", thresholds.inflation_down)),
        )
    confidence_raw = root.get("confidence", {})
    confidence = defaults.confidence
    if isinstance(confidence_raw, Mapping):
        score_thresholds = confidence_raw.get("score_strength_thresholds", {})
        score_thresholds = score_thresholds if isinstance(score_thresholds, Mapping) else {}
        confidence = ConfidenceConfig(
            enabled=bool(confidence_raw.get("enabled", confidence.enabled)),
            medium=float(score_thresholds.get("medium", confidence.medium)),
            high=float(score_thresholds.get("high", confidence.high)),
            disagreement_penalty=bool(confidence_raw.get("disagreement_penalty", confidence.disagreement_penalty)),
        )
    disagreement_raw = root.get("disagreement", {})
    disagreement = defaults.disagreement
    if isinstance(disagreement_raw, Mapping):
        disagreement = DisagreementConfig(
            enabled=bool(disagreement_raw.get("enabled", disagreement.enabled)),
            strong_disagreement_threshold=float(
                disagreement_raw.get(
                    "strong_disagreement_threshold",
                    disagreement.strong_disagreement_threshold,
                )
            ),
        )
    return RegimeEngineConfig(
        version=int(root.get("version", defaults.version)),
        layers=layers,
        risk_overlay=risk,
        regime_thresholds=thresholds,
        confidence=confidence,
        disagreement=disagreement,
    )


def run_regime_engine_v2(
    *,
    config: RegimeEngineConfig | None = None,
    macro_panel: pd.DataFrame | None = None,
    macro_specs: Sequence[SeriesSpec] | None = None,
    macro_method_config: MacroRegimeConfig | None = None,
    market_panel: pd.DataFrame | None = None,
    market_config: MarketRegimeConfig | None = None,
    model_selector: RegimeModelSelector | None = None,
) -> list[FinalRegimeResult]:
    cfg = config or RegimeEngineConfig()
    selector = model_selector or ConfiguredRegimeModelSelector()
    layer_series: dict[str, dict[str, RegimeLayerResult]] = {}
    layer_status: dict[str, RegimeLayerResult] = {}

    macro_cfg = cfg.layers.get("macro_nowcast", LayerConfig())
    if macro_cfg.enabled:
        if macro_panel is None or macro_specs is None:
            layer_status["macro_nowcast"] = _unavailable_layer("macro_nowcast", "macro_panel or macro_specs not provided")
        else:
            macro_method_cfg = macro_method_config or MacroRegimeConfig()
            results = MacroRegimeMethod(list(macro_specs), config=macro_method_cfg).classify(macro_panel)
            layer_series["macro_nowcast"] = {
                result.as_of: _layer_from_quadrant("macro_nowcast", result.quadrant, cfg)
                for result in results
            }
    else:
        layer_status["macro_nowcast"] = _disabled_layer("macro_nowcast")

    market_cfg = cfg.layers.get("market_implied", LayerConfig())
    market_config_with_engine_risk = (
        _market_config_with_engine_risk(market_config, cfg) if market_config else None
    )
    if market_cfg.enabled:
        if market_panel is None or market_config_with_engine_risk is None:
            layer_status["market_implied"] = _unavailable_layer("market_implied", "market_panel or market_config not provided")
        else:
            results = MarketRegimeMethod(market_config_with_engine_risk).classify(market_panel)
            layer_series["market_implied"] = {
                result.as_of: _layer_from_quadrant("market_implied", result.quadrant, cfg)
                for result in results
            }
    else:
        layer_status["market_implied"] = _disabled_layer("market_implied")

    feature_names = _available_feature_names(macro_panel, market_panel)
    for layer_name in ("macro_truth_ml", "return_truth_ml"):
        layer_cfg = cfg.layers.get(layer_name, LayerConfig(enabled=False, model_type="svm"))
        if not layer_cfg.enabled:
            layer_status[layer_name] = _disabled_layer(layer_name)
            continue
        selection = selector.select_model(
            layer_name=layer_name,
            config=layer_cfg.to_model_config(),
            available_features=feature_names,
        )
        if not selection.available:
            layer_status[layer_name] = _unavailable_layer(
                layer_name,
                selection.unavailable_reason or "model unavailable",
            )
            continue
        layer_status[layer_name] = _unavailable_layer(
            layer_name,
            "model selected but inference is not implemented in this pass",
            diagnostics={"model": selection.selected.diagnostics if selection.selected else {}},
        )

    risk_by_date = _risk_outputs_by_date(
        market_panel=market_panel,
        market_config=market_config_with_engine_risk,
        config=cfg,
    )

    dates = sorted({date for by_date in layer_series.values() for date in by_date})
    out: list[FinalRegimeResult] = []
    for date in dates:
        layer_outputs = [
            layer_series.get(layer_name, {}).get(date)
            or layer_status.get(layer_name)
            or _unavailable_layer(layer_name, "no result for date")
            for layer_name in cfg.layers.keys()
        ]
        final_growth = _weighted_axis(layer_outputs, cfg, axis="growth")
        final_inflation = _weighted_axis(layer_outputs, cfg, axis="inflation")
        risk_output = risk_by_date.get(date) or RiskOverlayResult(
            risk_score=0.0,
            risk_overlay_on=False,
            risk_state="Disabled" if not cfg.risk_overlay.enabled else STATE_UNAVAILABLE,
            diagnostics={"reason": "risk inputs not available"},
        )
        base_regime = _base_regime(final_growth, final_inflation, cfg)
        final_regime = (
            f"{base_regime} + Stress Overlay"
            if risk_output.risk_overlay_on
            else base_regime
        )
        disagreement_flag, disagreement_summary = _disagreement(layer_outputs, cfg)
        confidence = _confidence(final_growth, final_inflation, disagreement_flag, cfg)
        out.append(
            FinalRegimeResult(
                date=date,
                final_regime=final_regime,
                base_regime=base_regime,
                confidence=confidence,
                disagreement_flag=disagreement_flag,
                disagreement_summary=disagreement_summary,
                final_growth_score=final_growth,
                final_inflation_score=final_inflation,
                risk_score=risk_output.risk_score,
                risk_overlay_on=risk_output.risk_overlay_on,
                macro_growth_score=_score_for(layer_outputs, "macro_nowcast", "growth"),
                macro_inflation_score=_score_for(layer_outputs, "macro_nowcast", "inflation"),
                market_growth_score=_score_for(layer_outputs, "market_implied", "growth"),
                market_inflation_score=_score_for(layer_outputs, "market_implied", "inflation"),
                ml_macro_growth_score=_score_for(layer_outputs, "macro_truth_ml", "growth"),
                ml_macro_inflation_score=_score_for(layer_outputs, "macro_truth_ml", "inflation"),
                ml_return_growth_score=_score_for(layer_outputs, "return_truth_ml", "growth"),
                ml_return_inflation_score=_score_for(layer_outputs, "return_truth_ml", "inflation"),
                layer_outputs=layer_outputs,
                risk_output=risk_output,
                top_contributors=_top_contributors(layer_outputs),
            )
        )
    return out


def _market_config_with_engine_risk(
    market_config: MarketRegimeConfig,
    engine_config: RegimeEngineConfig,
) -> MarketRegimeConfig:
    """Override the market-config risk thresholds with the engine-level values.

    Risk overlay thresholds live in ``regime_engine.yml`` (the single source of
    truth); this keeps the market-method classifier's crisis flag aligned with
    the engine config without duplicating values in ``market_regime.yml``.
    """
    overlay = engine_config.risk_overlay
    return replace(
        market_config,
        risk_enter_threshold=float(overlay.enter_threshold),
        risk_exit_threshold=float(overlay.exit_threshold),
        risk_min_consecutive_days=int(overlay.min_consecutive_days),
    )


def _layer_from_quadrant(
    layer_name: str,
    snapshot: QuadrantSnapshot,
    cfg: RegimeEngineConfig,
) -> RegimeLayerResult:
    drivers = dict(snapshot.axes.growth_drivers) | dict(snapshot.axes.inflation_drivers)
    positives, negatives = _split_contributors(drivers)
    return RegimeLayerResult(
        layer_name=layer_name,
        enabled=True,
        available=True,
        growth_score=float(snapshot.axes.growth_score),
        inflation_score=float(snapshot.axes.inflation_score),
        growth_state=_axis_state(float(snapshot.axes.growth_score), "growth", cfg),
        inflation_state=_axis_state(float(snapshot.axes.inflation_score), "inflation", cfg),
        confidence=float(snapshot.axes.confidence),
        top_positive_contributors=positives,
        top_negative_contributors=negatives,
        diagnostics=dict(snapshot.diagnostics),
    )


def _risk_outputs_by_date(
    *,
    market_panel: pd.DataFrame | None,
    market_config: MarketRegimeConfig | None,
    config: RegimeEngineConfig,
) -> dict[str, RiskOverlayResult]:
    if not config.risk_overlay.enabled or market_panel is None or market_config is None:
        return {}
    scores = compute_market_axis_scores(market_panel, market_config)
    if scores.empty or "risk_score" not in scores.columns:
        return {}
    risks = MarketRegimeMethod(market_config).classify(market_panel)
    by_date: dict[str, RiskOverlayResult] = {}
    for result in risks:
        detail = result.quadrant.diagnostics
        risk_score = _safe_float(detail.get("risk_score"))
        drivers = dict(detail.get("risk_drivers", {}))
        positives, negatives = _split_contributors(drivers)
        on = bool(result.quadrant.crisis_flag)
        by_date[result.as_of] = RiskOverlayResult(
            risk_score=risk_score,
            risk_overlay_on=on,
            risk_state="Stress" if on else ("Risk On" if risk_score < 0 else "Neutral"),
            confidence=None,
            top_positive_contributors=positives,
            top_negative_contributors=negatives,
            diagnostics={
                "risk_regime": detail.get("risk_regime"),
                "independent": bool(config.risk_overlay.independent),
            },
        )
    return by_date


def _axis_state(score: float | None, axis: str, cfg: RegimeEngineConfig) -> str:
    if score is None:
        return STATE_UNAVAILABLE
    thresholds = cfg.regime_thresholds
    if axis == "growth":
        if score >= thresholds.growth_up:
            return STATE_UP
        if score <= thresholds.growth_down:
            return STATE_DOWN
    else:
        if score >= thresholds.inflation_up:
            return STATE_UP
        if score <= thresholds.inflation_down:
            return STATE_DOWN
    return STATE_NEUTRAL


def _base_regime(growth: float, inflation: float, cfg: RegimeEngineConfig) -> str:
    growth_state = _axis_state(growth, "growth", cfg)
    inflation_state = _axis_state(inflation, "inflation", cfg)
    if growth_state == STATE_UP and inflation_state in {STATE_DOWN, STATE_NEUTRAL}:
        return "Goldilocks / Expansion"
    if growth_state == STATE_UP and inflation_state == STATE_UP:
        return "Reflation"
    if growth_state == STATE_DOWN and inflation_state == STATE_UP:
        return "Stagflation-like"
    if growth_state == STATE_DOWN and inflation_state == STATE_DOWN:
        return "Slowdown / Deflationary Slowdown"
    return f"{growth_state} Growth / {inflation_state} Inflation"


def _weighted_axis(
    layers: Sequence[RegimeLayerResult],
    cfg: RegimeEngineConfig,
    *,
    axis: str,
) -> float:
    total = 0.0
    weight_sum = 0.0
    for layer in layers:
        layer_cfg = cfg.layers.get(layer.layer_name, LayerConfig())
        weight = layer_cfg.weight_growth if axis == "growth" else layer_cfg.weight_inflation
        score = layer.growth_score if axis == "growth" else layer.inflation_score
        if not layer.enabled or not layer.available or weight <= 0 or score is None:
            continue
        total += float(score) * float(weight)
        weight_sum += float(weight)
    return float(total / weight_sum) if weight_sum else 0.0


def _disagreement(
    layers: Sequence[RegimeLayerResult],
    cfg: RegimeEngineConfig,
) -> tuple[bool, str]:
    if not cfg.disagreement.enabled:
        return False, ""
    available = [layer for layer in layers if layer.enabled and layer.available]
    flag = _axis_has_opposing_layers(available, "growth", cfg) or _axis_has_opposing_layers(
        available,
        "inflation",
        cfg,
    )
    if not flag:
        return False, ""
    labels = ", ".join(f"{layer.layer_name}: {layer.growth_state}/{layer.inflation_state}" for layer in available)
    return True, f"Layer disagreement: {labels}"


def _axis_has_opposing_layers(
    layers: Sequence[RegimeLayerResult],
    axis: str,
    cfg: RegimeEngineConfig,
) -> bool:
    scores = [
        layer.growth_score if axis == "growth" else layer.inflation_score
        for layer in layers
    ]
    clean = [float(score) for score in scores if score is not None]
    if len(clean) < 2:
        return False
    thresholds = cfg.regime_thresholds
    down = thresholds.growth_down if axis == "growth" else thresholds.inflation_down
    up = thresholds.growth_up if axis == "growth" else thresholds.inflation_up
    return (
        min(clean) <= down
        and max(clean) >= up
        and (max(clean) - min(clean)) >= cfg.disagreement.strong_disagreement_threshold
    )


def _confidence(
    growth: float,
    inflation: float,
    disagreement: bool,
    cfg: RegimeEngineConfig,
) -> str:
    if not cfg.confidence.enabled:
        return CONFIDENCE_MEDIUM
    strength = min(abs(growth), abs(inflation))
    if strength >= cfg.confidence.high and not disagreement:
        return CONFIDENCE_HIGH
    if strength >= cfg.confidence.medium and not (disagreement and cfg.confidence.disagreement_penalty):
        return CONFIDENCE_MEDIUM
    if strength >= cfg.confidence.high and disagreement:
        return CONFIDENCE_MEDIUM
    return CONFIDENCE_LOW


def _disabled_layer(name: str) -> RegimeLayerResult:
    return RegimeLayerResult(
        layer_name=name,
        enabled=False,
        available=False,
        growth_state=STATE_DISABLED,
        inflation_state=STATE_DISABLED,
        diagnostics={"status": "disabled"},
    )


def _unavailable_layer(
    name: str,
    reason: str,
    *,
    diagnostics: Mapping[str, Any] | None = None,
) -> RegimeLayerResult:
    detail = {"status": "not_available", "reason": reason}
    if diagnostics:
        detail.update(dict(diagnostics))
    return RegimeLayerResult(
        layer_name=name,
        enabled=True,
        available=False,
        growth_state=STATE_UNAVAILABLE,
        inflation_state=STATE_UNAVAILABLE,
        diagnostics=detail,
    )


def _split_contributors(values: Mapping[str, Any]) -> tuple[list[tuple[str, float]], list[tuple[str, float]]]:
    clean = [(str(key), _safe_float(value)) for key, value in values.items()]
    positives = sorted((item for item in clean if item[1] > 0), key=lambda item: item[1], reverse=True)[:5]
    negatives = sorted((item for item in clean if item[1] < 0), key=lambda item: item[1])[:5]
    return positives, negatives


def _top_contributors(layers: Sequence[RegimeLayerResult]) -> list[tuple[str, float]]:
    values: list[tuple[str, float]] = []
    for layer in layers:
        values.extend((f"{layer.layer_name}:{name}", value) for name, value in layer.top_positive_contributors)
        values.extend((f"{layer.layer_name}:{name}", value) for name, value in layer.top_negative_contributors)
    return sorted(values, key=lambda item: abs(item[1]), reverse=True)[:10]


def _score_for(layers: Sequence[RegimeLayerResult], layer_name: str, axis: str) -> float | None:
    for layer in layers:
        if layer.layer_name == layer_name and layer.available:
            return layer.growth_score if axis == "growth" else layer.inflation_score
    return None


def _available_feature_names(
    macro_panel: pd.DataFrame | None,
    market_panel: pd.DataFrame | None,
) -> tuple[str, ...]:
    names: set[str] = set()
    if macro_panel is not None:
        names.update(str(col) for col in macro_panel.columns if col != "date")
    if market_panel is not None:
        names.update(str(col) for col in market_panel.columns if col != "date")
    return tuple(sorted(names))


def _safe_float(value: Any) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return 0.0
    if math.isnan(result):
        return 0.0
    return result


__all__ = [
    "CONFIDENCE_HIGH",
    "CONFIDENCE_LOW",
    "CONFIDENCE_MEDIUM",
    "ConfidenceConfig",
    "DisagreementConfig",
    "FinalRegimeResult",
    "LayerConfig",
    "RegimeEngineConfig",
    "RegimeLayerResult",
    "RegimeThresholds",
    "RiskOverlayConfig",
    "RiskOverlayResult",
    "load_regime_engine_config",
    "run_regime_engine_v2",
]
