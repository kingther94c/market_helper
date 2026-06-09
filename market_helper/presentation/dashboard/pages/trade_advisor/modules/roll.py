"""Roll & Carry Calendar module — holdings-derived, **no run**.

This module does not run an advisor. On render it reads the live book (held
options + futures) and lays out a plain **calendar**: which positions need a roll
and when, sorted by urgency. There is no Promote/Watch/Dismiss and no journal — a
roll schedule is an operational fact, not an idea stream.

Two parts (devplan §5.4):
- (a) **Current holdings' roll calendar** — options + futures, reusing the existing
  roll engines (``roll`` + ``futures_roll`` adapters) but rendered as a table.
- (b) **Commodity carry calendar** — a labelled placeholder (GSCI / F1-F7), honestly
  blocked on a CME forward curve that is not in-repo.

The row/table builders are pure and unit-tested; the ``ui.*`` wrappers stay thin.
"""
from __future__ import annotations

from nicegui import ui

from market_helper.trade_advisor.contracts import (
    LABEL_INFO,
    LABEL_ORDER,
    LABEL_RESEARCH_READY,
    LABEL_WATCHLIST,
    AdvisorContext,
)

from ..cards import _num, _ui_table

# Roll-engine label → operator-facing urgency text for the calendar.
_URGENCY_TEXT = {
    LABEL_RESEARCH_READY: "Roll now",
    LABEL_WATCHLIST: "In window",
    LABEL_INFO: "OK",
}
_NONE_IDS = {"roll:none", "futures_roll:none"}


# --------------------------------------------------------------------------- #
# Pure builders (unit-tested)
# --------------------------------------------------------------------------- #


def _option_row(s) -> dict:
    d = s.detail or {}
    dte = d.get("dte")
    qty = d.get("qty") or 0
    side = "short" if qty < 0 else "long"
    return {
        "kind": "Option",
        "subject": str(d.get("underlying", s.subject)),
        "instrument": f"{side} {d.get('right', '')}{_num(d.get('strike'))} {d.get('expiry', '—')}",
        "label": s.label,
        "urgency": _URGENCY_TEXT.get(s.label, "—"),
        "days": dte,
        "to_roll": f"{dte}d" if dte is not None else "—",
        "schedule": "monthly",
        "why": s.why_now,
    }


def _future_row(s) -> dict:
    d = s.detail or {}
    days = d.get("days_to_roll")
    delivery = d.get("delivery_label", "")
    contract = d.get("contract") or delivery
    return {
        "kind": "Future",
        "subject": str(d.get("root", s.subject)),
        "instrument": f"{contract} ({delivery})" if delivery else str(contract),
        "label": s.label,
        "urgency": _URGENCY_TEXT.get(s.label, "—"),
        "days": days,
        "to_roll": f"{days}d" if days is not None else "—",
        "schedule": "GSCI-like" if d.get("schedule") == "gsci" else "expiry",
        "why": s.why_now,
    }


def _sort_key(row: dict):
    """Most urgent first: by label rank, then nearest roll (None last)."""
    days = row.get("days")
    return (LABEL_ORDER.get(row.get("label"), 9), days if days is not None else 9999)


def build_roll_rows(context: AdvisorContext, *, today: str | None = None) -> list[dict]:
    """Flatten held options + futures into sorted calendar rows (pure; no network).

    Reuses the existing roll engines via their adapters, then re-frames the
    suggestions as calendar rows (dropping the empty-state ``:none`` sentinels).
    """
    from market_helper.trade_advisor.adapters.futures_roll import FuturesRollPlugin
    from market_helper.trade_advisor.adapters.roll import RollReminderPlugin

    rows: list[dict] = []
    opt = RollReminderPlugin().produce(context, today=today)
    for s in opt.suggestions:
        if s.suggestion_id not in _NONE_IDS:
            rows.append(_option_row(s))
    fut = FuturesRollPlugin().produce(context, today=today)
    for s in fut.suggestions:
        if s.suggestion_id not in _NONE_IDS:
            rows.append(_future_row(s))
    rows.sort(key=_sort_key)
    return rows


def roll_calendar_table(rows: list[dict]) -> tuple[list[str], list[list[str]]]:
    """Headers + formatted string rows for the holdings roll calendar."""
    headers = ["Type", "Subject", "Instrument", "Urgency", "To roll", "Schedule"]
    out = [
        [r["kind"], r["subject"], r["instrument"], r["urgency"], r["to_roll"], r["schedule"]]
        for r in rows
    ]
    return headers, out


def commodity_carry_placeholder() -> dict:
    """The (b) commodity-carry-calendar placeholder content — honest about the gap."""
    return {
        "title": "Commodity carry calendar — placeholder",
        "body": (
            "Target: pull GSCI's latest roll calendar and tune its F1/F7 deferred-carry "
            "logic as the baseline (front vs deferred roll yield by commodity sector)."
        ),
        "blocked_on": (
            "Blocked on a CME forward curve (not in-repo). Today's engine is roll-timing "
            "only and must not fabricate basis — held-commodity roll *timing* already shows "
            "above under \"Future\"."
        ),
    }


# --------------------------------------------------------------------------- #
# Rendering (thin)
# --------------------------------------------------------------------------- #


def _default_context() -> AdvisorContext:
    from market_helper.application.trade_advisor import context_from_positions_csv

    return context_from_positions_csv()


def render_roll_module(*, loader=None) -> None:
    """Render the Roll & Carry Calendar — no run; reads holdings on load."""
    ui.label("Roll & Carry Calendar").classes("text-subtitle1")
    ui.label(
        "Derived straight from your holdings — no run needed. Options + futures roll "
        "timing; commodity carry calendar is a placeholder below."
    ).classes("text-caption pm-muted")

    with ui.card().classes("w-full pm-card"):
        ui.label("Holdings roll calendar").classes("text-subtitle2")
        try:
            context = (loader or _default_context)()
            rows = build_roll_rows(context)
        except Exception as exc:  # noqa: BLE001 — surface, never crash the page
            ui.label(f"Could not read holdings: {type(exc).__name__}: {str(exc)[:160]}").classes("text-caption pm-muted")
            rows = []
        if rows:
            headers, trows = roll_calendar_table(rows)
            _ui_table(headers, trows)
            urgent = [r for r in rows if r["label"] == LABEL_RESEARCH_READY]
            if urgent:
                ui.label(
                    "Roll now: " + ", ".join(f"{r['subject']} {r['instrument']}" for r in urgent[:6])
                ).classes("text-caption").style("color:#f3b34d")
        else:
            ui.label(
                "No held options or futures found. Load your portfolio (live positions) to see roll timing."
            ).classes("text-caption pm-muted")

    ph = commodity_carry_placeholder()
    with ui.card().classes("w-full pm-card"):
        ui.label(ph["title"]).classes("text-subtitle2")
        ui.label(ph["body"]).classes("text-caption pm-muted")
        ui.label(ph["blocked_on"]).classes("text-caption").style("color:#f3b34d")
