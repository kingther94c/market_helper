"""`/advisor` registration + page lifecycle.

Owns the NiceGUI page handler, the per-page decision journal + Inbox wiring, and
the Rule-based / AI+ tab split. The service singleton lives here and is passed
explicitly into the tab renderers (no shared cross-module global).
"""
from __future__ import annotations

from nicegui import ui

from market_helper.application.trade_advisor import TradeAdvisorService, default_decision_journal
from market_helper.presentation.dashboard.shell import app_shell
from market_helper.presentation.dashboard.pages.trade_advisor.ai import _render_ai_tab
from market_helper.presentation.dashboard.pages.trade_advisor.cards import _render_inbox
from market_helper.presentation.dashboard.pages.trade_advisor.rule_based import _render_rule_based_tab

_REGISTERED = False
_SERVICE: TradeAdvisorService | None = None


def register_trade_advisor_page(*, registry=None) -> None:
    """Register the /advisor interactive page (idempotent)."""
    global _REGISTERED, _SERVICE
    if registry is not None or _SERVICE is None:
        _SERVICE = TradeAdvisorService(registry=registry)
    if _REGISTERED:
        return
    _REGISTERED = True

    @ui.page("/advisor")
    def advisor_page() -> None:
        # The shared shell provides the cross-surface nav (so the one-way
        # "← Portfolio dashboard" link is gone) and injects the dashboard styles
        # the page's `pm-*` classes rely on.
        with app_shell(active="advisor"):
            ui.label("Trade Advisor").classes("text-h5")
            ui.label("Read-only ideas, not orders. Explore within bounded controls.").classes("text-caption pm-muted")

            journal = default_decision_journal()
            inbox_box = ui.column().classes("w-full")

            def refresh_inbox() -> None:
                _render_inbox(inbox_box, journal)

            refresh_inbox()

            # Two parallel surfaces, selectable via tab: the deterministic rule-based
            # advisor (default) and the opt-in AI+ synthesis layer.
            with ui.tabs().classes("w-full") as tabs:
                rb_tab = ui.tab("Rule-based")
                ai_tab = ui.tab("AI+")
            with ui.tab_panels(tabs, value=rb_tab).classes("w-full"):
                with ui.tab_panel(rb_tab):
                    _render_rule_based_tab(journal, refresh_inbox, _SERVICE)
                with ui.tab_panel(ai_tab):
                    _render_ai_tab(_SERVICE)
