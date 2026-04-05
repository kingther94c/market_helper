"""Deterministic regime detection package."""

from .models import FactorSnapshot, IndicatorPoint, RegimeSnapshot
from .rulebook import RulebookConfig, classify_regimes

__all__ = [
    "IndicatorPoint",
    "FactorSnapshot",
    "RegimeSnapshot",
    "RulebookConfig",
    "classify_regimes",
    "detect_regimes",
    "load_service_config",
    "load_regime_snapshots",
    "load_factor_snapshots",
]


def __getattr__(name: str):
    if name in {
        "detect_regimes",
        "load_service_config",
        "load_regime_snapshots",
        "load_factor_snapshots",
    }:
        from .service import (
            detect_regimes,
            load_factor_snapshots,
            load_regime_snapshots,
            load_service_config,
        )

        exported = {
            "detect_regimes": detect_regimes,
            "load_service_config": load_service_config,
            "load_regime_snapshots": load_regime_snapshots,
            "load_factor_snapshots": load_factor_snapshots,
        }
        return exported[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
