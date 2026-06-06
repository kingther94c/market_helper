"""Always-visible page rendering for `/portfolio`.

Composition + header + toolbar + the Report/Artifacts tabs + the embedded HTML
report iframe + inline feedback + progress strip. The slide-over Operate panel
lives in :mod:`drawer`; orchestration callbacks are read off ``state`` (stashed
by :mod:`page`), so these renderers stay free of service wiring.
"""
from __future__ import annotations

import asyncio

from nicegui import ui

from market_helper.common.datetime_display import format_local_datetime
from market_helper.presentation.dashboard.components.common import render_status_card
from market_helper.presentation.dashboard.formatters import format_local_text, format_path
from market_helper.presentation.dashboard.shell import app_shell
from market_helper.presentation.dashboard.pages.portfolio_monitor.actions import (
    _ACTION_PRETTY_NAMES,
    _classify_warning,
    _progress_fraction,
)
from market_helper.presentation.dashboard.pages.portfolio_monitor.drawer import _render_operate_drawer
from market_helper.presentation.dashboard.pages.portfolio_monitor.routes import (
    _current_report_output_path,
    _served_artifact_url,
)
from market_helper.presentation.dashboard.pages.portfolio_monitor.state import (
    PortfolioPageState,
    _summarize_progress,
    _update_top_tab,
)


def _render_portfolio_page(state: PortfolioPageState) -> None:
    # The shared shell injects dashboard styles once and renders the
    # cross-surface nav; the portfolio chrome (sticky `.pm-app-bar`, progress
    # strip, operate drawer) renders inside it, behavior unchanged.
    with app_shell(active="portfolio"):
        _render_header(state)
        # P8: thin progress strip directly under the app-bar; only renders while
        # a job is in flight, with either a measurable fraction or an indeterminate
        # animation depending on what the progress sink is reporting.
        _render_progress_strip(state)
        with ui.column().classes("w-full max-w-[1600px] mx-auto p-4 pm-shell"):
            _render_toolbar(state)
            _render_feedback(state)
            _render_main_tabs(state)
        # P7: action console + artifact paths + progress log moved out of the page
        # first-paint into a slide-over drawer triggered by the app-bar Operate button.
        _render_operate_drawer(state)


def _render_header(state: PortfolioPageState) -> None:
    # P6: replaces the legacy slate-blue gradient `.pm-hero` with a token-driven
    # app-bar that mirrors the embedded report's `<header class='app-bar'>` so the
    # iframe seam closes. Status / job state surfaces inline as `.pm-app-bar__meta`.
    # P7: adds a single primary Refresh button + an Operate trigger that toggles
    # the right-side drawer holding the granular actions, paths, and progress log.
    run_action = getattr(state, "_run_action", None)
    is_busy = state.is_loading or state.active_job is not None
    job_label = "running…" if state.active_job else "idle"
    job_chip_class = "pm-status-chip pm-status-running" if state.active_job else "pm-status-chip pm-status-neutral"
    with ui.element("header").classes("pm-app-bar"):
        with ui.element("div").classes("pm-app-bar__brand"):
            ui.element("span").classes("pm-app-bar__brand-dot")
            ui.label("Market Helper").classes("pm-app-bar__brand-name")
            ui.label("/").classes("pm-app-bar__brand-sep")
            ui.label("Portfolio").classes("pm-app-bar__brand-title")
        ui.element("div").classes("pm-app-bar__spacer")
        ui.label(state.status_message).classes("pm-app-bar__meta")
        with ui.element("div").classes("pm-app-bar__actions"):
            ui.label(job_label).classes(job_chip_class)
            operate_button = ui.button("⚙ Operate")
            operate_button.classes("pm-app-bar__operate").props("flat dense no-caps")
            operate_button.on(
                "click",
                lambda _: ui.run_javascript("document.body.classList.toggle('pm-drawer-open');"),
            )
            refresh_button = ui.button(
                "Refresh",
                on_click=lambda: asyncio.create_task(run_action("refresh")) if run_action else None,
            )
            refresh_button.classes("pm-app-bar__primary").props("unelevated dense no-caps")
            if is_busy or run_action is None:
                refresh_button.props("disable")


