"""CLI-facing workflow for isolated Regime Engine v2 runs."""
from __future__ import annotations

import json
from pathlib import Path
from typing import List

from market_helper.data_sources.fred.macro_panel import (
    DEFAULT_CACHE_DIR as FRED_DEFAULT_CACHE_DIR,
    DEFAULT_PANEL_FILENAME as FRED_DEFAULT_PANEL_FILENAME,
    load_panel,
    load_series_specs,
)
from market_helper.data_sources.yahoo_finance.market_panel import (
    DEFAULT_MARKET_CACHE_DIR,
    DEFAULT_MARKET_PANEL_FILENAME,
    load_market_panel,
)
from market_helper.regimes.engine_v2 import (
    FinalRegimeResult,
    LayerConfig,
    RegimeEngineConfig,
    load_regime_engine_config,
    run_regime_engine_v2,
)
from market_helper.regimes.methods.macro_regime import load_macro_regime_config
from market_helper.regimes.methods.market_regime import load_market_regime_config


def run_regime_engine_v2_detection(
    *,
    methods: list[str] | tuple[str, ...] | None = None,
    regime_engine_config: str | Path | None = None,
    macro_panel_path: str | Path | None = None,
    fred_series_config: str | Path | None = None,
    market_panel_path: str | Path | None = None,
    market_regime_config: str | Path | None = None,
    output_path: str | Path | None = None,
    latest_only: bool = False,
) -> List[FinalRegimeResult]:
    cfg = _config_for_methods(load_regime_engine_config(regime_engine_config), methods)
    macro_panel = None
    macro_specs = None
    macro_method_cfg = None
    if cfg.layers.get("macro_nowcast") and cfg.layers["macro_nowcast"].enabled:
        specs_path = Path(fred_series_config) if fred_series_config else Path("configs/regime_detection/fred_series.yml")
        panel_path = Path(macro_panel_path) if macro_panel_path else Path(FRED_DEFAULT_CACHE_DIR) / FRED_DEFAULT_PANEL_FILENAME
        if specs_path.exists() and panel_path.exists():
            macro_specs = load_series_specs(specs_path)
            macro_panel = load_panel(panel_path)
            macro_method_cfg = load_macro_regime_config(specs_path)

    market_panel = None
    market_config = None
    if (
        (cfg.layers.get("market_implied") and cfg.layers["market_implied"].enabled)
        or cfg.risk_overlay.enabled
    ):
        market_cfg_path = Path(market_regime_config) if market_regime_config else Path("configs/regime_detection/market_regime.yml")
        market_panel_input = Path(market_panel_path) if market_panel_path else Path(DEFAULT_MARKET_CACHE_DIR) / DEFAULT_MARKET_PANEL_FILENAME
        if market_cfg_path.exists() and market_panel_input.exists():
            market_config = load_market_regime_config(market_cfg_path)
            market_panel = load_market_panel(market_panel_input)

    results = run_regime_engine_v2(
        config=cfg,
        macro_panel=macro_panel,
        macro_specs=macro_specs,
        macro_method_config=macro_method_cfg,
        market_panel=market_panel,
        market_config=market_config,
    )
    if latest_only and results:
        results = [results[-1]]
    if not results:
        raise ValueError("Regime Engine v2 produced no results.")
    if output_path is not None:
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            json.dumps([result.to_dict() for result in results], indent=2),
            encoding="utf-8",
        )
    return results


def _config_for_methods(
    config: RegimeEngineConfig,
    methods: list[str] | tuple[str, ...] | None,
) -> RegimeEngineConfig:
    if not methods:
        return config
    normalized = {_normalize_method_name(method) for method in methods if str(method).strip()}
    if not normalized or "all" in normalized:
        return config
    layers: dict[str, LayerConfig] = {}
    for name, layer in config.layers.items():
        layers[name] = LayerConfig(
            enabled=name in normalized,
            available_required=layer.available_required,
            weight_growth=layer.weight_growth,
            weight_inflation=layer.weight_inflation,
            model_type=layer.model_type,
            model_artifact=layer.model_artifact,
            feature_schema=layer.feature_schema,
        )
    return RegimeEngineConfig(
        version=config.version,
        layers=layers,
        risk_overlay=config.risk_overlay,
        regime_thresholds=config.regime_thresholds,
        confidence=config.confidence,
        disagreement=config.disagreement,
    )


def _normalize_method_name(value: str) -> str:
    text = str(value).strip().lower()
    if text == "macro_regime":
        return "macro_nowcast"
    if text == "market_regime":
        return "market_implied"
    return text


__all__ = ["run_regime_engine_v2_detection"]
