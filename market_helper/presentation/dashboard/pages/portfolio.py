from __future__ import annotations

import asyncio
import html
import os
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from nicegui import ui

from market_helper.application.portfolio_monitor import (
    EtfSectorSyncInputs,
    FlexPerformanceRefreshInputs,
    GenerateCombinedReportInputs,
    GeneratedReportArtifact,
    InMemoryUiProgressSink,
    LivePortfolioRefreshInputs,
    PortfolioMonitorActionService,
    PortfolioMonitorQueryService,
    PortfolioReportData,
    PortfolioReportInputs,
)
from market_helper.presentation.dashboard.components import render_action_card
from market_helper.presentation.dashboard.components.common import add_dashboard_styles, render_status_card
from market_helper.presentation.dashboard.formatters import format_path, format_text


_REGISTERED = False
_QUERY_SERVICE: PortfolioMonitorQueryService = PortfolioMonitorQueryService()
_ACTION_SERVICE: PortfolioMonitorActionService = PortfolioMonitorActionService()
_STALE_PAGE_CACHE: dict[str, Any] | None = None

DEFAULT_CANONICAL_LOCAL_ENV_PATH = (
    Path(__file__).resolve().parents[4] / "configs" / "portfolio_monitor" / "local.env"
)
DEFAULT_IBKR_FLEX_QUERY_ID_ENV_VAR = "IBKR_FLEX_QUERY_ID"
DEFAULT_IBKR_FLEX_TOKEN_ENV_VAR = "IBKR_FLEX_TOKEN"
DEFAULT_PROD_ACCOUNT_ID_ENV_VAR = "DEFAULT_PROD_ACCOUNT_ID"
DEFAULT_DEV_ACCOUNT_ID_ENV_VAR = "DEFAULT_DEV_ACCOUNT_ID"


@dataclass
class PortfolioArtifactFormState:
    positions_csv_path: str = ""
    performance_output_dir: str = ""
    performance_history_path: str = ""
    performance_report_csv_path: str = ""
    returns_path: str = ""
    proxy_path: str = ""
    regime_path: str = ""
    security_reference_path: str = ""
    risk_config_path: str = ""
    allocation_policy_path: str = ""
    vol_method: str = "geomean_1m_3m"
    inter_asset_corr: str = "historical"


@dataclass
class LiveActionFormState:
    output_path: str = ""
    host: str = "127.0.0.1"
    port: str = "7497"
    client_id: str = "1"
    account_id: str = ""
    timeout: str = "4.0"
    as_of: str = ""


@dataclass
class FlexActionFormState:
    output_dir: str = ""
    flex_xml_path: str = ""
    query_id: str = ""
    token: str = ""
    from_date: str = ""
    to_date: str = ""
    period: str = ""
    xml_output_path: str = ""


@dataclass
class ExportActionFormState:
    output_path: str = ""


@dataclass
class ReferenceActionFormState:
    security_reference_output_path: str = ""
    etf_symbols: str = ""
    etf_output_path: str = ""
    api_key: str = ""


@dataclass
class ActionStatusState:
    status: str = "idle"
    message: str = "Not run yet"
    progress_summary: str = "No recent progress"
    last_output_path: str = "n/a"


@dataclass
class PortfolioPageState:
    artifact_form: PortfolioArtifactFormState
    live_form: LiveActionFormState
    flex_form: FlexActionFormState
    export_form: ExportActionFormState
    reference_form: ReferenceActionFormState
    report_data: PortfolioReportData | None = None
    generated_report: GeneratedReportArtifact | None = None
    warnings: list[str] = field(default_factory=list)
    is_loading: bool = False
    load_error: str | None = None
    active_job: str | None = None
    status_message: str = "Ready"
    selected_top_tab: str = "report"
    progress_sink: InMemoryUiProgressSink = field(default_factory=InMemoryUiProgressSink)
    action_statuses: dict[str, ActionStatusState] = field(
        default_factory=lambda: {
            "refresh": ActionStatusState(message="Not run yet"),
            "live": ActionStatusState(),
            "flex": ActionStatusState(),
            "combined": ActionStatusState(message="Not generated yet"),
            "security-reference": ActionStatusState(),
            "etf": ActionStatusState(),
        }
    )


