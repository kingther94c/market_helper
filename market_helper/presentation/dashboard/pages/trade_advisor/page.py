"""`/advisor` registration + the v2 multi-module surface.

Four purpose-built module tabs — **Option Strategy · FX Hedge · Tactical Trade
Ideas · Roll & Carry Calendar** — each owning its own inputs (there is no global
input panel and no single Run). Option + Tactical are idea-shaped and share the
decision journal + a flagged-ideas Inbox; FX Hedge (a decision panel) and Roll &
Carry (a holdings-derived calendar) deliberately do not.

See ``docs/architecture/devplans/trade_advisor.md`` §5.
"""
from __future__ import annotations

from nicegui import ui

from market_helper.application.trade_advisor import default_decision_journal
from market_helper.presentation.dashboard.pages.trade_advisor.cards import _render_inbox
from market_helper.presentation.dashboard.pages.trade_advisor.modules.fx_hedge import render_fx_hedge_module
from market_helper.presentation.dashboard.pages.trade_advisor.modules.option import render_option_module
from market_helper.presentation.dashboard.pages.trade_advisor.modules.roll import render_roll_module
from market_helper.presentation.dashboard.pages.trade_advisor.modules.tactical import render_tactical_module
from market_helper.presentation.dashboard.shell import app_shell

_REGISTERED = False


def register_trade_advisor_page() -> None:
    """Register the /advisor multi-module page (idempotent)."""
    global _REGISTERED
    if _REGISTERED:
        return
    _REGISTERED = True

    @ui.page("/advisor")
    def advisor_page() -> None:
        # The shared shell provides cross-surface nav + injects the dashboard styles
        # the page's `pm-*` classes rely on.
        with app_shell(active="advisor"):
            ui.label("Trade Advisor").classes("text-h5")
            ui.label(
                "Four purpose-built modules · each owns its inputs · read-only research, never orders."
            ).classes("text-caption pm-muted")

            # Option + Tactical share the journal + a flagged-ideas Inbox; FX + Roll don't.
            journal = default_decision_journal()
            inbox_holder: dict = {}

            def refresh_inbox() -> None:
                box = inbox_holder.get("box")
                if box is not None:
                    _render_inbox(box, journal)

            with ui.tabs().classes("w-full") as tabs:
                t_opt = ui.tab("Option Strategy")
                t_fx = ui.tab("FX Hedge")
                t_tac = ui.tab("Tactical Trade Ideas")
                t_roll = ui.tab("Roll & Carry Calendar")
            with ui.tab_panels(tabs, value=t_opt).classes("w-full"):
                with ui.tab_panel(t_opt):
                    render_option_module(journal, refresh_inbox)
                with ui.tab_panel(t_fx):
                    render_fx_hedge_module()
                with ui.tab_panel(t_tac):
                    render_tactical_module(journal, refresh_inbox)
                with ui.tab_panel(t_roll):
                    render_roll_module()

            ui.separator()
            ui.label("Flagged ideas · Option + Tactical").classes("text-subtitle1")
            inbox_holder["box"] = ui.column().classes("w-full")
            refresh_inbox()
