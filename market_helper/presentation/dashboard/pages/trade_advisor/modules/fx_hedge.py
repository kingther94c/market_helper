"""FX Hedge module — an independent **decision panel**, not idea-cards.

FX Hedge is a continuous allocation decision, so it deliberately does NOT use the
Promote/Watch/Dismiss idea contract or the journal. It is built from three parts
(devplan §5.2):

1. **Baseline hedging mix** — Portfolio Monitor's FX-hedge target artifact (per-ccy
   target contracts / betas / indicative carry), read cached (no network).
2. **Current FX exposure** — a currency lookthrough of the book. Not yet computed
   in-repo (``security_universe.csv`` has no currency column), so this shows an
   honest placeholder rather than a fabricated weight until the lookthrough lands.
3. **Carry** — per-ccy carry (ON-rate differential approximation) → the tilt
   decision (e.g. "AUD carry is attractive → add AUD weight"), with the existing
   before/after exposure + carry-impact + hedge-deviation view.

Plus an **AI Plus** dialog over the same three inputs. The panel builders are pure
and unit-tested; the ``ui.*`` wrappers stay thin.
"""
from __future__ import annotations

from nicegui import ui

from market_helper.trade_advisor.contracts import AdvisorContext

from ..ai_pane import module_ai_initial, render_ai_pane
from ..cards import _ui_table, fx_alloc_table, fx_carry_table, fx_carry_tilt_table


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
        "carry": fx_carry_table(tilt.detail) if tilt else (["Ccy", "Carry bps", "ON %"], []),
        "tilt_detail": (tilt.detail if tilt else {}),
        "tilt_thesis": tilt.thesis if tilt else "",
        "tilt_headline": dict(tilt.headline_metrics) if tilt else {},
        "tilt_table": fx_carry_tilt_table(tilt.detail) if tilt else (["Ccy"], []),
    }
    return panel