def _render_toolbar(state: PortfolioPageState) -> None:
    # P7: granular action buttons (Recompute / Reload / Generate) + the Artifact
    # Paths expansion moved into the operate drawer. The toolbar now carries only
    # the status row + quick-link so /portfolio first-paint is form-free.
    with ui.row().classes("w-full gap-3 wrap"):
        render_status_card(
            title="Report Data",
            value=state.status_message,
            detail=(format_local_datetime(state.report_data.as_of) if state.report_data is not None else None),
        )
        render_status_card(
            title="Generated HTML",
            value=state.action_statuses["combined"].message,
            detail=state.action_statuses["combined"].last_output_path,
        )
    _render_report_quick_link(state)


def _render_feedback(state: PortfolioPageState) -> None:
    if state.is_loading:
        ui.label("Loading report data...").classes("pm-loading w-full")
    if state.load_error:
        ui.label(state.load_error).classes("pm-error w-full")
    run_action = getattr(state, "_run_action", None)
    is_busy = state.is_loading or state.active_job is not None
    for warning in state.warnings:
        hint = _classify_warning(warning)
        if hint is None:
            ui.label(warning).classes("pm-warning w-full")
            continue
        action_name, button_label = hint
        with ui.row().classes("pm-error w-full items-center justify-between gap-2"):
            ui.label(warning).classes("flex-1")
            button = ui.button(
                button_label,
                on_click=(
                    (lambda _name=action_name: asyncio.create_task(run_action(_name)))
                    if run_action is not None
                    else None
                ),
            ).props("color=accent dense no-caps")
            if is_busy or run_action is None:
                button.props("disable")


def _render_main_tabs(state: PortfolioPageState) -> None:
    tabs = ui.tabs(on_change=lambda event: _update_top_tab(state, event.value)).classes("w-full")
    with tabs:
        tab_report = ui.tab("Report")
        tab_artifacts = ui.tab("Artifacts")
    initial_tab = {"report": tab_report, "artifacts": tab_artifacts}.get(state.selected_top_tab, tab_report)
    with ui.tab_panels(tabs, value=initial_tab).classes("w-full"):
        with ui.tab_panel(tab_report):
            _render_report_host(state)
        with ui.tab_panel(tab_artifacts):
            _render_artifact_metadata(state)


def _render_report_host(state: PortfolioPageState) -> None:
    report_path = _current_report_output_path(state)
    if report_path is None:
        with ui.card().classes("w-full pm-card p-4"):
            ui.label("HTML Report").classes("text-h6")
            ui.label("No report output path is configured.").classes("pm-muted")
        return
    if not report_path.exists():
        with ui.card().classes("w-full pm-card p-4"):
            ui.label("HTML Report").classes("text-h6")
            ui.label(
                "No generated HTML report is available yet. Load report data or explicitly generate the HTML report."
            ).classes("pm-muted")
            ui.label(str(report_path)).classes("text-caption pm-muted")
        return
    # P6: drop the wrapping `ui.card` chrome — the embedded report now carries the
    # unified tokens, so a card-on-card border just creates the iframe seam we are
    # trying to close. The iframe itself uses the `.pm-report-iframe` primitive.
    # Link target uses `_served_artifact_url` — Chrome blocks navigation from
    # http:// to file://, so we serve through the sandboxed dashboard route
    # (supersedes the simpler `_generated_html_route` helper added on local main).
    with ui.row().classes("w-full items-center justify-between px-2 pt-2"):
        ui.label("Embedded HTML Report").classes("text-subtitle2 pm-muted")
        served_url = _served_artifact_url(report_path)
        if served_url is not None:
            ui.link("Open Generated HTML", served_url, new_tab=True).classes("text-primary")
        else:
            ui.label(str(report_path)).classes("text-caption pm-muted")
    iframe = ui.element("iframe").props("sandbox=allow-same-origin allow-scripts").classes(
        "pm-report-iframe"
    )
    iframe._props["title"] = "Portfolio Monitor HTML Report"
    iframe._props["srcdoc"] = _inject_embedded_overrides(report_path.read_text(encoding="utf-8"))


