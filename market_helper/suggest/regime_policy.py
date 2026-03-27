from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import yaml

from market_helper.regimes.models import RegimeSnapshot
from market_helper.regimes.taxonomy import (
    REGIME_DEFLATIONARY_CRISIS,
    REGIME_DEFLATIONARY_SLOWDOWN,
    REGIME_GOLDILOCKS,
    REGIME_INFLATIONARY_CRISIS,
    REGIME_RECOVERY_PIVOT,
    REGIME_REFLATION_TIGHTENING,
    REGIME_STAGFLATION,
)


@dataclass(frozen=True)
class RegimePolicyDecision:
    as_of: str
    regime: str
    vol_multiplier: float
    asset_class_targets: dict[str, float]
    notes: str = ""
    corr_overrides: dict[str, float] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


DEFAULT_POLICY: dict[str, dict[str, Any]] = {
    REGIME_DEFLATIONARY_CRISIS: {
        "vol_multiplier": 0.55,
        "asset_class_targets": {"EQ": 0.55, "FI": 0.30, "GOLD": 0.08, "CM": 0.02, "CASH": 0.05},
        "notes": "Reduce gross risk, favor duration/cash ballast.",
    },
    REGIME_INFLATIONARY_CRISIS: {
        "vol_multiplier": 0.60,
        "asset_class_targets": {"EQ": 0.58, "FI": 0.15, "GOLD": 0.15, "CM": 0.08, "CASH": 0.04},
        "notes": "Cap duration risk and increase inflation hedges.",
    },
    REGIME_RECOVERY_PIVOT: {
        "vol_multiplier": 0.90,
        "asset_class_targets": {"EQ": 0.72, "FI": 0.18, "GOLD": 0.05, "CM": 0.03, "CASH": 0.02},
        "notes": "Step back toward strategic risk after stress decay.",
    },
    REGIME_GOLDILOCKS: {
        "vol_multiplier": 1.05,
        "asset_class_targets": {"EQ": 0.80, "FI": 0.12, "GOLD": 0.03, "CM": 0.03, "CASH": 0.02},
        "notes": "Allow moderate risk-up tilt in calm expansion.",
    },
    REGIME_REFLATION_TIGHTENING: {
        "vol_multiplier": 0.95,
        "asset_class_targets": {"EQ": 0.76, "FI": 0.10, "GOLD": 0.06, "CM": 0.05, "CASH": 0.03},
        "notes": "Keep equity tilt but avoid excessive duration.",
    },
    REGIME_DEFLATIONARY_SLOWDOWN: {
        "vol_multiplier": 0.80,
        "asset_class_targets": {"EQ": 0.66, "FI": 0.22, "GOLD": 0.06, "CM": 0.02, "CASH": 0.04},
        "notes": "Lower beta, preserve defensive ballast.",
    },
    REGIME_STAGFLATION: {
        "vol_multiplier": 0.70,
        "asset_class_targets": {"EQ": 0.62, "FI": 0.12, "GOLD": 0.14, "CM": 0.08, "CASH": 0.04},
        "notes": "Bias toward real assets and keep risk controlled.",
    },
}


def load_regime_policy(path: str | Path | None = None) -> dict[str, dict[str, Any]]:
    """Load optional YAML policy overrides keyed by regime label."""
    if path is None:
        return DEFAULT_POLICY
    payload = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        raise ValueError("Policy config must be a mapping")
    if "policy" in payload and isinstance(payload["policy"], dict):
        payload = dict(payload["policy"])
    merged = dict(DEFAULT_POLICY)
    for regime, config in payload.items():
        if isinstance(config, dict):
            merged[str(regime)] = dict(config)
    return merged


def resolve_policy(
    snapshot: RegimeSnapshot,
    policy: dict[str, dict[str, Any]] | None = None,
) -> RegimePolicyDecision:
    """Map regime snapshot to suggested non-execution risk/tilt policy."""
    active = policy or DEFAULT_POLICY
    selected = active.get(snapshot.regime, active[REGIME_DEFLATIONARY_SLOWDOWN])
    return RegimePolicyDecision(
        as_of=snapshot.as_of,
        regime=snapshot.regime,
        vol_multiplier=float(selected.get("vol_multiplier", 1.0)),
        asset_class_targets={
            str(k): float(v) for k, v in dict(selected.get("asset_class_targets", {})).items()
        },
        notes=str(selected.get("notes", "")),
        corr_overrides=(
            {str(k): float(v) for k, v in dict(selected.get("corr_overrides", {})).items()}
            if isinstance(selected.get("corr_overrides"), dict)
            else None
        ),
    )
