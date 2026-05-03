"""CLI-facing workflow: run the multi-method regime orchestrator.

Handles optional input loading (FRED macro panel, market-price panel
bundle), invokes :func:`market_helper.regimes.multi_method_service.run_multi_method`,
and persists the resulting :class:`MultiMethodRegimeSnapshot` list as JSON.

The workflow is intentionally lenient about missing inputs so operators can run
in degraded modes. The orchestrator records which methods actually voted in the
snapshot's ``source_info.manifest``.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, List, Sequence

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
from market_helper.regimes.methods.market_regime import load_market_regime_config
from market_helper.regimes.models import MultiMethodRegimeSnapshot
from market_helper.regimes.multi_method_service import (
    MultiMethodConfig,
    run_multi_method,
)


ALL_METHODS = ("macro_regime", "market_regime")


def run_multi_method_detection(
    *,
    methods: Sequence[str] = ALL_METHODS,
    macro_panel_path: str | Path | None = None,
    fred_series_config: str | Path | None = None,
    market_panel_path: str | Path | None = None,
    market_regime_config: str | Path | None = None,
    output_path: str | Path | None = None,
    latest_only: bool = False,
) -> List[MultiMethodRegimeSnapshot]:
    """Run enabled methods and optionally persist the ensemble snapshots."""
    enabled = {m.strip().lower() for m in methods if m}
    if "all" in enabled:
        enabled = set(ALL_METHODS)
    unknown = enabled.difference(ALL_METHODS)
    if unknown:
        raise ValueError(
            f"Unknown regime methods: {sorted(unknown)}. Expected one of {list(ALL_METHODS)} or 'all'."
        )
    if not enabled:
        raise ValueError("No regime methods selected.")

    cfg = MultiMethodConfig(
        enable_macro_regime="macro_regime" in enabled,
        enable_market_regime="market_regime" in enabled,
    )

    missing_inputs: list[str] = []
    macro_panel = None
    macro_specs = None
    if cfg.enable_macro_regime:
        specs_path = (
            Path(fred_series_config)
            if fred_series_config
            else Path("configs/regime_detection/fred_series.yml")
        )
        panel_path = (
            Path(macro_panel_path)
            if macro_panel_path
            else Path(FRED_DEFAULT_CACHE_DIR) / FRED_DEFAULT_PANEL_FILENAME
        )
        if specs_path.exists() and panel_path.exists():
            macro_specs = load_series_specs(specs_path)
            macro_panel = load_panel(panel_path)
        else:
            if not specs_path.exists():
                missing_inputs.append(f"macro_regime missing FRED series config: {specs_path}")
            if not panel_path.exists():
                missing_inputs.append(f"macro_regime missing macro panel: {panel_path}")

    market_panel = None
    market_config = None
    if cfg.enable_market_regime:
        market_cfg_path = (
            Path(market_regime_config)
            if market_regime_config
            else Path("configs/regime_detection/market_regime.yml")
        )
        market_panel_input = (
            Path(market_panel_path)
            if market_panel_path
            else Path(DEFAULT_MARKET_CACHE_DIR) / DEFAULT_MARKET_PANEL_FILENAME
        )
        if market_cfg_path.exists() and market_panel_input.exists():
            market_config = load_market_regime_config(market_cfg_path)
            market_panel = load_market_panel(market_panel_input)
            cfg = MultiMethodConfig(
                enable_macro_regime=cfg.enable_macro_regime,
                enable_market_regime=cfg.enable_market_regime,
                macro_regime=cfg.macro_regime,
                market_regime=market_config,
                ensemble=cfg.ensemble,
            )
        else:
            if not market_cfg_path.exists():
                missing_inputs.append(f"market_regime missing config: {market_cfg_path}")
            if not market_panel_input.exists():
                missing_inputs.append(f"market_regime missing market panel: {market_panel_input}")

    runnable_methods = [
        cfg.enable_macro_regime and macro_panel is not None and macro_specs is not None,
        cfg.enable_market_regime and market_panel is not None and market_config is not None,
    ]
    if not any(runnable_methods):
        detail = "; ".join(missing_inputs) if missing_inputs else "no method inputs were available"
        raise ValueError(f"No enabled regime methods can run: {detail}")

    source_info: dict[str, Any] = {
        "fred_config": str(fred_series_config) if fred_series_config else None,
        "macro_panel": str(macro_panel_path) if macro_panel_path else None,
        "market_config": str(market_regime_config) if market_regime_config else None,
        "market_panel": str(market_panel_path) if market_panel_path else None,
    }

    snapshots = run_multi_method(
        config=cfg,
        macro_panel=macro_panel,
        macro_specs=macro_specs,
        market_panel=market_panel,
        source_info=source_info,
    )

    if latest_only and snapshots:
        snapshots = [snapshots[-1]]

    if not snapshots:
        raise ValueError("Multi-method regime detection produced no snapshots.")

    if output_path is not None:
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            json.dumps([s.to_dict() for s in snapshots], indent=2),
            encoding="utf-8",
        )

    return snapshots


def load_multi_method_snapshots(path: str | Path) -> List[MultiMethodRegimeSnapshot]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("Expected multi-method regime snapshots JSON array")
    return [
        MultiMethodRegimeSnapshot.from_dict(dict(entry))
        for entry in payload
        if isinstance(entry, dict)
    ]


__all__ = [
    "ALL_METHODS",
    "run_multi_method_detection",
    "load_multi_method_snapshots",
]