def _cache_stale_page_state(state: PortfolioPageState) -> None:
    global _STALE_PAGE_CACHE
    _STALE_PAGE_CACHE = {
        "artifact_form": deepcopy(state.artifact_form),
        "live_form": deepcopy(state.live_form),
        "flex_form": deepcopy(state.flex_form),
        "export_form": deepcopy(state.export_form),
        "reference_form": deepcopy(state.reference_form),
        "report_data": deepcopy(state.report_data),
        "generated_report": deepcopy(state.generated_report),
        "warnings": list(state.warnings),
        "status_message": state.status_message,
        "selected_top_tab": state.selected_top_tab,
        "action_statuses": deepcopy(state.action_statuses),
    }


def _restore_stale_page_state(state: PortfolioPageState) -> None:
    if _STALE_PAGE_CACHE is None:
        return
    state.artifact_form = deepcopy(_STALE_PAGE_CACHE["artifact_form"])
    state.live_form = deepcopy(_STALE_PAGE_CACHE["live_form"])
    state.flex_form = deepcopy(_STALE_PAGE_CACHE["flex_form"])
    state.export_form = deepcopy(_STALE_PAGE_CACHE["export_form"])
    state.reference_form = deepcopy(_STALE_PAGE_CACHE["reference_form"])
    state.report_data = deepcopy(_STALE_PAGE_CACHE["report_data"])
    state.generated_report = deepcopy(_STALE_PAGE_CACHE["generated_report"])
    state.warnings = list(_STALE_PAGE_CACHE["warnings"])
    state.status_message = str(_STALE_PAGE_CACHE["status_message"])
    state.selected_top_tab = str(_STALE_PAGE_CACHE["selected_top_tab"])
    state.action_statuses = deepcopy(_STALE_PAGE_CACHE["action_statuses"])
    state.load_error = None
    state.is_loading = False
    state.active_job = None


def _clear_stale_page_cache() -> None:
    global _STALE_PAGE_CACHE
    _STALE_PAGE_CACHE = None


def _report_data_matches_current_local_date(report_data: Any) -> bool:
    as_of = str(getattr(report_data, "as_of", "") or "").strip()
    if not as_of:
        return True
    try:
        report_dt = datetime.fromisoformat(as_of.replace("Z", "+00:00"))
    except ValueError:
        return True
    if report_dt.tzinfo is not None:
        report_dt = report_dt.astimezone()
    return report_dt.date() == datetime.now().astimezone().date()


_TOP_TAB_KEYS = {"report", "artifacts"}


def _resolve_top_tab_key(value: str | None) -> str:
    normalized = str(value or "").strip().lower()
    aliases = {
        "": "report",
        "html": "report",
        "performance": "report",
        "risk": "report",
    }
    if normalized in _TOP_TAB_KEYS:
        return normalized
    return aliases.get(normalized, "report")


def _positions_csv_ready_for_autoload(value: str) -> bool:
    normalized = value.strip()
    return bool(normalized) and Path(normalized).exists()


def _initial_dashboard_status(positions_csv_path: str) -> str:
    if _positions_csv_ready_for_autoload(positions_csv_path):
        return "Ready. Load report data or generate the HTML report from current artifacts."
    return "Positions CSV not found. Run Live Refresh or enter a valid artifact path."


def _resolve_local_env_value(key: str) -> str:
    normalized_key = str(key).strip()
    if not normalized_key:
        return ""
    from_process_env = str(os.environ.get(normalized_key, "")).strip()
    if from_process_env:
        return from_process_env
    return _read_env_file_value(DEFAULT_CANONICAL_LOCAL_ENV_PATH, normalized_key)


def _resolve_default_live_account_id() -> str:
    return _resolve_local_env_value(DEFAULT_PROD_ACCOUNT_ID_ENV_VAR) or _resolve_local_env_value(
        DEFAULT_DEV_ACCOUNT_ID_ENV_VAR
    )


