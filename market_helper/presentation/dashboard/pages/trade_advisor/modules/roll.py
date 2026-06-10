"""Roll & Carry Calendar module — holdings-derived, **no run**.

This module does not run an advisor. On render it reads the live book (held
options + futures) and lays out a plain **calendar**: which positions need a roll
and when (explicit dates, v2.1), sorted by urgency. There is no
Promote/Watch/Dismiss and no journal — a roll schedule is an operational fact,
not an idea stream.

Two parts (devplan §5.4):
- (a) **Current holdings' roll calendar** — options + futures, reusing the existing
  roll engines (``roll`` + ``futures_roll`` adapters) but rendered as a table.
- (b) **Commodity carry** — v2.1: the **held-roots roll yield** (held contract vs
  next liquid, Yahoo month-contract quotes; cached artifact, network only on the
  explicit Fetch action) plus the honest GSCI/F1-F7 placeholder for the full
  curve, which stays blocked on a CME forward feed.

The row/table builders are pure and unit-tested; the ``ui.*`` wrappers stay thin
and populate **async off the render path**.
"""
from __future__ import annotations

import asyncio

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
        "date": str(d.get("expiry") or "—"),
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
        "date": str(d.get("roll_target") or "—"),
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
    headers = ["Type", "Subject", "Instrument", "Urgency", "To roll", "Roll date", "Schedule"]
    out = [
        [r["kind"], r["subject"], r["instrument"], r["urgency"], r["to_roll"],
         r.get("date", "—"), r["schedule"]]
        for r in rows
    ]
    return headers, out


def roll_yield_table(rows: list[dict]) -> tuple[list[str], list[list[str]]]:
    """Headers + formatted rows for the held-roots roll-yield (carry) view.

    ``ok`` rows show the two-contract slice; skipped/no-quote rows surface their
    reason instead of being silently dropped (no silent coverage gaps).
    """
    headers = ["Root", "Held", "Next", "F held", "F next", "Roll yield (ann)", "Read"]
    out: list[list[str]] = []
    for r in rows:
        if r.get("status") == "ok":
            ann = r.get("roll_yield_ann")
            out.append([
                str(r.get("root", "—")),
                str(r.get("held_contract", "—")),
                str(r.get("next_contract", "—")),
                _num(r.get("held_px"), ",.4g"),
                _num(r.get("next_px"), ",.4g"),
                f"{ann * 100:+.1f}%" if ann is not None else "—",
                str(r.get("curve", "—")),
            ])
        else:
            out.append([
                str(r.get("root", "—")), str(r.get("held_contract", "—")),
                str(r.get("next_contract", "—") or "—"), "—", "—", "—",
                str(r.get("note", r.get("status", "—"))),
            ])
    return headers, out


def commodity_carry_placeholder() -> dict:
    """The full-curve ambition note — honest about what the two-contract slice is NOT."""
    return {
        "title": "Commodity carry calendar — full curve still open",
        "body": (
            "Target: pull GSCI's latest roll calendar and tune its F1/F7 deferred-carry "
            "logic as the baseline (front vs deferred roll yield by commodity sector)."
        ),
        "blocked_on": (
            "Blocked on a CME forward curve (not in-repo). The table above is a "
            "two-contract slice (held vs next liquid) for held roots only — it must "
            "not be read as the full F1/F7 curve."
        ),
    }


# --------------------------------------------------------------------------- #
# Rendering (thin)
# --------------------------------------------------------------------------- #


def _default_context() -> AdvisorContext:
    from market_helper.application.trade_advisor import context_from_positions_csv

    return context_from_positions_csv()


def _render_calendar(box, rows: list[dict]) -> None:
    box.clear()
    with box:
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


def _render_carry(box, payload: "dict | None", *, fetching: bool = False) -> None:
    box.clear()
    with box:
        if fetching:
            ui.label("Fetching month-contract quotes…").classes("text-caption pm-muted")
            return
        if payload and payload.get("rows"):
            headers, trows = roll_yield_table(payload["rows"])
            _ui_table(headers, trows)
            age = payload.get("age_hours")
            stamp = str(payload.get("fetched_at", ""))[:16]
            age_txt = f" ({age:.0f}h old)" if isinstance(age, (int, float)) else ""
            ui.label(
                f"Quoted {stamp}{age_txt} · positive = backwardation (long-friendly roll), "
                "negative = contango. Held roots only."
            ).classes("text-caption pm-muted")
        elif payload is not None:
            ui.label("No month-coded futures in the book to quote.").classes("text-caption pm-muted")
        else:
            ui.label(
                "No cached quotes yet — Fetch pulls the held + next-liquid month contracts from Yahoo "
                "(explicit network action; nothing fetches on page load)."
            ).classes("text-caption pm-muted")


def render_roll_module(*, loader=None) -> None:
    """Render the Roll & Carry Calendar — no run; reads holdings async on load."""
    ui.label("Roll & Carry Calendar").classes("text-subtitle1")
    ui.label(
        "Derived straight from your holdings — no run needed. Options + futures roll "
        "timing with explicit dates; held-roots carry below (quotes on demand)."
    ).classes("text-caption pm-muted")

    with ui.card().classes("w-full pm-card"):
        ui.label("Holdings roll calendar").classes("text-subtitle2")
        cal_box = ui.column().classes("w-full")
        with cal_box:
            ui.label("Reading holdings…").classes("text-caption pm-muted")

    with ui.card().classes("w-full pm-card"):
        with ui.row().classes("items-center justify-between w-full"):
            ui.label("Held-roots carry · two-contract roll yield").classes("text-subtitle2")
            fetch_btn = ui.button("Fetch quotes (network)").props("dense")
        carry_box = ui.column().classes("w-full")
        with carry_box:
            ui.label("Loading cached quotes…").classes("text-caption pm-muted")
        ph = commodity_carry_placeholder()
        ui.label(ph["body"]).classes("text-caption pm-muted")
        ui.label(ph["blocked_on"]).classes("text-caption").style("color:#f3b34d")

    async def _populate() -> None:
        try:
            context = await asyncio.to_thread(loader or _default_context)
            rows = await asyncio.to_thread(lambda: build_roll_rows(context))
        except Exception as exc:  # noqa: BLE001 — surface, never crash the page
            cal_box.clear()
            with cal_box:
                ui.label(f"Could not read holdings: {type(exc).__name__}: {str(exc)[:160]}").classes(
                    "text-caption pm-muted"
                )
            rows = None  # keep the error visible — don't overwrite with an empty state
        if rows is not None:
            _render_calendar(cal_box, rows)
        try:
            from market_helper.application.trade_advisor.roll_carry import load_roll_yields

            payload = await asyncio.to_thread(load_roll_yields)
        except Exception:  # noqa: BLE001 — cache read is best-effort
            payload = None
        _render_carry(carry_box, payload)

    ui.timer(0.1, _populate, once=True)

    async def _fetch() -> None:
        fetch_btn.disable()
        _render_carry(carry_box, None, fetching=True)
        try:
            from market_helper.application.trade_advisor.roll_carry import fetch_roll_yields

            payload = await asyncio.to_thread(fetch_roll_yields)
            payload["age_hours"] = 0.0
        except Exception as exc:  # noqa: BLE001 — a failed fetch degrades, never crashes
            carry_box.clear()
            with carry_box:
                ui.label(f"Quote fetch failed: {type(exc).__name__}: {str(exc)[:160]}").classes(
                    "text-caption"
                ).style("color:#f3b34d")
            fetch_btn.enable()
            return
        _render_carry(carry_box, payload)
        fetch_btn.enable()

    fetch_btn.on_click(_fetch)
