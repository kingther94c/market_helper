"""The "Today" attention strip — `/advisor` opens with answers, not buttons.

A zero-click, cross-module synthesis bar at the top of the page: roll urgency
(T1), due idea reviews, FX-target staleness + the carry-tilt headline, Tactical
Edge brief freshness, and the last option scan's stats. Everything is local /
cached data (no network in the render path), gathered **async off the render
path**, and each chip jumps to its module tab.

``build_attention_items`` is pure (unit-tested) over pre-gathered ingredients;
``gather_attention_inputs`` does the graceful IO (each ingredient independently
best-effort — one failure never blanks the strip).
"""
from __future__ import annotations

import asyncio
import datetime as _dt
import re

from nicegui import ui

from market_helper.trade_advisor.contracts import LABEL_RESEARCH_READY, LABEL_WATCHLIST

# Tab labels (must match page.py's ui.tab(...) names) — a chip's jump target.
TAB_OPTION = "Option Strategy"
TAB_FX = "FX Hedge"
TAB_TACTICAL = "Tactical Trade Ideas"
TAB_ROLL = "Roll & Carry Calendar"

_SEVERITY_ORDER = {"alert": 0, "warn": 1, "info": 2, "ok": 3}
_CACHED_AGE_RE = re.compile(r"cached_(\d+)d")

# The FX hedge target artifact's own staleness convention is 30 days (the provider
# refresh-if-stale window) — past it, flag the target as needing a refresh.
FX_STALE_DAYS = 30
EDGE_STALE_DAYS = 3


def _days_between(earlier: str, later: str) -> int | None:
    try:
        a = _dt.date.fromisoformat(str(earlier)[:10])
        b = _dt.date.fromisoformat(str(later)[:10])
    except (ValueError, TypeError):
        return None
    return (b - a).days


def build_attention_items(
    *,
    today: str,
    roll_rows: list[dict] | None,
    due_reviews: int,
    fx_panel: dict | None,
    edge_date: str = "",
    edge_count: int = 0,
    scan: dict | None = None,
) -> list[dict]:
    """Pure synthesis: pre-gathered module states → ordered attention items.

    Each item: ``{"key", "severity": alert|warn|info|ok, "text", "tab"}`` —
    alerts first. A module whose ingredient is ``None`` (couldn't be read) is
    simply absent: the strip never fabricates a status.
    """
    items: list[dict] = []

    # Roll & Carry (T1 operational — the only true *alert* source).
    if roll_rows is not None:
        urgent = [r for r in roll_rows if r.get("label") == LABEL_RESEARCH_READY]
        window = [r for r in roll_rows if r.get("label") == LABEL_WATCHLIST]
        if urgent:
            first = urgent[0]
            more = f" +{len(urgent) - 1} more" if len(urgent) > 1 else ""
            items.append({"key": "roll", "severity": "alert", "tab": TAB_ROLL,
                          "text": f"Roll now: {first.get('subject')} {first.get('instrument')}{more}"})
        elif window:
            items.append({"key": "roll", "severity": "warn", "tab": TAB_ROLL,
                          "text": f"Roll window: {len(window)} position{'s' if len(window) > 1 else ''}"})
        else:
            items.append({"key": "roll", "severity": "ok", "tab": TAB_ROLL, "text": "Roll: nothing due"})

    # Decision-journal review loop (what keeps the advisor verifiable).
    if due_reviews > 0:
        items.append({"key": "reviews", "severity": "warn", "tab": None,
                      "text": f"{due_reviews} idea review{'s' if due_reviews > 1 else ''} due (Inbox below)"})

    # FX hedge target — staleness + the tilt headline.
    if fx_panel is not None:
        if not fx_panel.get("available"):
            items.append({"key": "fx", "severity": "info", "tab": TAB_FX,
                          "text": "FX: no cached hedge target"})
        else:
            age_m = _CACHED_AGE_RE.search(str(fx_panel.get("data_mode", "")))
            age = int(age_m.group(1)) if age_m else None
            tilt = (fx_panel.get("tilt_detail") or {}).get("tilt") or {}
            if age is not None and age > FX_STALE_DAYS:
                items.append({"key": "fx", "severity": "warn", "tab": TAB_FX,
                              "text": f"FX target stale ({age}d) — refresh"})
            elif tilt.get("rows"):
                items.append({"key": "fx", "severity": "info", "tab": TAB_FX,
                              "text": (f"FX tilt: {tilt.get('carry_impact_bps', 0):+.0f}bps carry · "
                                       f"{tilt.get('hedge_deviation_pct', 0) * 100:.0f}% deviation")})
            else:
                items.append({"key": "fx", "severity": "ok", "tab": TAB_FX,
                              "text": f"FX target {fx_panel.get('data_mode', '')}"})

    # Tactical Edge brief freshness (skip silently when the folder isn't configured).
    if edge_date:
        age = _days_between(edge_date, today)
        if age is not None and age > EDGE_STALE_DAYS:
            items.append({"key": "edge", "severity": "warn", "tab": TAB_TACTICAL,
                          "text": f"Edge brief {edge_date} ({age}d old)"})
        else:
            items.append({"key": "edge", "severity": "info", "tab": TAB_TACTICAL,
                          "text": f"Edge brief {edge_date} · {edge_count} cards"})

    # Last option scan (persisted by the Option module).
    if scan is not None and scan.get("suggestions"):
        ready = sum(1 for s in scan["suggestions"] if getattr(s, "label", "") == LABEL_RESEARCH_READY)
        items.append({"key": "scan", "severity": "info", "tab": TAB_OPTION,
                      "text": (f"Option scan {str(scan.get('saved_at', ''))[:10]}: "
                               f"{len(scan['suggestions'])} ideas ({ready} ready)")})
    else:
        items.append({"key": "scan", "severity": "info", "tab": TAB_OPTION,
                      "text": "No option scan cached — scan now"})

    items.sort(key=lambda it: _SEVERITY_ORDER.get(it["severity"], 9))
    return items


