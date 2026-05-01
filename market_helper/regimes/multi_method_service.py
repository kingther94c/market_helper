"""Orchestrator for the multi-method regime pipeline.

Runs each registered method over its native inputs, aligns results by date,
calls the ensemble voter, and emits one :class:`MultiMethodRegimeSnapshot` per
overlapping date.

Methods that are configured but fail to produce output (e.g. FRED panel
missing) are skipped with their error recorded in ``source_info`` so the
orchestrator stays best-effort — callers can inspect the manifest to see
which methods actually voted.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Sequence

import pandas as pd

from market_helper.regimes.axes import QuadrantSnapshot
from market_helper.regimes.ensemble import EnsembleConfig, aggregate
from market_helper.regimes.methods.base import MethodResult
from market_helper.regimes.methods.macro_regime import (
    MacroRegimeConfig,
    MacroRegimeMethod,
)
from market_helper.regimes.methods.market_regime import (
    MarketRegimeConfig,
    MarketRegimeMethod,
)
from market_helper.regimes.models import MultiMethodRegimeSnapshot
from market_helper.data_sources.fred.macro_panel import SeriesSpec


@dataclass(frozen=True)
class MultiMethodConfig:
    enable_macro_regime: bool = True
    enable_market_regime: bool = True
    macro_regime: MacroRegimeConfig = field(default_factory=MacroRegimeConfig)
    market_regime: MarketRegimeConfig | None = None
    ensemble: EnsembleConfig = field(default_factory=EnsembleConfig)


def run_multi_method(
    *,
    config: MultiMethodConfig | None = None,
    macro_panel: pd.DataFrame | None = None,
    macro_specs: Sequence[SeriesSpec] | None = None,
    market_panel: pd.DataFrame | None = None,
    source_info: Mapping[str, Any] | None = None,
) -> List[MultiMethodRegimeSnapshot]:
    """Run enabled methods and ensemble-aggregate into dated snapshots.

    Parameters are optional so a caller can run just one method (e.g. only
    legacy when the FRED panel is unavailable). The ensemble still works with
    a single method — it just emits that method's verdict verbatim.
    """
    cfg = config or MultiMethodConfig()
    per_method: Dict[str, List[MethodResult]] = {}
    manifest: Dict[str, Any] = {"methods": {}}

    if cfg.enable_macro_regime:
        if macro_panel is None or macro_specs is None:
            manifest["methods"]["macro_regime"] = {
                "status": "skipped",
                "reason": "macro_panel or macro_specs not provided",
            }
        else:
            method = MacroRegimeMethod(list(macro_specs), config=cfg.macro_regime)
            results = method.classify(macro_panel)
            per_method[method.name] = results
            manifest["methods"]["macro_regime"] = {
                "status": "ok",
                "n_results": len(results),
            }

    if cfg.enable_market_regime:
        if market_panel is None or cfg.market_regime is None:
            manifest["methods"]["market_regime"] = {
                "status": "skipped",
                "reason": "market_panel or market config not provided",
            }
        else:
            method = MarketRegimeMethod(cfg.market_regime)
            results = method.classify(market_panel)
            per_method[method.name] = results
            manifest["methods"]["market_regime"] = {
                "status": "ok",
                "n_results": len(results),
            }

    if not per_method:
        return []

    ensemble_snapshots = aggregate(per_method, config=cfg.ensemble)
    if not ensemble_snapshots:
        return []

    by_date_methods = _index_per_method_by_date(per_method)
    base_source = dict(source_info or {})
    base_source["manifest"] = manifest

    out: List[MultiMethodRegimeSnapshot] = []
    for snap in ensemble_snapshots:
        methods_on_date = by_date_methods.get(snap.as_of, {})
        out.append(
            MultiMethodRegimeSnapshot(
                as_of=snap.as_of,
                per_method=dict(methods_on_date),
                ensemble=snap,
                source_info=dict(base_source),
            )
        )
    return out


def _index_per_method_by_date(
    per_method: Mapping[str, Sequence[MethodResult]],
) -> Dict[str, Dict[str, MethodResult]]:
    indexed: Dict[str, Dict[str, MethodResult]] = {}
    for name, results in per_method.items():
        for result in results:
            indexed.setdefault(result.as_of, {})[name] = result
    return indexed


def snapshots_to_json(
    snapshots: Sequence[MultiMethodRegimeSnapshot],
) -> List[dict]:
    return [snap.to_dict() for snap in snapshots]


def snapshots_from_json(payload: Sequence[Mapping[str, Any]]) -> List[MultiMethodRegimeSnapshot]:
    return [MultiMethodRegimeSnapshot.from_dict(dict(entry)) for entry in payload]


__all__ = [
    "MultiMethodConfig",
    "run_multi_method",
    "snapshots_to_json",
    "snapshots_from_json",
]
