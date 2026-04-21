"""4-quadrant policy table + crisis overlay for the 2D regime framework.

Pairs with :mod:`market_helper.regimes.axes`. Uses the same
:class:`RegimePolicyDecision` dataclass as the legacy 7-regime policy so
downstream renderers only need to understand one output type.

When a :class:`QuadrantSnapshot` arrives with ``crisis_flag=True``, a crisis
overlay is applied on top of the base quadrant policy:

  - ``vol_multiplier *= (1 - overlay.vol_multiplier_reduction * intensity)``
  - A fraction ``overlay.equity_shift_pct * intensity`` of EQ weight is
    redistributed to CASH, GOLD, and FI per ``overlay.shift_allocation``.

This keeps the quadrant call and the risk-off dial orthogonal.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import yaml

from market_helper.regimes.axes import (
    QUADRANT_DEFLATIONARY_SLOWDOWN,
    QUADRANT_GOLDILOCKS,
    QUADRANT_LABELS,
    QUADRANT_REFLATION,
    QUADRANT_STAGFLATION,
    QuadrantSnapshot,
)
from market_helper.suggest.regime_policy import RegimePolicyDecision


DEFAULT_QUADRANT_POLICY: dict[str, dict[str, Any]] = {
    QUADRANT_GOLDILOCKS: {
        "vol_multiplier": 1.05,
        "asset_class_targets": {"EQ": 0.80, "FI": 0.12, "GOLD": 0.03, "CM": 0.03, "CASH": 0.02},
        "notes": "Goldilocks — allow a modest risk-up tilt.",
    },
    QUADRANT_REFLATION: {
        "vol_multiplier": 0.95,
        "asset_class_targets": {"EQ": 0.76, "FI": 0.10, "GOLD": 0.06, "CM": 0.05, "CASH": 0.03},
        "notes": "Reflation — stay with equities but cap duration.",
    },
    QUADRANT_STAGFLATION: {
        "vol_multiplier": 0.70,
        "asset_class_targets": {"EQ": 0.62, "FI": 0.12, "GOLD": 0.14, "CM": 0.08, "CASH": 0.04},
        "notes": "Stagflation — bias to real assets, keep risk controlled.",
    },
    QUADRANT_DEFLATIONARY_SLOWDOWN: {
        "vol_multiplier": 0.80,
        "asset_class_targets": {"EQ": 0.66, "FI": 0.22, "GOLD": 0.06, "CM": 0.02, "CASH": 0.04},
        "notes": "Deflationary slowdown — lower beta, preserve defensive ballast.",
    },
}


@dataclass(frozen=True)
class CrisisOverlay:
    vol_multiplier_reduction: float = 0.35
    equity_shift_pct: float = 0.10
    shift_allocation: tuple[tuple[str, float], ...] = (
        ("CASH", 0.50),
        ("GOLD", 0.30),
        ("FI", 0.20),
    )


DEFAULT_CRISIS_OVERLAY = CrisisOverlay()


def load_quadrant_policy(path: str | Path | None = None) -> dict[str, dict[str, Any]]:
    """Merge optional YAML overrides into :data:`DEFAULT_QUADRANT_POLICY`.

    YAML shape::

        policy:
          Goldilocks: { vol_multiplier: 1.1, asset_class_targets: {...} }
        crisis_overlay: { vol_multiplier_reduction: 0.4, ... }

    Returns only the ``policy`` mapping; use :func:`load_crisis_overlay` for the
    overlay section.
    """
    if path is None:
        return dict(DEFAULT_QUADRANT_POLICY)
    payload = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        raise ValueError("Quadrant policy config must be a mapping")
    policy_section = payload.get("policy", payload)
    if not isinstance(policy_section, dict):
        raise ValueError("'policy' section must be a mapping")
    merged = dict(DEFAULT_QUADRANT_POLICY)
    for key, entry in policy_section.items():
        if isinstance(entry, dict):
            merged[str(key)] = dict(entry)
    return merged


def load_crisis_overlay(path: str | Path | None = None) -> CrisisOverlay:
    if path is None:
        return DEFAULT_CRISIS_OVERLAY
    payload = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        return DEFAULT_CRISIS_OVERLAY
    raw = payload.get("crisis_overlay")
    if not isinstance(raw, dict):
        return DEFAULT_CRISIS_OVERLAY
    alloc_raw = raw.get("shift_allocation", DEFAULT_CRISIS_OVERLAY.shift_allocation)
    if isinstance(alloc_raw, dict):
        allocation = tuple((str(k), float(v)) for k, v in alloc_raw.items())
    else:
        allocation = tuple(
            (str(pair[0]), float(pair[1]))
            for pair in alloc_raw
            if isinstance(pair, (list, tuple)) and len(pair) == 2
        )
    return CrisisOverlay(
        vol_multiplier_reduction=float(
            raw.get(
                "vol_multiplier_reduction",
                DEFAULT_CRISIS_OVERLAY.vol_multiplier_reduction,
            )
        ),
        equity_shift_pct=float(
            raw.get("equity_shift_pct", DEFAULT_CRISIS_OVERLAY.equity_shift_pct)
        ),
        shift_allocation=allocation,
    )


def resolve_quadrant_policy(
    snapshot: QuadrantSnapshot,
    *,
    policy: Mapping[str, Mapping[str, Any]] | None = None,
    overlay: CrisisOverlay | None = None,
) -> RegimePolicyDecision:
    """Map a :class:`QuadrantSnapshot` to a :class:`RegimePolicyDecision`.

    Falls back to the Deflationary Slowdown entry if the quadrant isn't found.
    Applies the crisis overlay when ``snapshot.crisis_flag`` is true.
    """
    active_policy = dict(policy) if policy is not None else dict(DEFAULT_QUADRANT_POLICY)
    base = active_policy.get(
        snapshot.quadrant, active_policy[QUADRANT_DEFLATIONARY_SLOWDOWN]
    )
    vol_multiplier = float(base.get("vol_multiplier", 1.0))
    targets = {
        str(k): float(v)
        for k, v in dict(base.get("asset_class_targets", {})).items()
    }
    notes = str(base.get("notes", ""))

    if snapshot.crisis_flag:
        ov = overlay or DEFAULT_CRISIS_OVERLAY
        intensity = max(0.0, min(1.0, float(snapshot.crisis_intensity)))
        if intensity > 0:
            vol_multiplier *= max(0.0, 1.0 - ov.vol_multiplier_reduction * intensity)
            shift_total = ov.equity_shift_pct * intensity
            current_eq = targets.get("EQ", 0.0)
            taken = min(current_eq, shift_total)
            targets["EQ"] = current_eq - taken
            for bucket, share in ov.shift_allocation:
                targets[bucket] = targets.get(bucket, 0.0) + taken * float(share)
            notes = (
                notes
                + f" Crisis overlay applied (intensity={intensity:.2f})."
            ).strip()

    corr_raw = base.get("corr_overrides")
    corr = (
        {str(k): float(v) for k, v in dict(corr_raw).items()}
        if isinstance(corr_raw, dict)
        else None
    )
    return RegimePolicyDecision(
        as_of=snapshot.as_of,
        regime=snapshot.quadrant,
        vol_multiplier=vol_multiplier,
        asset_class_targets=targets,
        notes=notes,
        corr_overrides=corr,
    )


__all__ = [
    "DEFAULT_QUADRANT_POLICY",
    "DEFAULT_CRISIS_OVERLAY",
    "CrisisOverlay",
    "load_quadrant_policy",
    "load_crisis_overlay",
    "resolve_quadrant_policy",
    "QUADRANT_LABELS",
]
