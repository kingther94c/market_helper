"""FX Hedge module — an independent **decision panel**, not idea-cards.

FX Hedge is a continuous allocation decision, so it deliberately does NOT use the
Promote/Watch/Dismiss idea contract or the journal. Three inputs side by side
(devplan §5.2) feeding an actual **decision join** (v2.1):

1. **Baseline hedging mix** — Portfolio Monitor's FX-hedge target artifact (per-ccy
   target contracts / betas / indicative carry), read cached (no network).
2. **Current FX exposure** — the currency lookthrough of the book, including the
   **signed FX-futures overlay** (a future's ``market_value`` is its signed
   notional).
3. **Carry** — per-ccy carry (ON-rate differential approximation).

→ **Decision** — the per-currency join the panel previously left to the reader:
   target hedge leg vs the FX futures the book *already holds* (the gap, in
   contracts and USD), the "at target" net currency mix, and the carry tilt
   before/after. Plus an **AI Plus** dialog grounded on the same data.

The panel builders are pure and unit-tested; the ``ui.*`` wrappers stay thin and
populate **async off the render path**.
"""
from __future__ import annotations

import asyncio

from nicegui import ui

from market_helper.application.trade_advisor.fx_decision import build_fx_decision
from market_helper.trade_advisor.contracts import AdvisorContext

from ..ai_pane import module_ai_initial, render_ai_pane
from ..cards import _num, _ui_table, fx_alloc_table, fx_carry_table, fx_carry_tilt_table

__all__ = ["build_fx_decision"]  # re-export: the join lives in application (one home)


# --------------------------------------------------------------------------- #
# Pure builders (unit-tested)
# --------------------------------------------------------------------------- #


def build_fx_panel(*, provider=None, mode: str = "cached") -> dict:
    """Assemble render-ready panel data from the FX hedge engine (cached; graceful).

    Reuses the ``fx_hedge`` adapter (so the mix + carry-tilt math is shared), then
    re-frames its two suggestions into a decision panel instead of idea-cards.
    ``provider`` is injectable for tests (no network / no artifact dependency).
    """
    from market_helper.trade_advisor.adapters.fx_hedge import FxHedgeAdvisorPlugin

    res = FxHedgeAdvisorPlugin().produce(AdvisorContext(), provider=provider, mode=mode)
    hedge = next((s for s in res.suggestions if s.body_kind == "fx_alloc"), None)
    tilt = next((s for s in res.suggestions if s.body_kind == "fx_carry"), None)
    available = hedge is not None and hedge.suggestion_id != "fx_hedge:missing"

    panel: dict = {
        "available": available,
        "data_mode": res.data_mode,
        "source": (res.meta or {}).get("source", ""),
        "warnings": list(res.warnings),
        "thesis": hedge.thesis if hedge else "",
        "why_now": hedge.why_now if hedge else "",
        "headline": dict(hedge.headline_metrics) if hedge else {},
        "mix": fx_alloc_table(hedge.detail) if (available and hedge) else (["Ccy"], []),
        "legs_raw": [dict(l) for l in (hedge.detail.get("fx_legs") or [])] if (available and hedge) else [],
        "carry": fx_carry_table(tilt.detail) if tilt else (["Ccy", "Carry bps", "ON %"], []),
        "tilt_detail": (tilt.detail if tilt else {}),
        "tilt_thesis": tilt.thesis if tilt else "",
        "tilt_headline": dict(tilt.headline_metrics) if tilt else {},
        "tilt_table": fx_carry_tilt_table(tilt.detail) if tilt else (["Ccy"], []),
    }
    return panel


def build_fx_exposure() -> dict:
    """Render-ready per-currency exposure of the live book (lookthrough).

    FX futures count toward the foreign currency they track; equities are looked
    through to underlying-country currencies. ``available`` is False when no
    positions are found — the caller then shows the placeholder.
    """
    from market_helper.application.trade_advisor import currency_exposure_from_positions_csv

    exp = currency_exposure_from_positions_csv()
    rows = [[c, f"{usd:,.0f}", f"{w * 100:.1f}"] for c, usd, w in exp["by_currency"]]
    return {
        "available": exp["n_positions"] > 0,
        "headers": ["Currency", "Exposure $", "Weight %"],
        "rows": rows,
        "by_currency": exp["by_currency"],
        "total_usd": exp["total_usd"],
        "as_of": exp["as_of"],
        "lookthrough": exp.get("lookthrough", False),
        "fx_overlay_by_currency": dict(exp.get("fx_overlay_by_currency") or {}),
    }


def fx_decision_table(decision: dict) -> tuple[list[str], list[list[str]]]:
    """Headers + formatted rows for the target-vs-current decision join."""
    headers = ["Ccy", "Book $", "Book %", "Now ct", "Now $", "Target ct", "Target $", "Δ ct", "Δ $"]
    rows = [
        [
            r["ccy"],
            _num(r["book_usd"], ",.0f"),
            f"{r['book_w'] * 100:.1f}",
            _num(r["cur_qty"], "+g") if r["cur_qty"] else "0",
            _num(r["cur_usd"], "+,.0f") if r["cur_usd"] else "0",
            _num(r["tgt_ct"], "+d"),
            _num(r["tgt_usd"], "+,.0f"),
            _num(r["gap_ct"], "+.0f"),
            _num(r["gap_usd"], "+,.0f"),
        ]
        for r in decision.get("rows", [])
    ]
    return headers, rows


