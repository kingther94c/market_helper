from __future__ import annotations

"""Build a lightweight regime dashboard payload for notebooks or future UIs."""

from pathlib import Path
from typing import Any

from market_helper.domain.regime_detection.policies.regime_policy import load_regime_policy, resolve_policy
from market_helper.domain.regime_detection.services.detection_service import load_regime_snapshots


def generate_regime_dashboard(
    *,
    regime_path: str | Path,
    policy_path: str | Path | None = None,
) -> dict[str, Any]:
    # The dashboard stays intentionally small for now: latest regime snapshot
    # plus the read-only policy interpretation for that state.
    snapshots = load_regime_snapshots(regime_path)
    if not snapshots:
        return {"latest": None, "policy": None}
    latest = snapshots[-1]
    decision = resolve_policy(latest, policy=load_regime_policy(policy_path))
    return {
        "latest": latest.to_dict(),
        "policy": decision.to_dict(),
    }


__all__ = ["generate_regime_dashboard"]