def _read_env_file_value(path: Path, key: str) -> str:
    if not path.exists():
        return ""
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue
        raw_key, raw_value = line.split("=", 1)
        if raw_key.strip() != key:
            continue
        value = raw_value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"\"", "'"}:
            value = value[1:-1]
        return value.strip()
    return ""


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

    @ui.page("/portfolio")
    async def portfolio_page(tab: str | None = None) -> None:
        state = _build_initial_state(_QUERY_SERVICE)
        _restore_stale_page_state(state)
        state.selected_top_tab = _resolve_top_tab_key(tab)

        @ui.refreshable
        def render() -> None:
            _render_portfolio_page(state)

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
                state.status_message = f"Loaded report data as of {_format_local_timestamp(report_data.as_of)}"
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
            _set_action_running(state, action_name)
            render.refresh()
            try:
                if action_name == "live":
                    action_inputs = _live_inputs_from_form(state.live_form)
                    output_path = await asyncio.to_thread(
                        _ACTION_SERVICE.refresh_live_positions,
                        action_inputs,
                        sink=state.progress_sink,
                    )
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
                    _set_action_success(state, "combined", message="HTML report generated", output_path=str(artifact.output_path))
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
                elif action_name == "refresh":
                    live_inputs = _live_inputs_from_form(state.live_form)
                    live_output = await asyncio.to_thread(
                        _ACTION_SERVICE.refresh_live_positions,
                        live_inputs,
                        sink=state.progress_sink,
                    )
                    state.artifact_form.positions_csv_path = str(live_output)
                    state.live_form.output_path = str(live_output)
                    _set_action_success(state, "live", message="Live positions refreshed", output_path=str(live_output))

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
                    _set_action_success(state, "combined", message="HTML report generated", output_path=str(artifact.output_path))
                    _set_action_success(state, "refresh", message="Refresh completed", output_path=str(artifact.output_path))
                else:
                    raise ValueError(f"Unsupported action: {action_name}")
                state.status_message = state.action_statuses[action_name].message
            except Exception as exc:
                _set_action_error(state, action_name, str(exc))
                state.status_message = f"Action failed: {exc}"
            finally:
                state.active_job = None
                _cache_stale_page_state(state)
                render.refresh()

        state._load_report_data = load_report_data  # type: ignore[attr-defined]
        state._run_action = run_action  # type: ignore[attr-defined]
        render()
        ui.timer(0.1, lambda: asyncio.create_task(initialize_page()), once=True)
        ui.timer(0.5, lambda: render.refresh() if state.active_job is not None else None)

    _REGISTERED = True


def _build_initial_state(query_service: PortfolioMonitorQueryService) -> PortfolioPageState:
    inputs = query_service.resolve_inputs()
    positions_path = str(inputs.positions_csv_path or "")
    performance_output_dir = str(inputs.performance_output_dir or "")
    default_output_path = (
        str(Path(performance_output_dir).parent / "portfolio_combined_report.html")
        if performance_output_dir
        else "portfolio_combined_report.html"
    )
    return PortfolioPageState(
        artifact_form=PortfolioArtifactFormState(
            positions_csv_path=positions_path,
            performance_output_dir=performance_output_dir,
            performance_history_path=str(inputs.performance_history_path or ""),
            performance_report_csv_path=str(inputs.performance_report_csv_path or ""),
            returns_path=str(inputs.returns_path or ""),
            proxy_path=str(inputs.proxy_path or ""),
            regime_path=str(inputs.regime_path or ""),
            security_reference_path=str(inputs.security_reference_path or ""),
            risk_config_path=str(inputs.risk_config_path or ""),
            allocation_policy_path=str(inputs.allocation_policy_path or ""),
            vol_method=str(inputs.vol_method or "geomean_1m_3m"),
            inter_asset_corr=str(inputs.inter_asset_corr or "historical"),
        ),
        live_form=LiveActionFormState(
            output_path=positions_path,
            account_id=_resolve_default_live_account_id(),
        ),
        flex_form=FlexActionFormState(
            output_dir=performance_output_dir,
            query_id=_resolve_local_env_value(DEFAULT_IBKR_FLEX_QUERY_ID_ENV_VAR),
            token=_resolve_local_env_value(DEFAULT_IBKR_FLEX_TOKEN_ENV_VAR),
        ),
        export_form=ExportActionFormState(output_path=default_output_path),
        reference_form=ReferenceActionFormState(
            security_reference_output_path=str(inputs.security_reference_path or "")
        ),
        status_message=_initial_dashboard_status(positions_path),
    )


