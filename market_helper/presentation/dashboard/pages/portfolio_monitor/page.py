"""`/portfolio` registration + page lifecycle.

Owns the NiceGUI page handler and its closures (load report data, run action,
initialize, reload) — the lifecycle that captures the per-page ``render.refresh``
and the module-level service singletons. Everything reusable lives in the
sibling modules (`state`, `actions`, `routes`, `views`, `drawer`).
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime

from nicegui import ui

from market_helper.application.portfolio_monitor import (
    PortfolioMonitorActionService,
    PortfolioMonitorQueryService,
)
from market_helper.common.datetime_display import format_local_datetime
from market_helper.providers.tws_ib_async import TwsIbAsyncError
from market_helper.presentation.dashboard.pages.portfolio_monitor.actions import (
    _artifact_inputs_from_form,
    _benchmark_inputs_from_form,
    _combined_inputs_from_form,
    _etf_inputs_from_form,
    _flex_inputs_from_form,
    _live_inputs_from_form,
    _push_completion_toast,
    _record_job_completion,
    _regime_refresh_inputs_from_form,
    _regime_run_inputs_from_form,
    _set_action_error,
    _set_action_running,
    _set_action_success,
)
from market_helper.presentation.dashboard.pages.portfolio_monitor.routes import (
    _current_report_output_path,
    _register_dashboard_report_route,
    _register_generated_html_route,
)
from market_helper.presentation.dashboard.pages.portfolio_monitor.state import (
    _build_initial_state,
    _cache_stale_page_state,
    _clear_stale_page_cache,
    _existing_cached_position_csv,
    _initial_dashboard_status,
    _optional_text,
    _positions_csv_ready_for_autoload,
    _report_data_matches_current_local_date,
    _required_text,
    _resolve_top_tab_key,
    _restore_stale_page_state,
)
from market_helper.presentation.dashboard.pages.portfolio_monitor.views import _render_portfolio_page

_logger = logging.getLogger(__name__)
_REGISTERED = False
_QUERY_SERVICE: PortfolioMonitorQueryService = PortfolioMonitorQueryService()
_ACTION_SERVICE: PortfolioMonitorActionService = PortfolioMonitorActionService()


def register_portfolio_page(
    *,
    query_service: PortfolioMonitorQueryService | None = None,
    action_service: PortfolioMonitorActionService | None = None,
) -> None:
    global _REGISTERED, _QUERY_SERVICE, _ACTION_SERVICE
    if query_service is not None:
        _QUERY_SERVICE = query_service
    if action_service is not None:
        _ACTION_SERVICE = action_service
    if _REGISTERED:
        return

    _register_generated_html_route()
    _register_dashboard_report_route()

    @ui.page("/portfolio")
    async def portfolio_page(tab: str | None = None) -> None:
        state = _build_initial_state(_QUERY_SERVICE)
        _restore_stale_page_state(state)
        state.selected_top_tab = _resolve_top_tab_key(tab)

        @ui.refreshable
        def render() -> None:
            _render_portfolio_page(state)

        def reload_embedded_report() -> None:
            report_path = _current_report_output_path(state)
            if report_path is None:
                state.status_message = "No HTML report output path is configured"
            elif not report_path.exists():
                state.status_message = "No generated HTML report is available to reload"
            else:
                state.status_message = f"Reloaded embedded HTML from {report_path}"
            render.refresh()

        async def load_report_data() -> None:
            previous_data = state.report_data
            previous_warnings = list(state.warnings)
            if not _positions_csv_ready_for_autoload(state.artifact_form.positions_csv_path):
                state.load_error = None
                state.is_loading = False
                state.status_message = _initial_dashboard_status(state.artifact_form.positions_csv_path)
                render.refresh()
                return
            state.is_loading = True
            state.load_error = None
            state.status_message = "Loading report data..."
            render.refresh()
            try:
                inputs = _artifact_inputs_from_form(state.artifact_form)
                report_data = await asyncio.to_thread(_QUERY_SERVICE.load_report_data, inputs)
            except Exception as exc:
                state.report_data = previous_data
                state.warnings = previous_warnings
                state.load_error = str(exc)
                state.status_message = "Report data load failed"
            else:
                state.report_data = report_data
                state.warnings = list(report_data.warnings)
                state.generated_report = _QUERY_SERVICE.resolve_report_artifact(
                    inputs=inputs,
                    output_path=_required_text(state.export_form.output_path, "Combined report output path"),
                    report_data=report_data,
                )
                state.status_message = f"Loaded report data as of {format_local_datetime(report_data.as_of)}"
                _cache_stale_page_state(state)
            finally:
                state.is_loading = False
                render.refresh()

        async def initialize_page() -> None:
            if state.report_data is not None:
                if not _report_data_matches_current_local_date(state.report_data):
                    _clear_stale_page_cache()
                    state.report_data = None
                    state.generated_report = None
                    state.warnings = []
                    state.load_error = None
                    state.status_message = "Report date changed; reloading current artifacts..."
                    render.refresh()
                    if _positions_csv_ready_for_autoload(state.artifact_form.positions_csv_path):
                        await load_report_data()
                    return
                render.refresh()
                return
            state.status_message = _initial_dashboard_status(state.artifact_form.positions_csv_path)
            render.refresh()
            if _positions_csv_ready_for_autoload(state.artifact_form.positions_csv_path):
                await load_report_data()

        async def run_action(action_name: str) -> None:
            if state.active_job is not None:
                return
            state.progress_sink.clear()
            state.active_job = action_name
            state.active_job_started_at = datetime.now()
            _set_action_running(state, action_name)
            render.refresh()
            try:
                if action_name == "live":
                    action_inputs = _live_inputs_from_form(state.live_form)
                    try:
                        output_path = await asyncio.to_thread(
                            _ACTION_SERVICE.refresh_live_positions,
                            action_inputs,
                            sink=state.progress_sink,
                        )
                    except TwsIbAsyncError as exc:
                        cached = _existing_cached_position_csv(state.artifact_form.positions_csv_path)
                        if cached is None:
                            raise
                        _logger.warning(
                            "Live refresh failed (%s); using cached snapshot %s",
                            exc,
                            cached,
                        )
                        state.artifact_form.positions_csv_path = str(cached)
                        state.live_form.output_path = str(cached)
                        _set_action_success(
                            state,
                            "live",
                            message=f"TWS / IB Gateway unreachable; using cached {cached.name}",
                            output_path=str(cached),
                        )
                        await load_report_data()
                    else:
                        state.artifact_form.positions_csv_path = str(output_path)
                        state.live_form.output_path = str(output_path)
                        _set_action_success(state, "live", message="Live positions refreshed", output_path=str(output_path))
                        await load_report_data()
                elif action_name == "flex":
                    action_inputs = _flex_inputs_from_form(state.flex_form)
                    output_path = await asyncio.to_thread(
                        _ACTION_SERVICE.rebuild_flex_performance,
                        action_inputs,
                        sink=state.progress_sink,
                    )
                    state.artifact_form.performance_output_dir = str(output_path.parent)
                    _set_action_success(state, "flex", message="Flex performance refreshed", output_path=str(output_path))
                    await load_report_data()
                elif action_name == "combined":
                    action_inputs = _combined_inputs_from_form(state)
                    artifact = await asyncio.to_thread(
                        _ACTION_SERVICE.generate_combined_report,
                        action_inputs,
                        sink=state.progress_sink,
                    )
                    state.generated_report = artifact
                    combined_message = "HTML report generated"
                    if artifact.mirrored_output_path is not None:
                        combined_message = "HTML report generated and mirrored to Google Drive"
                    _set_action_success(state, "combined", message=combined_message, output_path=str(artifact.output_path))
                elif action_name == "regime-run":
                    action_inputs = _regime_run_inputs_from_form(state.regime_form)
                    artifact = await asyncio.to_thread(
                        _ACTION_SERVICE.run_regime_report,
                        action_inputs,
                        sink=state.progress_sink,
                    )
                    state.artifact_form.regime_path = str(action_inputs.output_regime_path or "")
                    _set_action_success(
                        state,
                        "regime-run",
                        message="Regime report generated",
                        output_path=str(artifact.output_path),
                    )
                    if _positions_csv_ready_for_autoload(state.artifact_form.positions_csv_path):
                        await load_report_data()
                elif action_name == "regime-refresh":
                    action_inputs = _regime_refresh_inputs_from_form(state.regime_form)
                    artifact = await asyncio.to_thread(
                        _ACTION_SERVICE.refresh_regime_report,
                        action_inputs,
                        sink=state.progress_sink,
                    )
                    state.artifact_form.regime_path = str(action_inputs.output_regime_path or "")
                    _set_action_success(
                        state,
                        "regime-refresh",
                        message="Regime inputs refreshed and report generated",
                        output_path=str(artifact.output_path),
                    )
                    if _positions_csv_ready_for_autoload(state.artifact_form.positions_csv_path):
                        await load_report_data()
                elif action_name == "security-reference":
                    output_path = await asyncio.to_thread(
                        _ACTION_SERVICE.sync_security_reference,
                        output_path=_optional_text(state.reference_form.security_reference_output_path),
                        sink=state.progress_sink,
                    )
                    state.artifact_form.security_reference_path = str(output_path)
                    state.reference_form.security_reference_output_path = str(output_path)
                    _set_action_success(
                        state,
                        "security-reference",
                        message="Security reference synced",
                        output_path=str(output_path),
                    )
                    await load_report_data()
                elif action_name == "etf":
                    action_inputs = _etf_inputs_from_form(state.reference_form)
                    output_path = await asyncio.to_thread(
                        _ACTION_SERVICE.sync_etf_sector,
                        action_inputs,
                        sink=state.progress_sink,
                    )
                    state.reference_form.etf_output_path = str(output_path)
                    _set_action_success(state, "etf", message="ETF sector lookthrough synced", output_path=str(output_path))
                elif action_name == "yahoo":
                    action_inputs = _benchmark_inputs_from_form(state)
                    output_path = await asyncio.to_thread(
                        _ACTION_SERVICE.refresh_benchmark_cache,
                        action_inputs,
                        sink=state.progress_sink,
                    )
                    _set_action_success(state, "yahoo", message="Benchmark cache refreshed", output_path=str(output_path))
                    await load_report_data()
                elif action_name == "refresh":
                    live_inputs = _live_inputs_from_form(state.live_form)
                    try:
                        live_output = await asyncio.to_thread(
                            _ACTION_SERVICE.refresh_live_positions,
                            live_inputs,
                            sink=state.progress_sink,
                        )
                        live_message = "Live positions refreshed"
                    except TwsIbAsyncError as exc:
                        cached = _existing_cached_position_csv(state.artifact_form.positions_csv_path)
                        if cached is None:
                            raise
                        _logger.warning(
                            "Live refresh failed (%s); continuing with cached snapshot %s",
                            exc,
                            cached,
                        )
                        live_output = cached
                        live_message = f"TWS / IB Gateway unreachable; using cached {cached.name}"
                    state.artifact_form.positions_csv_path = str(live_output)
                    state.live_form.output_path = str(live_output)
                    _set_action_success(state, "live", message=live_message, output_path=str(live_output))

                    flex_inputs = _flex_inputs_from_form(state.flex_form)
                    flex_output = await asyncio.to_thread(
                        _ACTION_SERVICE.rebuild_flex_performance,
                        flex_inputs,
                        sink=state.progress_sink,
                    )
                    state.artifact_form.performance_output_dir = str(flex_output.parent)
                    state.flex_form.output_dir = str(flex_output.parent)
                    _set_action_success(state, "flex", message="Flex performance refreshed", output_path=str(flex_output))

                    await load_report_data()
                    combined_inputs = _combined_inputs_from_form(state)
                    artifact = await asyncio.to_thread(
                        _ACTION_SERVICE.generate_combined_report,
                        combined_inputs,
                        sink=state.progress_sink,
                    )
                    state.generated_report = artifact
                    combined_message = "HTML report generated"
                    refresh_message = "Refresh completed"
                    if artifact.mirrored_output_path is not None:
                        combined_message = "HTML report generated and mirrored to Google Drive"
                        refresh_message = "Refresh completed and mirrored to Google Drive"
                    _set_action_success(state, "combined", message=combined_message, output_path=str(artifact.output_path))
                    _set_action_success(state, "refresh", message=refresh_message, output_path=str(artifact.output_path))
                else:
                    raise ValueError(f"Unsupported action: {action_name}")
                state.status_message = state.action_statuses[action_name].message
            except Exception as exc:
                _set_action_error(state, action_name, str(exc))
                state.status_message = f"Action failed: {exc}"
            finally:
                # P8: record completion in history + push a toast so a finished
                # background job is visible without watching the page.
                _record_job_completion(state, action_name)
                _push_completion_toast(state, action_name)
                state.active_job = None
                state.active_job_started_at = None
                _cache_stale_page_state(state)
                render.refresh()

        state._load_report_data = load_report_data  # type: ignore[attr-defined]
        state._reload_embedded_report = reload_embedded_report  # type: ignore[attr-defined]
        state._run_action = run_action  # type: ignore[attr-defined]
        render()
        ui.timer(0.1, lambda: asyncio.create_task(initialize_page()), once=True)
        ui.timer(0.5, lambda: render.refresh() if state.active_job is not None else None)

    _REGISTERED = True
