"""The deterministic, no-AI advisor tab (inputs → run → ranked cards)."""
from __future__ import annotations

import asyncio

from nicegui import ui

from market_helper.application.trade_advisor import TradeAdvisorService, current_regime_seed
from market_helper.trade_advisor.journal import DecisionJournal
from market_helper.presentation.dashboard.pages.trade_advisor.cards import _render_results
from market_helper.presentation.dashboard.pages.trade_advisor.inputs import (
    CONFIDENCE_OPTIONS,
    LIQUID_UNIVERSE,
    REGIME_OPTIONS,
    AdvisorInputs,
    build_run_context,
    option_run_params,
)


def _render_rule_based_tab(journal: DecisionJournal, refresh_inbox, service: TradeAdvisorService) -> None:
    """The deterministic, no-AI advisor surface (inputs → run → ranked cards)."""
    with ui.row().classes("w-full gap-4 items-start no-wrap"):
        with ui.card().classes("p-4").style("min-width: 300px"):
            ui.label("Inputs").classes("text-subtitle1")
            sym_sel = ui.select(LIQUID_UNIVERSE, value=["SPY", "QQQ"], multiple=True, label="Universe").props("use-chips").classes("w-full")
            held_sel = ui.select(LIQUID_UNIVERSE, value=["SPY"], multiple=True, label="Treat as held (100 sh)").props("use-chips").classes("w-full")
            aum_in = ui.number("AUM (USD)", value=250_000, min=0, step=10_000, format="%.0f").classes("w-full")
            seed = current_regime_seed()  # default the regime controls to the live snapshot (overridable)
            regime_sel = ui.select(REGIME_OPTIONS, value=seed.regime, label="Regime").classes("w-full")
            conf_sel = ui.select(CONFIDENCE_OPTIONS, value=seed.confidence, label="Confidence").classes("w-full")
            crisis_sw = ui.switch("Crisis overlay", value=seed.crisis)
            if seed.is_seeded:
                ui.label(
                    f"Regime auto-seeded from latest snapshot: {seed.regime}"
                    f"{' · ' + seed.confidence if seed.confidence else ''}"
                    f"{' · stress overlay' if seed.crisis else ''} (override above)"
                ).classes("text-caption pm-muted")
            rv_sw = ui.switch("Fetch realized vol (slower)", value=False)
            earnings_sw = ui.switch("Check earnings (slower)", value=False)
            portfolio_sw = ui.switch("Use my portfolio (live positions)", value=True)
            run_btn = ui.button("Run advisor")
            status = ui.label("").classes("text-caption pm-muted")

        results_box = ui.column().classes("grow gap-3")

    async def run() -> None:
        run_btn.disable()
        status.text = "Running…"
        inp = AdvisorInputs(
            symbols=list(sym_sel.value or []),
            held=list(held_sel.value or []),
            aum=float(aum_in.value or 0),
            regime=regime_sel.value or "",
            confidence=conf_sel.value or "",
            crisis=bool(crisis_sw.value),
            fetch_realized=bool(rv_sw.value),
            check_earnings=bool(earnings_sw.value),
        )
        if not inp.symbols:
            status.text = "Pick at least one symbol."
            run_btn.enable()
            return
        context, book_note = build_run_context(inp, use_portfolio=bool(portfolio_sw.value))
        try:
            run_result = await asyncio.to_thread(
                service.run, context, advisors=None, params_by_advisor=option_run_params(inp)
            )
        except Exception as exc:  # noqa: BLE001 — surface, don't crash the page
            status.text = f"Failed: {type(exc).__name__}: {exc}"
            run_btn.enable()
            return
        _render_results(results_box, run_result, journal, refresh_inbox)
        status.text = f"Done · {len(run_result.all_suggestions())} ideas{book_note}"
        run_btn.enable()

    run_btn.on_click(run)