def at_target_line(decision: dict, top: int = 6) -> str:
    """One-line 'at target' currency mix, e.g. ``USD 62% · EUR 14% · AUD 9%``."""
    parts = [f"{c} {w * 100:.0f}%" for c, _usd, w in decision.get("at_target", [])[:top]]
    return " · ".join(parts)


def fx_exposure_placeholder() -> dict:
    """Shown only when no live positions are found — honest, no fabricated number."""
    return {
        "title": "Current FX exposure — no live positions",
        "body": (
            "No live positions CSV found, so per-currency exposure can't be computed. With a book loaded "
            "this shows a currency lookthrough (FX futures → their economic currency; equities → their "
            "underlying-country currencies). No fabricated number."
        ),
    }


def fx_tilt_summary(panel: dict) -> str:
    """One-line decision read of the carry tilt (before/after), or a fallback."""
    tilt = (panel.get("tilt_detail") or {}).get("tilt") or {}
    if tilt.get("rows"):
        before = tilt.get("before") or {}
        after = tilt.get("after") or {}
        return (
            f"Annual carry before → after: ${before.get('annual_carry_usd', 0):,.0f} → "
            f"${after.get('annual_carry_usd', 0):,.0f}  "
            f"({tilt.get('carry_impact_bps', 0):+.0f}bps · {tilt.get('hedge_deviation_pct', 0) * 100:.0f}% "
            "deviation from the hedge-optimal)"
        )
    return panel.get("tilt_thesis", "") or "No carry tilt available."


# --------------------------------------------------------------------------- #
# Rendering (thin)
# --------------------------------------------------------------------------- #


def _render_panel_content(panel: dict, exp: dict) -> None:
    """The three input cards side by side + the full-width decision card."""
    if not panel["available"]:
        ui.label("No cached FX hedge allocation found.").classes("text-subtitle2")
        ui.label(
            "Run `fx-hedge-report` (or trigger a refresh) to compute the target allocation, then reload."
        ).classes("text-caption pm-muted")
        return

    badge = f"data: {panel['data_mode']}" + (f" · {panel['source']}" if panel["source"] else "")
    ui.label(badge).classes("text-caption pm-muted")

    with ui.row().classes("w-full gap-3 items-stretch wrap"):
        # 1) Baseline hedging mix
        with ui.column().classes("grow").style("min-width: 340px"):
            with ui.card().classes("w-full pm-card"):
                ui.label("1 · Baseline hedging mix").classes("text-subtitle2")
                if panel["thesis"]:
                    ui.label(panel["thesis"]).classes("text-caption")
                headers, rows = panel["mix"]
                if rows:
                    _ui_table(headers, rows)
                if panel["headline"]:
                    ui.label("   ".join(f"{k}: {v}" for k, v in panel["headline"].items())).classes(
                        "text-caption pm-muted"
                    )

        # 2) Current FX exposure
        with ui.column().classes("grow").style("min-width: 300px"):
            with ui.card().classes("w-full pm-card"):
                if exp["available"]:
                    ui.label("2 · Current FX exposure").classes("text-subtitle2")
                    _ui_table(exp["headers"], exp["rows"])
                    top = exp["by_currency"][0]
                    method = "country lookthrough" if exp.get("lookthrough") else "listing currency"
                    ui.label(
                        f"Largest: {top[0]} ${top[1]:,.0f} ({top[2] * 100:.0f}%) of ${exp['total_usd']:,.0f} gross "
                        f"· via {method}. DM-EUME folds GBP/CHF into EUR; uncovered symbols fall back to listing ccy."
                    ).classes("text-caption pm-muted")
                else:
                    ph = fx_exposure_placeholder()
                    ui.label("2 · " + ph["title"]).classes("text-subtitle2")
                    ui.label(ph["body"]).classes("text-caption").style("color:#f3b34d")

        # 3) Carry
        with ui.column().classes("grow").style("min-width: 240px"):
            with ui.card().classes("w-full pm-card"):
                ui.label("3 · Carry (ON-rate approx)").classes("text-subtitle2")
                ch, cr = panel["carry"]
                if cr:
                    _ui_table(ch, cr)
                else:
                    ui.label("No carry ranking available.").classes("text-caption pm-muted")
                ui.label(
                    "Rate-differential approximation vs USD — not futures-implied."
                ).classes("text-caption pm-muted")

    # → Decision: the join the reader previously had to do in their head.
    decision = build_fx_decision(panel, exp)
    with ui.card().classes("w-full pm-card"):
        ui.label("→ Decision · target vs current FX-futures book").classes("text-subtitle2")
        if decision["available"]:
            headers, rows = fx_decision_table(decision)
            _ui_table(headers, rows)
            at_line = at_target_line(decision)
            if at_line:
                ui.label(f"Book mix at target: {at_line}").classes("text-caption")
            ui.label(decision["note"]).classes("text-caption pm-muted")
        else:
            ui.label(
                "Needs both a cached hedge target and live positions — the gap table stays empty rather "
                "than fabricated."
            ).classes("text-caption pm-muted")
        ui.separator()
        ui.label("Carry tilt (explorer)").classes("text-subtitle2")
        ui.label(fx_tilt_summary(panel)).classes("text-caption")
        theaders, trows = panel["tilt_table"]
        if trows:
            _ui_table(theaders, trows)
        ui.label(
            "A tilt EXPLORER, not a carry optimizer: carry is rate-approximated from configured overnight-rate "
            "differentials vs USD. Read-only — no order, no size."
        ).classes("text-caption pm-muted")


