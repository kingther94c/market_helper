"""The slide-over "Operate" panel for `/portfolio` (P7).

Holds the granular report controls, the per-action console + forms, the artifact
paths form, the recent-runs history, and the progress log — moved off the
first-paint into a right-edge drawer toggled by the app-bar Operate button.
Action callbacks are read off ``state`` (stashed by :mod:`page`).
"""
from __future__ import annotations

import asyncio
from pathlib import Path

from nicegui import ui

from market_helper.presentation.dashboard.components import render_action_card
from market_helper.presentation.dashboard.pages.portfolio_monitor.actions import (
    _ACTION_PRETTY_NAMES,
    _action_progress_summary,
    _merged_action_status,
    _regime_progress_summary,
)
from market_helper.presentation.dashboard.pages.portfolio_monitor.routes import _served_artifact_url
from market_helper.presentation.dashboard.pages.portfolio_monitor.state import (
    PortfolioPageState,
    _JOB_HISTORY_MAX_ENTRIES,
    _format_progress_event,
)


def _render_operate_drawer(state: PortfolioPageState) -> None:
    """Slide-over drawer holding granular controls, paths, and logs (P7).

    Toggled by the app-bar Operate button via `body.classList.toggle('pm-drawer-open')`
    so opening/closing is purely client-side; rendered content still binds to `state`
    so form changes round-trip through the existing `@ui.refreshable` pipeline.
    """
    backdrop = ui.element("div").classes("pm-drawer-backdrop")
    backdrop.on(
        "click",
        lambda _: ui.run_javascript("document.body.classList.remove('pm-drawer-open');"),
    )
    with ui.element("aside").classes("pm-drawer"):
        with ui.element("div").classes("pm-drawer__header"):
            ui.label("Operate").classes("pm-drawer__title")
            close_btn = ui.button("×")
            close_btn.classes("pm-drawer__close").props("flat dense")
            close_btn.on(
                "click",
                lambda _: ui.run_javascript("document.body.classList.remove('pm-drawer-open');"),
            )
        with ui.element("div").classes("pm-drawer__body"):
            ui.label("Report Controls").classes("pm-drawer__section-title")
            _render_granular_buttons(state)
            ui.element("div").classes("pm-divider").style("border-top: 1px solid var(--border-soft); margin: 4px 0;")
            ui.label("Pipeline Actions").classes("pm-drawer__section-title")
            _render_action_console(state)
            ui.element("div").classes("pm-divider").style("border-top: 1px solid var(--border-soft); margin: 4px 0;")
            ui.label("Artifact Paths").classes("pm-drawer__section-title")
            _render_artifact_paths_form(state)
            ui.element("div").classes("pm-divider").style("border-top: 1px solid var(--border-soft); margin: 4px 0;")
            ui.label(f"Recent Runs (last {_JOB_HISTORY_MAX_ENTRIES})").classes("pm-drawer__section-title")
            _render_job_history(state)
            ui.element("div").classes("pm-divider").style("border-top: 1px solid var(--border-soft); margin: 4px 0;")
            ui.label("Progress Log").classes("pm-drawer__section-title")
            _render_logs(state)


def _state_is_busy(state: PortfolioPageState) -> bool:
    return state.is_loading or state.active_job is not None


def _render_granular_buttons(state: PortfolioPageState) -> None:
    """Granular Report Controls — moved into the operate drawer in P7."""
    load_report_data = getattr(state, "_load_report_data", None)
    reload_embedded_report = getattr(state, "_reload_embedded_report", None)
    run_action = getattr(state, "_run_action", None)
    is_busy = state.is_loading or state.active_job is not None
    with ui.row().classes("items-center gap-2 wrap"):
        load_button = ui.button(
            "Recompute Report Data",
            on_click=lambda: asyncio.create_task(load_report_data()) if load_report_data else None,
        ).props("color=primary outline dense no-caps")
        reload_button = ui.button(
            "Reload Embedded HTML",
            on_click=reload_embedded_report,
        ).props("outline color=primary dense no-caps")
        generate_button = ui.button(
            "Generate HTML Report",
            on_click=lambda: asyncio.create_task(run_action("combined")) if run_action else None,
        ).props("color=accent dense no-caps")
        if is_busy:
            load_button.props("disable")
            reload_button.props("disable")
            generate_button.props("disable")


