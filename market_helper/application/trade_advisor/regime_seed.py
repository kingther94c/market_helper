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


# The canonical regime artifact (``regime_snapshots.json``) is a single JSON array the
# engine APPENDS to indefinitely — in practice it grows to 100s of MB. Both the advisor
# seed and the tactical context only need the LAST snapshot, so fully parsing it on every
# page load froze the UI. We therefore (a) tail-read just the last array element for big
# files, and (b) cache by (mtime, size) so repeated reads in one process are free.
# (The root fix — bounding the engine's append — is a separate regime-engine task.)
_FULL_PARSE_MAX = 4 * 1024 * 1024     # ≤4 MB → parse fully (simple + robust; covers test fixtures)
_TAIL_BYTES = 1024 * 1024             # read up to the last 1 MB for the tail scan
_SNAPSHOT_CACHE: dict[str, tuple[float, int, "dict | None"]] = {}


def _parse_last_full(path: Path) -> dict | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return None
    if isinstance(payload, list):
        snap = payload[-1] if payload else None
    elif isinstance(payload, dict):
        snap = payload
    else:
        snap = None
    return snap if isinstance(snap, dict) else None


def _parse_last_tail(path: Path, size: int) -> dict | None:
    """Last element of a pretty-printed (``indent=2``) JSON array — without a full parse.

    Top-level array elements open/close at exactly two-space indent (``  {`` / ``  }``);
    nested content is indented deeper, so those lines unambiguously bound the last object.
    """
    try:
        with open(path, "rb") as fh:
            fh.seek(max(0, size - _TAIL_BYTES))
            tail = fh.read().decode("utf-8", errors="ignore")
    except OSError:
        return None
    lines = tail.splitlines()
    close = next((i for i in range(len(lines) - 1, -1, -1) if lines[i].rstrip() in ("  }", "  },")), None)
    if close is None:
        return None
    opener = next((i for i in range(close - 1, -1, -1) if lines[i].rstrip() == "  {"), None)
    if opener is None:
        return None
    block = "\n".join(lines[opener:close + 1]).rstrip().rstrip(",")
    try:
        obj = json.loads(block)
    except (json.JSONDecodeError, ValueError):
        return None
    return obj if isinstance(obj, dict) else None


def latest_regime_snapshot(path: str | Path | None = None) -> dict | None:
    """Return the latest regime snapshot dict, reading the huge append-only array cheaply.

    Cached by (mtime, size) per path, so the first read in a process pays the cost and
    every later read (other tabs, the tactical context) is free. Big files are tail-read;
    small files / fixtures are parsed fully. Best-effort: returns ``None`` on any problem.
    """
    p = Path(path) if path else DEFAULT_REGIME_SNAPSHOT_PATH
    try:
        st = p.stat()
    except OSError:
        return None
    key = str(p)
    hit = _SNAPSHOT_CACHE.get(key)
    if hit is not None and hit[0] == st.st_mtime and hit[1] == st.st_size:
        return hit[2]
    snap = _parse_last_full(p) if st.st_size <= _FULL_PARSE_MAX else _parse_last_tail(p, st.st_size)
    _SNAPSHOT_CACHE[key] = (st.st_mtime, st.st_size, snap)
    return snap


# Back-compat alias (older callers / tests).
_latest_snapshot = latest_regime_snapshot


def current_regime_seed(path: str | Path | None = None) -> RegimeSeed:
    """Return the latest regime snapshot mapped onto the advisor's controls.

    Prefers ``base_regime`` (the clean quadrant); falls back to ``final_regime``
    with any " + Stress Overlay" suffix stripped. ``risk_overlay_on`` maps to the
    crisis flag. Unrecognised labels are dropped to ``""`` so the dropdown stays
    valid.
    """
    snap = latest_regime_snapshot(path)
    if snap is None:
        return RegimeSeed()

    regime = str(snap.get("base_regime") or "").strip()
    if regime not in _KNOWN_REGIMES:
        regime = str(snap.get("final_regime") or "").split(" + ")[0].strip()
    regime = regime if regime in _KNOWN_REGIMES else ""

    confidence = str(snap.get("confidence") or "").strip()
    confidence = confidence if confidence in _KNOWN_CONFIDENCE else ""

    return RegimeSeed(regime=regime, confidence=confidence, crisis=bool(snap.get("risk_overlay_on", False)))


__all__ = ["RegimeSeed", "current_regime_seed", "latest_regime_snapshot", "DEFAULT_REGIME_SNAPSHOT_PATH"]