def _fx_ai_builder(cache: dict):
    """AI Plus initial messages grounded on the live FX hedge mix + exposure + gap.

    Reuses the panel/exposure the module already built (``cache``) instead of
    re-reading artifacts; falls back to building when the cache is cold.
    """
    panel = cache.get("panel")
    if panel is None:
        try:
            panel = build_fx_panel()
        except Exception:  # noqa: BLE001 — AI pane must still open if the panel build fails
            panel = {"available": False}
    exp = cache.get("exp")
    if exp is None:
        try:
            exp = build_fx_exposure()
        except Exception:  # noqa: BLE001 — grounding is best-effort
            exp = {"available": False}

    mix_lines = "; ".join(
        f"{r[0]} {r[3]}ct (β{r[2]}, carry {r[5]}bps)" for r in (panel.get("mix", (None, []))[1] or [])
    ) or "no cached allocation"
    exp_line = (
        "; ".join(f"{c} {w * 100:.0f}%" for c, _u, w in exp["by_currency"][:6]) if exp.get("available") else "not available"
    )
    decision = build_fx_decision(panel, exp)
    gap_line = (
        "; ".join(f"{r['ccy']} Δ{r['gap_usd']:+,.0f}$" for r in decision["rows"][:6])
        if decision["available"] else "not available"
    )
    framing = (
        "You are an FX-hedge RESEARCH partner for an SGD-based book. The baseline is a USD/SGD hedge target "
        "across CME FX futures (EUR/GBP/AUD/JPY/CNH). Analyze whether to TILT the mix given carry, the book's "
        "FX exposure, and the gap between the held FX futures and the target legs — e.g. is a higher-carry "
        "currency like AUD worth overweighting, and at what basis-risk cost? Be explicit that carry here is a "
        "rate-differential approximation, not futures-implied. You may call read-only tools (get_fx_decision "
        "for the live target-vs-current gap, get_portfolio_book, regime, price-trend) to support the read. "
        "Never output an order, contract count to execute, or size."
    )
    ask = (
        f"Current hedge legs: {mix_lines}. Book FX exposure (lookthrough): {exp_line}. "
        f"Gap to target (held FX futures vs target legs): {gap_line}. "
        f"Tilt read: {fx_tilt_summary(panel)}. "
        "Give: (1) a short macro/carry read; (2) which leg(s) you'd tilt and why (or why not), in light of the "
        "book's existing currency exposure and the gaps; (3) the main basis-risk / what would change your mind. "
        "No orders, no sizes."
    )
    return module_ai_initial(framing, ask)


def render_fx_hedge_module() -> None:
    """Render the FX Hedge decision panel + the AI Plus dialog (async populate)."""
    ui.label("FX Hedge").classes("text-subtitle1")
    ui.label(
        "A decision panel — baseline hedge mix + FX exposure + carry → target-vs-current gap + tilt. "
        "Not idea-cards; read-only, never orders."
    ).classes("text-caption pm-muted")

    cache: dict = {"panel": None, "exp": None}
    body = ui.column().classes("w-full gap-3")
    with body:
        ui.label("Loading FX panel…").classes("text-caption pm-muted")

    async def _populate() -> None:
        try:
            panel = await asyncio.to_thread(build_fx_panel)
            exp = await asyncio.to_thread(build_fx_exposure)
        except Exception as exc:  # noqa: BLE001 — surface, never crash the page
            body.clear()
            with body:
                ui.label(f"FX hedge unavailable: {type(exc).__name__}: {str(exc)[:160]}").classes(
                    "text-caption pm-muted"
                )
            return
        cache["panel"], cache["exp"] = panel, exp
        body.clear()
        with body:
            _render_panel_content(panel, exp)

    ui.timer(0.1, _populate, once=True)

    render_ai_pane(
        lambda: _fx_ai_builder(cache),
        intro="Opt-in: the AI analyzes the hedge mix + exposure gap + carry (and may call read-only tools) to "
              "reason about a tilt. After a brief, type feedback to refine — analysis only, never orders.",
        generate_label="Analyze FX tilt",
    )