def _render_action_console(state: PortfolioPageState) -> None:
    run_action = getattr(state, "_run_action", None)
    is_busy = state.is_loading or state.active_job is not None
    with ui.row().classes("w-full gap-4 wrap"):
        render_action_card(
            title="Refresh Pipeline",
            subtitle="Run live refresh, rebuild flex artifacts, reload report data, and regenerate HTML.",
            status=state.action_statuses["refresh"].status,
            message=state.action_statuses["refresh"].message,
            progress_summary=_action_progress_summary(state, "refresh"),
            last_output_path=state.action_statuses["refresh"].last_output_path,
            body=lambda: _render_action_button(run_action, "refresh", "Run Full Refresh", is_busy=is_busy),
        )
        render_action_card(
            title="Live Refresh",
            subtitle="Fetch latest live positions into the configured CSV artifact.",
            status=state.action_statuses["live"].status,
            message=state.action_statuses["live"].message,
            progress_summary=_action_progress_summary(state, "live"),
            last_output_path=state.action_statuses["live"].last_output_path,
            body=lambda: _render_live_action_form(state, run_action),
        )
        render_action_card(
            title="Flex Refresh",
            subtitle="Rebuild flex performance artifacts from local XML or live credentials.",
            status=state.action_statuses["flex"].status,
            message=state.action_statuses["flex"].message,
            progress_summary=_action_progress_summary(state, "flex"),
            last_output_path=state.action_statuses["flex"].last_output_path,
            body=lambda: _render_flex_action_form(state, run_action),
        )
        render_action_card(
            title="HTML Report",
            subtitle="Explicitly generate the self-contained HTML report artifact.",
            status=state.action_statuses["combined"].status,
            message=state.action_statuses["combined"].message,
            progress_summary=_action_progress_summary(state, "combined"),
            last_output_path=state.action_statuses["combined"].last_output_path,
            body=lambda: _render_action_button(run_action, "combined", "Generate HTML Report", is_busy=is_busy),
        )
        render_action_card(
            title="Regime Engine v2",
            subtitle="Run or refresh the standalone regime artifact consumed by the combined report.",
            status=_merged_action_status(state, "regime-run", "regime-refresh").status,
            message=_merged_action_status(state, "regime-run", "regime-refresh").message,
            progress_summary=_regime_progress_summary(state),
            last_output_path=_merged_action_status(state, "regime-run", "regime-refresh").last_output_path,
            body=lambda: _render_regime_action_form(state, run_action),
        )
        render_action_card(
            title="Reference Sync",
            subtitle="Refresh supporting reference artifacts used by the report data pipeline.",
            status=state.action_statuses["security-reference"].status,
            message=state.action_statuses["security-reference"].message,
            progress_summary=_action_progress_summary(state, "security-reference"),
            last_output_path=state.action_statuses["security-reference"].last_output_path,
            body=lambda: _render_reference_action_form(state, run_action),
        )


def _render_artifact_paths_form(state: PortfolioPageState) -> None:
    with ui.column().classes("w-full gap-3"):
        with ui.grid(columns=2).classes("w-full gap-3"):
            ui.input("Positions CSV").bind_value(state.artifact_form, "positions_csv_path").classes("w-full")
            ui.input("Performance output dir").bind_value(state.artifact_form, "performance_output_dir").classes("w-full")
            ui.input("Combined HTML output").bind_value(state.export_form, "output_path").classes("w-full")
            ui.input("Security reference CSV").bind_value(state.artifact_form, "security_reference_path").classes("w-full")
        with ui.expansion("More Paths", icon="tune", value=False).classes("w-full"):
            with ui.grid(columns=2).classes("w-full gap-3 p-2"):
                ui.input("Performance history").bind_value(state.artifact_form, "performance_history_path").classes("w-full")
                ui.input("Performance report CSV").bind_value(state.artifact_form, "performance_report_csv_path").classes("w-full")
                ui.input("Returns JSON").bind_value(state.artifact_form, "returns_path").classes("w-full")
                ui.input("Proxy JSON").bind_value(state.artifact_form, "proxy_path").classes("w-full")
                ui.input("Regime JSON").bind_value(state.artifact_form, "regime_path").classes("w-full")
                ui.input("Risk config YAML").bind_value(state.artifact_form, "risk_config_path").classes("w-full")
                ui.input("Allocation policy YAML").bind_value(state.artifact_form, "allocation_policy_path").classes("w-full")
                ui.input("Vol method").bind_value(state.artifact_form, "vol_method").classes("w-full")
                ui.input("Correlation assumption").bind_value(state.artifact_form, "inter_asset_corr").classes("w-full")


def _render_live_action_form(state: PortfolioPageState, run_action) -> None:
    with ui.column().classes("w-full gap-2"):
        ui.input("Output CSV").bind_value(state.live_form, "output_path").classes("w-full")
        with ui.grid(columns=2).classes("w-full gap-2"):
            ui.input("Host").bind_value(state.live_form, "host").classes("w-full")
            ui.input("Port").bind_value(state.live_form, "port").classes("w-full")
            ui.input("Client ID").bind_value(state.live_form, "client_id").classes("w-full")
            ui.input("Account ID").bind_value(state.live_form, "account_id").classes("w-full")
            ui.input("Timeout").bind_value(state.live_form, "timeout").classes("w-full")
            ui.input("As of").bind_value(state.live_form, "as_of").classes("w-full")
        _render_action_button(run_action, "live", "Run Live Refresh", is_busy=_state_is_busy(state))


