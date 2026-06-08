"""`/advisor` registration + page lifecycle (the multi-module Advisor cockpit).

Owns the NiceGUI page handler, the per-page decision journal + cross-module Inbox
wiring, and the cockpit (Option Strategy / FX Hedge Tilt / Tactical Trade Ideas /
Roll & Carry Calendar tabs). The service singleton lives here and is passed
explicitly into the cockpit renderer (no shared cross-module global).
"""
from __future__ import annotations

from nicegui import ui

from market_helper.application.trade_advisor import TradeAdvisorService, default_decision_journal
from market_helper.presentation.dashboard.shell import app_shell
from market_helper.presentation.dashboard.pages.trade_advisor.cards import _render_inbox
from market_helper.presentation.dashboard.pages.trade_advisor.cockpit import render_cockpit

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
        # The shared shell provides the cross-surface nav and injects the dashboard
        # styles the page's `pm-*` classes rely on.
        with app_shell(active="advisor"):
            ui.label("Trade Advisor").classes("text-h5")
            ui.label(
                "Multi-module advisory cockpit · read-only ideas, never orders · bounded controls."
            ).classes("text-caption pm-muted")

            journal = default_decision_journal()
            inbox_box = ui.column().classes("w-full")

            def refresh_inbox() -> None:
                _render_inbox(inbox_box, journal)

            refresh_inbox()
            render_cockpit(journal, refresh_inbox, _SERVICE)
