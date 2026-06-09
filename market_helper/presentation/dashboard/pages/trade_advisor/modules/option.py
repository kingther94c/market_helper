"""Option Strategy module — Rule-based | AI Plus (the canonical two-pane).

- **Rule-based** (left): scans current holdings + the security universe with the
  preset option engine. Two screens (devplan §5.1): a **zero-cost collar** over
  *holdings* (hedge) and **premium shorts** (sell call/put) over the *universe*
  (income). Inputs are scoped to options — no global panel. Ideas flow to the
  journal/Inbox (this module is idea-shaped).
- **AI Plus** (right): given holdings + the interest universe, the AI opens the
  search, calls read-only tools to judge whether an opportunity is good enough,
  and refines on feedback. Read-only, never orders.

The scan universe comes from ``configs/security_universe.csv`` (EQ rows), not the
old hardcoded 14-name list.
"""
from __future__ import annotations

import asyncio

from nicegui import ui

from market_helper.application.trade_advisor import current_regime_seed

from ..ai_pane import module_ai_initial, render_ai_pane
from ..cards import _render_module
from ..inputs import (
    CONFIDENCE_OPTIONS,
    REGIME_OPTIONS,
    AdvisorInputs,
    build_run_context,
    load_option_universe,
)


def _make_option_ai_builder(sym_sel, held_sel):
    """Factory: an AI-pane initial_builder that reads the live universe/held inputs."""

    def _builder():
        syms = list(sym_sel.value or [])
        held = list(held_sel.value or [])
        framing = (
            "You are an options RESEARCH partner. Given my holdings and a scan universe, evaluate which names "
            "are worth an option structure under two screens: (a) a zero-cost / protective COLLAR over names I "
            "HOLD (hedge the downside), and (b) SELLING premium (covered call / cash-secured put / defined-risk "
            "spread) across the universe where it's worth it. Judge whether each opportunity is good enough on "
            "IV level, liquidity, and event risk. You may call read-only tools (price-trend, regime) to support "
            "the read. Frame premium sales by their tail/assignment risk, never as a 'yield'. Never output an "
            "order, contract count to execute, or size."
        )
        ask = (
            f"Holdings: {', '.join(held) or '(none specified)'}. Scan universe: {', '.join(syms) or '(none)'}. "
            "For the most attractive few names, say: the structure, the one-line reason, the main risk, and your "
            "confidence. Separate hedge (collar) ideas from premium-income ideas. No orders, no sizes."
        )
        return module_ai_initial(framing, ask)

    return _builder


def render_option_module(journal, refresh_inbox) -> None:
    """Render the Option Strategy two-pane surface."""
    ui.label("Option Strategy").classes("text-subtitle1")
    ui.label(
        "Rule-based scan (collar over holdings · premium shorts over the security universe) on the left; "
        "AI Plus opens the search on the right. Read-only ideas, never orders."
    ).classes("text-caption pm-muted")

    seed = current_regime_seed()
    universe = load_option_universe()
    default_syms = [s for s in ("SPY", "QQQ", "NVDA", "AAPL") if s in universe] or universe[:4]
    default_held = [s for s in ("SPY",) if s in universe]

    with ui.row().classes("w-full gap-4 items-start wrap"):
        # ---- Rule-based pane ----
        with ui.column().classes("grow gap-2").style("min-width: 440px"):
            with ui.card().classes("w-full pm-card"):
                ui.label("Rule-based · scan holdings + security universe").classes("text-subtitle2")
                sym_sel = ui.select(universe, value=default_syms, multiple=True, label="Scan universe").props(
                    "use-chips"
                ).classes("w-full")
                held_sel = ui.select(universe, value=default_held, multiple=True, label="Treat as held (100 sh)").props(
                    "use-chips"
                ).classes("w-full")
                aum_in = ui.number("AUM (USD)", value=250_000, min=0, step=10_000, format="%.0f").classes("w-full")
                regime_sel = ui.select(REGIME_OPTIONS, value=seed.regime, label="Regime").classes("w-full")
                conf_sel = ui.select(CONFIDENCE_OPTIONS, value=seed.confidence, label="Confidence").classes("w-full")
                crisis_sw = ui.switch("Crisis overlay", value=seed.crisis)
                if seed.is_seeded:
                    ui.label(
                        f"Regime auto-seeded: {seed.regime}"
                        f"{' · ' + seed.confidence if seed.confidence else ''}"
                        f"{' · stress overlay' if seed.crisis else ''} (override above)"
                    ).classes("text-caption pm-muted")
                rv_sw = ui.switch("Fetch realized vol (slower)", value=False)
                earn_sw = ui.switch("Check earnings (slower)", value=False)
                port_sw = ui.switch("Use my portfolio (live positions)", value=True)
                run_btn = ui.button("Scan options")
                status = ui.label("").classes("text-caption pm-muted")
            results = ui.column().classes("w-full gap-3")
            with results:
                ui.label("Scan to populate collar (holdings) + premium-short (universe) ideas.").classes(
                    "text-caption pm-muted"
                )

        # ---- AI Plus pane ----
        with ui.column().classes("grow gap-2").style("min-width: 360px"):
            render_ai_pane(
                _make_option_ai_builder(sym_sel, held_sel),
                intro="Opt-in: given your holdings + universe, the AI evaluates which names are worth a collar or "
                      "a premium sale (calling read-only tools to judge IV / trend / regime). After a brief, type "
                      "feedback to refine — analysis only, never orders.",
                generate_label="Find opportunities (AI)",
            )

    async def run() -> None:
        run_btn.disable()
        status.text = "Scanning…"
        inp = AdvisorInputs(
            symbols=list(sym_sel.value or []),
            held=list(held_sel.value or []),
            aum=float(aum_in.value or 0),
            regime=regime_sel.value or "",
            confidence=conf_sel.value or "",
            crisis=bool(crisis_sw.value),
            fetch_realized=bool(rv_sw.value),
            check_earnings=bool(earn_sw.value),
        )
        if not inp.symbols and not port_sw.value:
            status.text = "Pick at least one symbol (or enable “use my portfolio”)."
            run_btn.enable()
            return
        context, book_note = build_run_context(inp, use_portfolio=bool(port_sw.value))
        try:
            from market_helper.trade_advisor.adapters.option import OptionAdvisorPlugin

            res = await asyncio.to_thread(
                lambda: OptionAdvisorPlugin().produce(
                    context, fetch_realized=inp.fetch_realized, fetch_events=inp.check_earnings
                )
            )
        except Exception as exc:  # noqa: BLE001 — surface, don't crash the page
            status.text = f"Failed: {type(exc).__name__}: {exc}"
            run_btn.enable()
            return
        _render_module(
            results, res.suggestions, journal, refresh_inbox,
            empty_note="No option ideas for these inputs.",
        )
        status.text = f"Done · {len(res.suggestions)} ideas · data: {res.data_mode or 'n/a'}{book_note}"
        run_btn.enable()

    run_btn.on_click(run)
