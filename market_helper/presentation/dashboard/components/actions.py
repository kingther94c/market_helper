from __future__ import annotations

from collections.abc import Callable

from nicegui import ui

from .common import render_status_badge, render_status_card


def render_action_card(
    *,
    title: str,
    subtitle: str,
    status: str,
    message: str,
    progress_summary: str,
    last_output_path: str,
    body: Callable[[], None],
) -> None:
    # P6: drop the pre-token `bg-slate-50` styling in favor of the shared `.pm-card`
    # primitive so action cards match the rest of the dashboard chrome.
    with ui.card().classes("grow basis-[420px] p-4 pm-card shadow-none"):
        with ui.row().classes("w-full items-center justify-between"):
            ui.label(title).classes("text-subtitle1")
            render_status_badge(status)
        ui.label(subtitle).classes("text-caption pm-muted")
        with ui.row().classes("w-full gap-3 wrap my-3"):
            render_status_card(title="Status", value=message)
            render_status_card(title="Progress", value=progress_summary)
            render_status_card(title="Last Output", value=last_output_path)
        body()

