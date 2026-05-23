"""CLI-facing workflow for isolated Regime Engine v2 runs."""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import List

import pandas as pd

from market_helper.data_sources.fred.macro_panel import (
    DEFAULT_CACHE_DIR as FRED_DEFAULT_CACHE_DIR,
    DEFAULT_PANEL_FILENAME as FRED_DEFAULT_PANEL_FILENAME,
    load_concept_specs,
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


logger = logging.getLogger(__name__)


# Pre-2025 market panel snapshot — checked into git so a fresh checkout can
# run the regime engine without first round-tripping ~40 years of Yahoo
# history. Live cache (gitignored) appends post-2024 data on top.
HISTORICAL_MARKET_PANEL_PATH = Path(
    "data/external/regime_detection/historical/market_panel_to_2024.feather"
)


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
    auto_sync: bool = True,
) -> List[FinalRegimeResult]:
    cfg = _config_for_methods(load_regime_engine_config(regime_engine_config), methods)
    macro_panel = None
    macro_specs = None
    macro_concepts = None
    macro_method_cfg = None
    if cfg.layers.get("macro_nowcast") and cfg.layers["macro_nowcast"].enabled:
        specs_path = Path(fred_series_config) if fred_series_config else Path("configs/regime_detection/fred_series.yml")
        panel_path = Path(macro_panel_path) if macro_panel_path else Path(FRED_DEFAULT_CACHE_DIR) / FRED_DEFAULT_PANEL_FILENAME
        if specs_path.exists():
            macro_panel = _load_or_sync_macro_panel(
                panel_path=panel_path,
                series_config_path=specs_path,
                auto_sync=auto_sync,
            )
            if macro_panel is not None:
                macro_specs = load_series_specs(specs_path)
                macro_concepts = load_concept_specs(specs_path)
                macro_method_cfg = load_macro_regime_config(specs_path)
            else:
                logger.warning(
                    "Macro panel unavailable and FRED_API_KEY not configured — "
                    "disabling macro_nowcast layer for this run. Export "
                    "FRED_API_KEY in the process env, or add it to "
                    "<MARKET_HELPER_GDRIVE_ROOT>/local.env (preferred for "
                    "multi-machine sync) or configs/portfolio_monitor/local.env. "
                    "Activation runbook: docs/architecture/devplans/"
                    "regime_engine.md"
                )

    market_panel = None
    market_config = None
    if (
        (cfg.layers.get("market_implied") and cfg.layers["market_implied"].enabled)
        or cfg.risk_overlay.enabled
    ):
        market_cfg_path = Path(market_regime_config) if market_regime_config else Path("configs/regime_detection/market_regime.yml")
        market_panel_input = Path(market_panel_path) if market_panel_path else Path(DEFAULT_MARKET_CACHE_DIR) / DEFAULT_MARKET_PANEL_FILENAME
        if market_cfg_path.exists():
            market_panel = _load_or_sync_market_panel(
                live_cache_path=market_panel_input,
                market_config_path=market_cfg_path,
                auto_sync=auto_sync,
            )
            if market_panel is not None:
                market_config = load_market_regime_config(market_cfg_path)

    results = run_regime_engine_v2(
        config=cfg,
        macro_panel=macro_panel,
        macro_specs=macro_specs,
        macro_concepts=macro_concepts,
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


def _load_or_sync_market_panel(
    *,
    live_cache_path: Path,
    market_config_path: Path,
    auto_sync: bool,
) -> pd.DataFrame | None:
    """Load the market panel, auto-syncing from Yahoo if the live cache is absent.

    Always merges the checked-in historical baseline (pre-2025) with the live
    cache when both exist, so an incremental sync ("2mo" lookback) is enough
    to extend coverage to today without re-downloading 40 years of history.
    Live cache wins on overlapping dates.
    """
    if not live_cache_path.exists() and auto_sync:
        from market_helper.workflows.sync_market_regime_panel import run_market_regime_sync

        logger.info(
            "Market panel cache missing at %s — running incremental Yahoo sync.",
            live_cache_path,
        )
        run_market_regime_sync(
            config_path=market_config_path,
            cache_dir=live_cache_path.parent,
        )

    live_frame = (
        load_market_panel(live_cache_path) if live_cache_path.exists() else pd.DataFrame()
    )
    historical_frame = (
        load_market_panel(HISTORICAL_MARKET_PANEL_PATH)
        if HISTORICAL_MARKET_PANEL_PATH.exists()
        else pd.DataFrame()
    )

    if live_frame.empty and historical_frame.empty:
        return None
    if historical_frame.empty:
        return live_frame
    if live_frame.empty:
        return historical_frame

    merged = pd.concat([historical_frame, live_frame], ignore_index=True)
    merged = (
        merged.drop_duplicates(subset=["date"], keep="last")
        .sort_values("date")
        .reset_index(drop=True)
    )
    return merged


def _load_or_sync_macro_panel(
    *,
    panel_path: Path,
    series_config_path: Path,
    auto_sync: bool,
) -> pd.DataFrame | None:
    """Load the FRED macro panel, auto-syncing when both cache and key are present.

    Returns None when the panel is absent AND no FRED_API_KEY is available —
    the caller is expected to disable the macro layer and emit a warning in
    that case rather than failing the whole regime run.
    """
    if panel_path.exists():
        return load_panel(panel_path)
    if not auto_sync:
        return None
    if not _have_fred_api_key():
        return None
    from market_helper.workflows.sync_fred_macro_panel import run_fred_macro_sync

    logger.info(
        "FRED panel cache missing at %s — running full sync (may take ~1-2 minutes).",
        panel_path,
    )
    run_fred_macro_sync(
        config_path=series_config_path,
        cache_dir=panel_path.parent,
    )
    return load_panel(panel_path) if panel_path.exists() else None


def _have_fred_api_key() -> bool:
    from market_helper.config.local_env import read_local_config_value

    if os.environ.get("FRED_API_KEY", "").strip():
        return True
    return bool(read_local_config_value("FRED_API_KEY"))


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


__all__ = ["run_regime_engine_v2_detection", "HISTORICAL_MARKET_PANEL_PATH"]