def build_fx_exposure() -> dict:
    """Render-ready per-currency exposure of the live book (coarse lookthrough).

    FX futures count toward the foreign currency they track; everything else toward
    its quote currency (options excluded). ``available`` is False when no positions
    are found — the caller then shows the placeholder.
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
    }


def fx_exposure_placeholder() -> dict:
    """Shown only when no live positions are found — honest, no fabricated number."""
    return {
        "title": "Current FX exposure — no live positions",
        "body": (
            "No live positions CSV found, so per-currency exposure can't be computed. With a book loaded "
            "this shows a coarse currency lookthrough (FX futures → their economic currency; everything "
            "else → quote currency). No fabricated number."
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


def _render_decision_panel() -> None:
    try:
        panel = build_fx_panel()
    except Exception as exc:  # noqa: BLE001 — surface, never crash the page
        ui.label(f"FX hedge unavailable: {type(exc).__name__}: {str(exc)[:160]}").classes("text-caption pm-muted")
        return

    if not panel["available"]:
        ui.label("No cached FX hedge allocation found.").classes("text-subtitle2")
        ui.label(
            "Run `fx-hedge-report` (or trigger a refresh) to compute the target allocation, then reload."
        ).classes("text-caption pm-muted")
        return

    badge = f"data: {panel['data_mode']}" + (f" · {panel['source']}" if panel["source"] else "")
    ui.label(badge).classes("text-caption pm-muted")

    # 1) Baseline hedging mix
    with ui.card().classes("w-full pm-card"):
        ui.label("1 · Baseline hedging mix").classes("text-subtitle2")
        if panel["thesis"]:
            ui.label(panel["thesis"]).classes("text-caption")
        headers, rows = panel["mix"]
        if rows:
            _ui_table(headers, rows)
        if panel["headline"]:
            ui.label("   ".join(f"{k}: {v}" for k, v in panel["headline"].items())).classes("text-caption pm-muted")

    # 2) Current FX exposure — a coarse currency lookthrough of the live book.
    exp = build_fx_exposure()
    with ui.card().classes("w-full pm-card"):
        if exp["available"]:
            ui.label("2 · Current FX exposure").classes("text-subtitle2")
            _ui_table(exp["headers"], exp["rows"])
            top = exp["by_currency"][0]
            ui.label(
                f"Largest: {top[0]} ${top[1]:,.0f} ({top[2] * 100:.0f}%) of ${exp['total_usd']:,.0f} gross. "
                "Coarse: listing/settlement currency (FX futures → economic ccy); a USD-listed ex-US fund still "
                "counts as USD — deeper risk-currency lookthrough pending."
            ).classes("text-caption pm-muted")
        else:
            ph = fx_exposure_placeholder()
            ui.label("2 · " + ph["title"]).classes("text-subtitle2")
            ui.label(ph["body"]).classes("text-caption").style("color:#f3b34d")

    # 3) Carry → tilt decision
    with ui.card().classes("w-full pm-card"):
        ui.label("3 · Carry → tilt decision").classes("text-subtitle2")
        ui.label(fx_tilt_summary(panel)).classes("text-caption")
        headers, rows = panel["tilt_table"]
        if rows:
            _ui_table(headers, rows)
        else:
            ch, cr = panel["carry"]
            if cr:
                _ui_table(ch, cr)
        ui.label(
            "A tilt EXPLORER, not a carry optimizer: carry is rate-approximated from configured overnight-rate "
            "differentials vs USD. Read-only — no order, no size."
        ).classes("text-caption pm-muted")


def _fx_ai_builder():
    """AI Plus initial messages grounded on the live FX hedge mix + carry."""
    try:
        panel = build_fx_panel()
    except Exception:  # noqa: BLE001 — AI pane must still open if the panel build fails
        panel = {"available": False}
    mix_lines = "; ".join(
        f"{r[0]} {r[3]}ct (β{r[2]}, carry {r[5]}bps)" for r in (panel.get("mix", (None, []))[1] or [])
    ) or "no cached allocation"
    try:
        exp = build_fx_exposure()
        exp_line = "; ".join(f"{c} {w * 100:.0f}%" for c, _u, w in exp["by_currency"][:6]) if exp["available"] else "not available"
    except Exception:  # noqa: BLE001 — grounding is best-effort
        exp_line = "not available"
    framing = (
        "You are an FX-hedge RESEARCH partner for an SGD-based book. The baseline is a USD/SGD hedge target "
        "across CME FX futures (EUR/GBP/AUD/JPY/CNH). Analyze whether to TILT the mix given carry and (when "
        "known) the book's FX exposure — e.g. is a higher-carry currency like AUD worth overweighting, and at "
        "what basis-risk cost? Be explicit that carry here is a rate-differential approximation, not "
        "futures-implied. You may call read-only tools (regime, price-trend) to support the read. Never output "
        "an order, contract count to execute, or size."
    )
    ask = (
        f"Current hedge legs: {mix_lines}. Book FX exposure (coarse): {exp_line}. "
        f"Tilt read: {fx_tilt_summary(panel)}. "
        "Give: (1) a short macro/carry read; (2) which leg(s) you'd tilt and why (or why not), in light of the "
        "book's existing currency exposure; (3) the main basis-risk / what would change your mind. No orders, no sizes."
    )
    return module_ai_initial(framing, ask)


def render_fx_hedge_module() -> None:
    """Render the FX Hedge decision panel + the AI Plus dialog."""
    ui.label("FX Hedge").classes("text-subtitle1")
    ui.label(
        "A decision panel — baseline hedge mix + FX exposure + carry → tilt. Not idea-cards; "
        "read-only, never orders."
    ).classes("text-caption pm-muted")
    _render_decision_panel()
    render_ai_pane(
        _fx_ai_builder,
        intro="Opt-in: the AI analyzes the hedge mix + carry (and may call read-only tools) to reason about a "
              "tilt. After a brief, type feedback to refine — analysis only, never orders.",
        generate_label="Analyze FX tilt",
    )
