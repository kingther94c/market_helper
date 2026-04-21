"""CLI-facing workflow: run the multi-method regime orchestrator.

Handles optional input loading (FRED macro panel, market-stress returns/proxy
bundle), invokes :func:`market_helper.regimes.multi_method_service.run_multi_method`,
and persists the resulting :class:`MultiMethodRegimeSnapshot` list as JSON.

The workflow is intentionally lenient about missing inputs so operators can
run in degraded modes: legacy-only (no FRED sync yet) or macro-only (no
market bundle). The orchestrator records which methods actually voted in the
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
from market_helper.regimes.models import MultiMethodRegimeSnapshot
from market_helper.regimes.multi_method_service import (
    MultiMethodConfig,
    run_multi_method,
)
from market_helper.regimes.sources import load_regime_inputs


ALL_METHODS = ("macro_rules", "legacy_rulebook")


def run_multi_method_detection(
    *,
    methods: Sequence[str] = ALL_METHODS,
    macro_panel_path: str | Path | None = None,
    fred_series_config: str | Path | None = None,
    returns_path: str | Path | None = None,
    proxy_path: str | Path | None = None,
    output_path: str | Path | None = None,
    latest_only: bool = False,
) -> List[MultiMethodRegimeSnapshot]:
    """Run enabled methods and optionally persist the ensemble snapshots."""
    enabled = {m.strip().lower() for m in methods if m}
    if "all" in enabled:
        enabled = set(ALL_METHODS)

    cfg = MultiMethodConfig(
        enable_macro_rules="macro_rules" in enabled,
        enable_legacy_rulebook="legacy_rulebook" in enabled,
    )

    macro_panel = None
    macro_specs = None
    if cfg.enable_macro_rules:
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
        # If either is missing, the orchestrator logs a "skipped" status in
        # the manifest — caller can inspect to decide whether that's OK.

    market_bundle = None
    if cfg.enable_legacy_rulebook and returns_path and proxy_path:
        market_bundle = load_regime_inputs(
            proxy_path=Path(proxy_path),
            returns_path=Path(returns_path),
        )

    source_info: dict[str, Any] = {
        "fred_config": str(fred_series_config) if fred_series_config else None,
        "macro_panel": str(macro_panel_path) if macro_panel_path else None,
        "returns_path": str(returns_path) if returns_path else None,
        "proxy_path": str(proxy_path) if proxy_path else None,
    }

    snapshots = run_multi_method(
        config=cfg,
        macro_panel=macro_panel,
        macro_specs=macro_specs,
        market_bundle=market_bundle,
        source_info=source_info,
    )

    if latest_only and snapshots:
        snapshots = [snapshots[-1]]

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
