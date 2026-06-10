"""Persist the latest Option scan so `/advisor` opens with answers, not buttons.

A scan is expensive (per-symbol chain fetches) and was previously lost on every
reload. ``save_option_scan`` snapshots the suggestions + the inputs that produced
them to ``data/artifacts/trade_advisor/option_scan_latest.json`` (gitignored);
``load_option_scan`` restores them with the saved-at / as-of stamps so the UI can
badge how old the view is. Honesty: a restored scan is *display* state — the
data_mode and timestamps ride along untouched, never re-labelled as fresh.

Round-trips the frozen :class:`Suggestion` dataclass (nested ``AuditEntry`` /
``IdeaAssessment`` / ``Sizing``) via plain dicts; a corrupt or missing artifact
loads as ``None``, never an exception.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from market_helper.app.paths import TRADE_ADVISOR_ARTIFACTS_DIR
from market_helper.trade_advisor.contracts import (
    AuditEntry,
    IdeaAssessment,
    Sizing,
    Suggestion,
)

DEFAULT_SCAN_PATH = TRADE_ADVISOR_ARTIFACTS_DIR / "option_scan_latest.json"


def suggestion_to_dict(s: Suggestion) -> dict:
    """JSON-serializable view of a Suggestion (nested dataclasses included)."""
    return asdict(s)


def _filtered(cls, payload: dict) -> dict:
    return {k: payload[k] for k in payload if k in cls.__dataclass_fields__}


def suggestion_from_dict(payload: dict) -> Suggestion:
    """Rebuild a Suggestion from :func:`suggestion_to_dict` output.

    Unknown keys are ignored (forward-compat); ``drivers`` pairs come back as
    tuples; nested dataclasses are reconstructed.
    """
    data = _filtered(Suggestion, dict(payload))
    data["drivers"] = [tuple(d) for d in (data.get("drivers") or [])]
    data["audit"] = [AuditEntry(**_filtered(AuditEntry, a)) for a in (data.get("audit") or [])]
    assessment = data.get("assessment")
    if isinstance(assessment, dict):
        data["assessment"] = IdeaAssessment(**_filtered(IdeaAssessment, assessment))
    sizing = data.get("sizing")
    if isinstance(sizing, dict):
        data["sizing"] = Sizing(**_filtered(Sizing, sizing))
    return Suggestion(**data)


def save_option_scan(
    suggestions: list[Suggestion],
    *,
    as_of: str,
    data_mode: str,
    inputs: dict | None = None,
    warnings: list[str] | None = None,
    path: str | Path | None = None,
    saved_at: str | None = None,
) -> Path:
    """Write the latest-scan artifact. ``inputs`` records what produced the scan."""
    out = Path(path) if path else DEFAULT_SCAN_PATH
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "saved_at": saved_at or datetime.now().isoformat(timespec="seconds"),
        "as_of": as_of,
        "data_mode": data_mode,
        "inputs": dict(inputs or {}),
        "warnings": list(warnings or []),
        "suggestions": [suggestion_to_dict(s) for s in suggestions],
    }
    out.write_text(json.dumps(payload), encoding="utf-8")
    return out


def load_option_scan(path: str | Path | None = None) -> dict | None:
    """Load the latest-scan artifact, or ``None`` (missing / corrupt — graceful).

    Returns ``{"saved_at", "as_of", "data_mode", "inputs", "warnings",
    "suggestions": [Suggestion, …]}``.
    """
    src = Path(path) if path else DEFAULT_SCAN_PATH
    if not src.exists():
        return None
    try:
        payload = json.loads(src.read_text(encoding="utf-8"))
        suggestions = [suggestion_from_dict(d) for d in payload.get("suggestions", [])]
    except Exception:  # noqa: BLE001 — a corrupt artifact must never break the page
        return None
    return {
        "saved_at": str(payload.get("saved_at", "")),
        "as_of": str(payload.get("as_of", "")),
        "data_mode": str(payload.get("data_mode", "")),
        "inputs": dict(payload.get("inputs") or {}),
        "warnings": list(payload.get("warnings") or []),
        "suggestions": suggestions,
    }