def _render_flex_action_form(state: PortfolioPageState, run_action) -> None:
    with ui.column().classes("w-full gap-2"):
        ui.input("Output dir").bind_value(state.flex_form, "output_dir").classes("w-full")
        ui.input("Flex XML path").bind_value(state.flex_form, "flex_xml_path").classes("w-full")
        with ui.grid(columns=2).classes("w-full gap-2"):
            ui.input("Query ID").bind_value(state.flex_form, "query_id").classes("w-full")
            ui.input("Token").bind_value(state.flex_form, "token").classes("w-full")
            ui.input("From date").bind_value(state.flex_form, "from_date").classes("w-full")
            ui.input("To date").bind_value(state.flex_form, "to_date").classes("w-full")
            ui.input("Period").bind_value(state.flex_form, "period").classes("w-full")
            ui.input("XML output path").bind_value(state.flex_form, "xml_output_path").classes("w-full")
        _render_action_button(run_action, "flex", "Run Flex Refresh", is_busy=_state_is_busy(state))


def _render_regime_action_form(state: PortfolioPageState, run_action) -> None:
    with ui.column().classes("w-full gap-2"):
        ui.input("Regime JSON").bind_value(state.regime_form, "output_regime_path").classes("w-full")
        ui.input("Regime HTML").bind_value(state.regime_form, "output_html_path").classes("w-full")
        with ui.grid(columns=2).classes("w-full gap-2"):
            ui.input("Max age days").bind_value(state.regime_form, "max_age_days").classes("w-full")
            ui.checkbox("Force refresh").bind_value(state.regime_form, "force_refresh")
            ui.checkbox("Latest only").bind_value(state.regime_form, "latest_only")
        with ui.row().classes("gap-2 wrap"):
            _render_action_button(run_action, "regime-run", "Run Cached Regime", is_busy=_state_is_busy(state))
            _render_action_button(run_action, "regime-refresh", "Refresh Regime", is_busy=_state_is_busy(state))


def _render_reference_action_form(state: PortfolioPageState, run_action) -> None:
    with ui.column().classes("w-full gap-2"):
        ui.input("Security reference output").bind_value(
            state.reference_form, "security_reference_output_path"
        ).classes("w-full")
        ui.input("ETF symbols").bind_value(state.reference_form, "etf_symbols").classes("w-full")
        with ui.grid(columns=2).classes("w-full gap-2"):
            ui.input("ETF output path").bind_value(state.reference_form, "etf_output_path").classes("w-full")
            ui.input("API key").bind_value(state.reference_form, "api_key").classes("w-full")
        with ui.row().classes("gap-2 wrap"):
            _render_action_button(run_action, "security-reference", "Sync Security Reference", is_busy=_state_is_busy(state))
            _render_action_button(run_action, "etf", "Sync ETF Lookthrough", is_busy=_state_is_busy(state))


def _render_action_button(run_action, action_name: str, label: str, *, is_busy: bool = False) -> None:
    button = ui.button(
        label,
        on_click=(lambda: asyncio.create_task(run_action(action_name))) if run_action is not None else None,
    )
    if is_busy or run_action is None:
        button.props("disable")


def _render_logs(state: PortfolioPageState) -> None:
    with ui.column().classes("w-full gap-2"):
        with ui.column().classes("w-full gap-2 pm-log"):
            if not state.progress_sink.events:
                ui.label("No progress events yet.").classes("pm-muted")
                return
            for event in state.progress_sink.events[-20:]:
                detail = _format_progress_event(event)
                text = f"{event.label}: {detail}" if detail else event.label
                ui.label(text).classes("text-caption")


def _render_job_history(state: PortfolioPageState) -> None:
    """Render the recent-jobs ring buffer inside the operate drawer (P8)."""
    if not state.job_history:
        ui.label("No completed runs yet.").classes("pm-muted")
        return
    with ui.column().classes("w-full gap-1 pm-history"):
        for entry in reversed(state.job_history):
            chip_class = {
                "success": "pm-status-chip pm-status-success",
                "warning": "pm-status-chip pm-status-warning",
            }.get(entry.status, "pm-status-chip pm-status-error")
            pretty_action = _ACTION_PRETTY_NAMES.get(entry.action_name, entry.action_name)
            time_label = entry.finished_at.strftime("%H:%M:%S")
            duration_label = f"{entry.duration_seconds:.1f}s"
            with ui.element("div").classes("pm-history__row"):
                ui.label(time_label).classes("pm-history__time")
                ui.label(pretty_action).classes("pm-history__action")
                ui.label(entry.status.title()).classes(chip_class)
                ui.label(duration_label).classes("pm-history__duration")
            ui.label(entry.message).classes("pm-history__message text-caption pm-muted")
            if entry.output_path and entry.output_path != "n/a":
                output_path = Path(entry.output_path)
                served_url = _served_artifact_url(output_path)
                if served_url is not None:
                    ui.link("Open output", served_url, new_tab=True).classes(
                        "pm-history__link text-caption"
                    )
                else:
                    ui.label(entry.output_path).classes("pm-history__path text-caption pm-muted")