_EMBEDDED_REPORT_OVERRIDES = """
<style id='pm-embedded-overrides'>
  /* P10/M1: when the report runs inside the dashboard iframe, its sticky brand
     pill + as-of meta duplicate the dashboard's own app-bar. Hide them but keep
     the section-nav so users can still jump between Performance / Risk / Regime
     within the iframe. The regime ribbon stays — the dashboard chrome doesn't
     surface that context anywhere else. */
  .app-bar__brand, .app-bar__meta { display: none !important; }
  .app-bar { background: var(--surface); }
  .report-shell { padding-top: 8px; }
  /* The framework defaults assume the full app-bar (brand + nav + meta); this
     iframe hides brand + meta so the visible `.app-bar` collapses to just the
     section-nav. Desktop = padding (12*2) + button row (~24px) ≈ 48px; mobile
     gets a touch-target lift so the section-nav row grows to ~40px + padding
     (8*2) = ~56px. Re-declare the height vars so `.regime-ribbon`'s sticky
     `top` matches the iframe's real app-bar height; values are conservative
     upper bounds to avoid the ribbon overlapping the nav. */
  :root {
    --app-bar-height: 48px;
    --app-bar-height-mobile: 56px;
  }
</style>
"""


def _inject_embedded_overrides(html_text: str) -> str:
    """Inject `_EMBEDDED_REPORT_OVERRIDES` immediately before `</head>` in the rendered report.

    Falls back to prepending the override block when no closing `</head>` is
    found (still works in browsers — late `<style>` blocks are honoured).
    """
    needle = "</head>"
    idx = html_text.find(needle)
    if idx == -1:
        return _EMBEDDED_REPORT_OVERRIDES + html_text
    return html_text[:idx] + _EMBEDDED_REPORT_OVERRIDES + html_text[idx:]


def _render_report_quick_link(state: PortfolioPageState) -> None:
    report_path = _current_report_output_path(state)
    if report_path is None or not report_path.exists():
        return
    served_url = _served_artifact_url(report_path)
    if served_url is None:
        return
    with ui.row().classes("w-full items-center gap-2 mt-3"):
        ui.label("Quick Access").classes("text-caption pm-muted")
        ui.link("Open Generated HTML", served_url, new_tab=True).classes("text-primary")


def _render_artifact_metadata(state: PortfolioPageState) -> None:
    if state.report_data is not None:
        metadata = state.report_data.artifact_metadata
        rows = [
            ("Positions CSV", format_path(metadata.positions_csv_path)),
            ("Positions as of", format_local_text(metadata.positions_as_of)),
            ("Performance output dir", format_path(metadata.performance_output_dir)),
            ("Performance history", format_path(metadata.performance_history_path)),
            ("Performance report CSV", format_path(metadata.performance_report_csv_path)),
            ("Returns JSON", format_path(metadata.returns_path)),
            ("Proxy JSON", format_path(metadata.proxy_path)),
            ("Regime JSON", format_path(metadata.regime_path)),
            ("Security reference", format_path(metadata.security_reference_path)),
            ("Risk config", format_path(metadata.risk_config_path)),
            ("Allocation policy", format_path(metadata.allocation_policy_path)),
        ]
    else:
        rows = [
            ("Positions CSV", state.artifact_form.positions_csv_path or "n/a"),
            ("Performance output dir", state.artifact_form.performance_output_dir or "n/a"),
            ("Combined HTML output", state.export_form.output_path or "n/a"),
        ]

    with ui.card().classes("w-full pm-card p-4"):
        ui.label("Artifact Metadata").classes("text-h6")
        for label, value in rows:
            render_status_card(title=label, value=value)


def _render_progress_strip(state: PortfolioPageState) -> None:
    """Render a thin progress strip below the app-bar while a job is active."""
    if state.active_job is None:
        return
    fraction = _progress_fraction(state)
    summary = _summarize_progress(state) if state.progress_sink.events else "Starting…"
    pretty = _ACTION_PRETTY_NAMES.get(state.active_job, state.active_job)
    with ui.element("div").classes("pm-progress-strip"):
        with ui.element("div").classes("pm-progress-strip__row"):
            ui.label(f"⏳ {pretty}").classes("pm-progress-strip__label")
            ui.label(summary).classes("pm-progress-strip__detail")
        progress_el = ui.linear_progress(
            value=fraction if fraction is not None else 0.0,
            show_value=False,
        ).classes("pm-progress-strip__bar")
        # NiceGUI's linear-progress renders an indeterminate animation when given
        # the `indeterminate` Quasar prop — we set it directly when we have no
        # measurable fraction.
        if fraction is None:
            progress_el.props("indeterminate")