def _render_portfolio_page(state: PortfolioPageState) -> None:
    add_dashboard_styles()
    with ui.column().classes("w-full max-w-[1600px] mx-auto p-4 pm-shell"):
        _render_header(state)
        _render_toolbar(state)
        _render_feedback(state)
        _render_main_tabs(state)
        _render_action_console(state)
        _render_logs(state)


def _render_header(state: PortfolioPageState) -> None:
    with ui.card().classes("w-full pm-hero shadow-lg"):
        ui.label("Portfolio Monitor").classes("text-h4")
        ui.label("GUI shell for actions, artifact inspection, and embedded HTML report hosting.").classes(
            "text-body1 opacity-80"
        )
        ui.label(state.status_message).classes("text-body2 opacity-80")


def _render_toolbar(state: PortfolioPageState) -> None:
    load_report_data = getattr(state, "_load_report_data", None)
    run_action = getattr(state, "_run_action", None)
    with ui.card().classes("w-full pm-card p-4"):
        ui.label("Report Controls").classes("text-h6")
        ui.label(
            "Load current report data without mutating artifacts, or explicitly generate the self-contained HTML report."
        ).classes("pm-muted")
        with ui.row().classes("items-center gap-3 mt-4 wrap"):
            load_button = ui.button(
                "Load Latest Data",
                on_click=lambda: asyncio.create_task(load_report_data()),
            ).props("color=primary")
            refresh_button = ui.button(
                "Refresh Pipeline + Generate",
                on_click=lambda: asyncio.create_task(run_action("refresh")),
            ).props("color=secondary")
            generate_button = ui.button(
                "Generate HTML Report",
                on_click=lambda: asyncio.create_task(run_action("combined")),
            ).props("color=accent")
            if state.is_loading or state.active_job is not None:
                load_button.props("disable")
                refresh_button.props("disable")
                generate_button.props("disable")
        with ui.row().classes("w-full gap-3 wrap mt-4"):
            render_status_card(
                title="Report Data",
                value=state.status_message,
                detail=state.report_data.as_of if state.report_data is not None else None,
            )
            render_status_card(
                title="Generated HTML",
                value=state.action_statuses["combined"].message,
                detail=state.action_statuses["combined"].last_output_path,
            )
        with ui.expansion("Artifact Paths", icon="folder", value=False).classes("w-full mt-4"):
            with ui.column().classes("w-full gap-3 p-2"):
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


def _render_feedback(state: PortfolioPageState) -> None:
    if state.is_loading:
        ui.label("Loading report data...").classes("pm-loading w-full")
    if state.load_error:
        ui.label(state.load_error).classes("pm-error w-full")
    for warning in state.warnings:
        ui.label(warning).classes("pm-warning w-full")


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
    report_html = report_path.read_text(encoding="utf-8")
    iframe_html = (
        "<iframe "
        "title='Portfolio Monitor HTML Report' "
        "sandbox='allow-same-origin allow-scripts' "
        "style='width:100%;min-height:78vh;border:0;border-radius:20px;background:#fff' "
        f"srcdoc='{html.escape(report_html, quote=True)}'></iframe>"
    )
    with ui.card().classes("w-full pm-card p-2"):
        ui.html(iframe_html).classes("w-full")