def gather_attention_inputs(journal) -> dict:
    """Blocking IO for the strip — each ingredient independently graceful.

    Runs off the render path (the caller wraps it in ``asyncio.to_thread``); a
    failed ingredient comes back ``None``/empty and its chip is simply absent.
    """
    today = _dt.date.today().isoformat()
    out: dict = {"today": today, "roll_rows": None, "due_reviews": 0,
                 "fx_panel": None, "edge_date": "", "edge_count": 0, "scan": None}

    try:
        from market_helper.application.trade_advisor import context_from_positions_csv

        from .modules.roll import build_roll_rows

        out["roll_rows"] = build_roll_rows(context_from_positions_csv())
    except Exception:  # noqa: BLE001 — best-effort per ingredient
        pass
    try:
        out["due_reviews"] = len(journal.due_for_review(today))
    except Exception:  # noqa: BLE001
        pass
    try:
        from .modules.fx_hedge import build_fx_panel

        out["fx_panel"] = build_fx_panel()
    except Exception:  # noqa: BLE001
        pass
    try:
        from market_helper.domain.tactical_ideas.tactical_edge import load_tactical_edge

        date, cards = load_tactical_edge(None)
        out["edge_date"], out["edge_count"] = date, len(cards)
    except Exception:  # noqa: BLE001
        pass
    try:
        from market_helper.application.trade_advisor import load_option_scan

        out["scan"] = load_option_scan()
    except Exception:  # noqa: BLE001
        pass
    return out


_CHIP_PROPS = {
    "alert": {"color": "negative", "text_color": "white", "icon": "priority_high"},
    "warn": {"color": "warning", "text_color": "black", "icon": "schedule"},
    "info": {"color": "blue-grey-8", "text_color": "white", "icon": "info"},
    "ok": {"color": "positive", "text_color": "white", "icon": "check"},
}


def render_overview_strip(tabs, tab_by_label: dict, journal) -> None:
    """Render the strip skeleton + populate it async (off the render path).

    ``tab_by_label`` maps the TAB_* labels to the ``ui.tab`` objects so a chip
    click jumps to its module tab.
    """
    box = ui.row().classes("w-full items-center gap-2 wrap")
    with box:
        ui.label("Today —").classes("text-caption pm-muted")
        ui.spinner(size="1em")

    async def _populate() -> None:
        try:
            inputs = await asyncio.to_thread(gather_attention_inputs, journal)
            items = build_attention_items(**inputs)
        except Exception as exc:  # noqa: BLE001 — the strip must never break the page
            box.clear()
            with box:
                ui.label(f"Today: unavailable ({type(exc).__name__})").classes("text-caption pm-muted")
            return
        box.clear()
        with box:
            ui.label("Today —").classes("text-caption pm-muted")
            for item in items:
                props = _CHIP_PROPS.get(item["severity"], _CHIP_PROPS["info"])
                chip = ui.chip(item["text"], color=props["color"], text_color=props["text_color"],
                               icon=props["icon"]).props("dense square")
                target = tab_by_label.get(item.get("tab"))
                if target is not None:
                    chip.props("clickable")
                    chip.on_click(lambda t=target: tabs.set_value(t))

    ui.timer(0.1, _populate, once=True)
