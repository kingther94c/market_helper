"""Seed the advisor's regime context from the live regime snapshot.

The umbrella's ``/advisor`` page exposes *Regime* / *Confidence* / *Crisis* as
bounded controls. Rather than make the operator re-key what the regime engine
already determined, this reads the latest regime snapshot and offers it as the
**default** — still fully overridable (it's a bounded control, not an oracle).

This is the rule-based, explainable counterpart to an LLM "read the regime"
step: we map the engine's own fields onto our controls, no model in the loop.

Read-only, best-effort: a missing / malformed artifact, or a label the UI
doesn't recognise, degrades to an empty seed (manual entry) rather than raising.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from market_helper.app.paths import REGIME_ARTIFACTS_DIR

DEFAULT_REGIME_SNAPSHOT_PATH = REGIME_ARTIFACTS_DIR / "regime_snapshots.json"

# The four base quadrants the engine emits (``base_regime``) — these match the
# ``/advisor`` Regime dropdown exactly. ``final_regime`` may append a
# " + Stress Overlay" suffix, which we strip before matching.
_KNOWN_REGIMES = frozenset({"Goldilocks", "Reflation", "Stagflation", "Deflationary Slowdown"})
_KNOWN_CONFIDENCE = frozenset({"High", "Medium", "Low"})


@dataclass(frozen=True)
class RegimeSeed:
    """Default regime context for the advisor inputs (empty = manual entry)."""

    regime: str = ""
    confidence: str = ""
    crisis: bool = False

    @property
    def is_seeded(self) -> bool:
        return bool(self.regime)


def _latest_snapshot(path: Path) -> dict | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if isinstance(payload, list):
        snap = payload[-1] if payload else None
    elif isinstance(payload, dict):
        snap = payload
    else:
        snap = None
    return snap if isinstance(snap, dict) else None


def current_regime_seed(path: str | Path | None = None) -> RegimeSeed:
    """Return the latest regime snapshot mapped onto the advisor's controls.

    Prefers ``base_regime`` (the clean quadrant); falls back to ``final_regime``
    with any " + Stress Overlay" suffix stripped. ``risk_overlay_on`` maps to the
    crisis flag. Unrecognised labels are dropped to ``""`` so the dropdown stays
    valid.
    """
    snap = _latest_snapshot(Path(path) if path else DEFAULT_REGIME_SNAPSHOT_PATH)
    if snap is None:
        return RegimeSeed()

    regime = str(snap.get("base_regime") or "").strip()
    if regime not in _KNOWN_REGIMES:
        regime = str(snap.get("final_regime") or "").split(" + ")[0].strip()
    regime = regime if regime in _KNOWN_REGIMES else ""

    confidence = str(snap.get("confidence") or "").strip()
    confidence = confidence if confidence in _KNOWN_CONFIDENCE else ""

    return RegimeSeed(regime=regime, confidence=confidence, crisis=bool(snap.get("risk_overlay_on", False)))


__all__ = ["RegimeSeed", "current_regime_seed", "DEFAULT_REGIME_SNAPSHOT_PATH"]