def _render_artifact_metadata(state: PortfolioPageState) -> None:
    if state.report_data is not None:
        metadata = state.report_data.artifact_metadata
        rows = [
            ("Positions CSV", format_path(metadata.positions_csv_path)),
            ("Positions as of", format_text(metadata.positions_as_of)),
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


def _render_action_console(state: PortfolioPageState) -> None:
    run_action = getattr(state, "_run_action", None)
    with ui.row().classes("w-full gap-4 wrap"):
        render_action_card(
            title="Refresh Pipeline",
            subtitle="Run live refresh, rebuild flex artifacts, reload report data, and regenerate HTML.",
            status=state.action_statuses["refresh"].status,
            message=state.action_statuses["refresh"].message,
            progress_summary=_action_progress_summary(state, "refresh"),
            last_output_path=state.action_statuses["refresh"].last_output_path,
            body=lambda: _render_action_button(run_action, "refresh", "Run Full Refresh"),
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
            body=lambda: _render_action_button(run_action, "combined", "Generate HTML Report"),
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
        _render_action_button(run_action, "live", "Run Live Refresh")


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
        _render_action_button(run_action, "flex", "Run Flex Refresh")


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
            _render_action_button(run_action, "security-reference", "Sync Security Reference")
            _render_action_button(run_action, "etf", "Sync ETF Lookthrough")


def _render_action_button(run_action, action_name: str, label: str) -> None:
    ui.button(label, on_click=lambda: asyncio.create_task(run_action(action_name)))


def _render_logs(state: PortfolioPageState) -> None:
    with ui.card().classes("w-full pm-card p-4"):
        ui.label("Progress Log").classes("text-h6")
        with ui.column().classes("w-full gap-2 pm-log"):
            if not state.progress_sink.events:
                ui.label("No progress events yet.").classes("pm-muted")
                return
            for event in state.progress_sink.events[-20:]:
                detail = _format_progress_event(event)
                text = f"{event.label}: {detail}" if detail else event.label
                ui.label(text).classes("text-caption")


def _artifact_inputs_from_form(form: PortfolioArtifactFormState) -> PortfolioReportInputs:
    return PortfolioReportInputs(
        positions_csv_path=_required_text(form.positions_csv_path, "Positions CSV path"),
        performance_output_dir=_optional_text(form.performance_output_dir),
        performance_history_path=_optional_text(form.performance_history_path),
        performance_report_csv_path=_optional_text(form.performance_report_csv_path),
        returns_path=_optional_text(form.returns_path),
        proxy_path=_optional_text(form.proxy_path),
        regime_path=_optional_text(form.regime_path),
        security_reference_path=_optional_text(form.security_reference_path),
        risk_config_path=_optional_text(form.risk_config_path),
        allocation_policy_path=_optional_text(form.allocation_policy_path),
        vol_method=_required_text(form.vol_method, "Vol method"),
        inter_asset_corr=_required_text(form.inter_asset_corr, "Inter-asset correlation assumption"),
    )


def _live_inputs_from_form(form: LiveActionFormState) -> LivePortfolioRefreshInputs:
    return LivePortfolioRefreshInputs(
        output_path=_required_text(form.output_path, "Live positions output path"),
        host=_required_text(form.host, "Live host"),
        port=_parse_int(form.port, "Live port"),
        client_id=_parse_int(form.client_id, "Live client id"),
        account_id=_optional_text(form.account_id),
        timeout=_parse_float(form.timeout, "Live timeout"),
        as_of=_optional_text(form.as_of),
    )


def _flex_inputs_from_form(form: FlexActionFormState) -> FlexPerformanceRefreshInputs:
    return FlexPerformanceRefreshInputs(
        output_dir=_required_text(form.output_dir, "Flex output dir"),
        flex_xml_path=_optional_text(form.flex_xml_path),
        query_id=_optional_text(form.query_id),
        token=_optional_text(form.token),
        from_date=_optional_text(form.from_date),
        to_date=_optional_text(form.to_date),
        period=_optional_text(form.period),
        xml_output_path=_optional_text(form.xml_output_path),
    )


def _combined_inputs_from_form(state: PortfolioPageState) -> GenerateCombinedReportInputs:
    artifact_inputs = _artifact_inputs_from_form(state.artifact_form)
    return GenerateCombinedReportInputs(
        positions_csv_path=artifact_inputs.positions_csv_path,
        performance_output_dir=artifact_inputs.performance_output_dir,
        performance_history_path=artifact_inputs.performance_history_path,
        performance_report_csv_path=artifact_inputs.performance_report_csv_path,
        returns_path=artifact_inputs.returns_path,
        proxy_path=artifact_inputs.proxy_path,
        regime_path=artifact_inputs.regime_path,
        security_reference_path=artifact_inputs.security_reference_path,
        risk_config_path=artifact_inputs.risk_config_path,
        allocation_policy_path=artifact_inputs.allocation_policy_path,
        vol_method=artifact_inputs.vol_method,
        inter_asset_corr=artifact_inputs.inter_asset_corr,
        output_path=_required_text(state.export_form.output_path, "Combined report output path"),
    )


def _etf_inputs_from_form(form: ReferenceActionFormState) -> EtfSectorSyncInputs:
    symbols = [part.strip().upper() for part in form.etf_symbols.split(",") if part.strip()]
    if not symbols:
        raise ValueError("ETF symbols are required for ETF sector sync")
    return EtfSectorSyncInputs(
        symbols=symbols,
        output_path=_optional_text(form.etf_output_path),
        api_key=_optional_text(form.api_key),
    )


def _current_report_output_path(state: PortfolioPageState) -> Path | None:
    candidates = [
        str(state.generated_report.output_path) if state.generated_report is not None else None,
        _optional_text(state.action_statuses["combined"].last_output_path),
        _optional_text(state.export_form.output_path),
    ]
    for candidate in candidates:
        if candidate:
            return Path(candidate)
    return None


def _required_text(value: str, label: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{label} is required")
    return normalized


def _optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def _parse_int(value: str, label: str) -> int:
    try:
        return int(_required_text(value, label))
    except ValueError as exc:
        raise ValueError(f"{label} must be an integer") from exc


def _parse_float(value: str, label: str) -> float:
    try:
        return float(_required_text(value, label))
    except ValueError as exc:
        raise ValueError(f"{label} must be a number") from exc


def _set_action_running(state: PortfolioPageState, action_name: str) -> None:
    status = state.action_statuses[action_name]
    status.status = "running"
    status.message = f"Running {action_name}"
    status.progress_summary = "Starting..."


def _set_action_success(state: PortfolioPageState, action_name: str, *, message: str, output_path: str) -> None:
    status = state.action_statuses[action_name]
    status.status = "success"
    status.message = message
    status.last_output_path = output_path
    status.progress_summary = _summarize_progress(state)


def _set_action_error(state: PortfolioPageState, action_name: str, message: str) -> None:
    status = state.action_statuses[action_name]
    status.status = "error"
    status.message = message
    status.progress_summary = _summarize_progress(state)


def _action_progress_summary(state: PortfolioPageState, action_name: str) -> str:
    if state.active_job == action_name and state.progress_sink.events:
        return _summarize_progress(state)
    return state.action_statuses[action_name].progress_summary


def _summarize_progress(state: PortfolioPageState) -> str:
    if not state.progress_sink.events:
        return "No progress events"
    latest = state.progress_sink.events[-1]
    progress = _format_progress_event(latest)
    if latest.detail and progress:
        return f"{latest.label}: {progress} {latest.detail}"
    if latest.detail:
        return f"{latest.label}: {latest.detail}"
    if progress:
        return f"{latest.label}: {progress}"
    return latest.label


def _format_progress_event(event: Any) -> str:
    if event.completed is not None and event.total is not None:
        return f"{event.completed} / {event.total}"
    if event.current is not None and event.total is not None:
        return f"{event.current} / {event.total}"
    return event.detail or ""


def _format_local_timestamp(value: str | None) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        return ""
    try:
        dt = datetime.fromisoformat(normalized.replace("Z", "+00:00"))
    except ValueError:
        return normalized
    return dt.astimezone().isoformat(timespec="seconds")


def _update_top_tab(state: PortfolioPageState, value: str) -> None:
    mapping = {"Report": "report", "Artifacts": "artifacts"}
    key = mapping.get(str(value or "").strip())
    if key is not None:
        state.selected_top_tab = key
