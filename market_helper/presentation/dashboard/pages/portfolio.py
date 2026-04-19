from __future__ import annotations

import asyncio
import csv
import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

from nicegui import ui

from market_helper.application.portfolio_monitor import (
    EtfSectorSyncInputs,
    FlexPerformanceRefreshInputs,
    GenerateCombinedReportInputs,
    InMemoryUiProgressSink,
    LivePortfolioRefreshInputs,
    PortfolioMonitorActionService,
    PortfolioMonitorQueryService,
    PortfolioReportInputs,
    PortfolioReportSnapshot,
)
from market_helper.presentation.dashboard.components import (
    add_dashboard_styles,
    build_breakdown_figure,
    build_policy_drift_figure,
    render_action_card,
    render_risk_chart_block,
    render_status_card,
    render_table,
)
from market_helper.presentation.dashboard.formatters import (
    format_amount,
    format_path,
    format_percent,
    format_ratio,
    format_text,
)
from market_helper.reporting.performance_html import PerformanceMetricRow, PerformanceReportViewModel
from market_helper.reporting.risk_html import (
    BreakdownRow,
    DEFAULT_VOL_METHOD_LABELS,
    PolicyDriftRow,
    RiskMetricsRow,
    resolve_vol_method_key,
)


_REGISTERED = False
_QUERY_SERVICE: PortfolioMonitorQueryService = PortfolioMonitorQueryService()
_ACTION_SERVICE: PortfolioMonitorActionService = PortfolioMonitorActionService()
_SNAPSHOT_OVERRIDES: dict[str, str] | None = None


def set_snapshot_overrides(overrides: dict[str, str] | None) -> None:
    """Register artifact-path + vol-method overrides for the next snapshot-mode page load.

    Used by the headless ``capture_snapshot()`` pipeline so the CLI can inject
    positions-CSV / returns / vol-method etc. before Playwright navigates.
    Keys that match ``PortfolioArtifactFormState`` field names overwrite the
    defaults resolved from the query service. Pass ``None`` to clear.
    """
    global _SNAPSHOT_OVERRIDES
    _SNAPSHOT_OVERRIDES = dict(overrides) if overrides else None


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
    vol_method: str = "Fast"
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
    snapshot: PortfolioReportSnapshot | None = None
    warnings: list[str] = field(default_factory=list)
    is_loading: bool = False
    load_error: str | None = None
    active_job: str | None = None
    status_message: str = "Ready"
    snapshot_mode: bool = False
    selected_top_tab: str = "performance_usd"
    selected_perf_mode: dict[str, str] = field(default_factory=lambda: {"USD": "percent", "SGD": "percent"})
    selected_perf_window: dict[str, str] = field(default_factory=lambda: {"USD": "MTD", "SGD": "MTD"})
    progress_sink: InMemoryUiProgressSink = field(default_factory=InMemoryUiProgressSink)
    action_statuses: dict[str, ActionStatusState] = field(
        default_factory=lambda: {
            "live": ActionStatusState(),
            "flex": ActionStatusState(),
            "combined": ActionStatusState(),
            "security-reference": ActionStatusState(),
            "etf": ActionStatusState(),
        }
    )


def _normalize_vol_method_label(value: str) -> str:
    normalized = str(value).strip()
    if normalized in DEFAULT_VOL_METHOD_LABELS:
        return normalized
    resolved_key = resolve_vol_method_key(normalized, DEFAULT_VOL_METHOD_LABELS)
    for label, key in DEFAULT_VOL_METHOD_LABELS.items():
        if key == resolved_key:
            return label
    return next(iter(DEFAULT_VOL_METHOD_LABELS))


_TOP_TAB_KEYS = {"performance_usd", "performance_sgd", "risk", "artifacts"}


def _resolve_top_tab_key(value: str | None) -> str:
    normalized = str(value or "").strip().lower()
    aliases = {
        "": "performance_usd",
        "performance": "performance_usd",
        "perf": "performance_usd",
        "usd": "performance_usd",
        "sgd": "performance_sgd",
        "perf_sgd": "performance_sgd",
    }
    if normalized in _TOP_TAB_KEYS:
        return normalized
    return aliases.get(normalized, "performance_usd")


def _apply_snapshot_overrides(
    state: PortfolioPageState, overrides: dict[str, str] | None
) -> None:
    if not overrides:
        return
    form = state.artifact_form
    for key, value in overrides.items():
        if value is None:
            continue
        if not hasattr(form, key):
            continue
        if key == "vol_method":
            setattr(form, key, _normalize_vol_method_label(str(value)))
        else:
            setattr(form, key, str(value))


def _positions_csv_ready_for_autoload(value: str) -> bool:
    normalized = value.strip()
    return bool(normalized) and Path(normalized).exists()


def _initial_dashboard_status(positions_csv_path: str) -> str:
    if _positions_csv_ready_for_autoload(positions_csv_path):
        return "Ready. Click Refresh Snapshot to load the current artifacts."
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
    async def portfolio_page(
        snapshot: str | None = None,
        tab: str | None = None,
    ) -> None:  # noqa: ARG001
        state = _build_initial_state(_QUERY_SERVICE)
        state.snapshot_mode = str(snapshot or "").strip() in {"1", "true", "yes"}
        state.selected_top_tab = _resolve_top_tab_key(tab)
        if state.snapshot_mode:
            _apply_snapshot_overrides(state, _SNAPSHOT_OVERRIDES)

        @ui.refreshable
        def render() -> None:
            _render_portfolio_page(state)

        async def load_snapshot() -> None:
            if not _positions_csv_ready_for_autoload(state.artifact_form.positions_csv_path):
                state.snapshot = None
                state.warnings = []
                state.load_error = None
                state.is_loading = False
                state.status_message = _initial_dashboard_status(state.artifact_form.positions_csv_path)
                render.refresh()
                return
            state.is_loading = True
            state.load_error = None
            state.status_message = "Loading portfolio snapshot..."
            render.refresh()
            try:
                inputs = _artifact_inputs_from_form(state.artifact_form)
                snapshot = await asyncio.to_thread(_QUERY_SERVICE.load_snapshot, inputs)
            except Exception as exc:
                state.snapshot = None
                state.warnings = []
                state.load_error = str(exc)
                state.status_message = "Snapshot load failed"
            else:
                state.snapshot = snapshot
                state.warnings = list(snapshot.warnings)
                state.status_message = f"Loaded snapshot as of {snapshot.as_of}"
            finally:
                state.is_loading = False
                render.refresh()

        async def initialize_page() -> None:
            state.snapshot = None
            state.warnings = []
            state.load_error = None
            state.is_loading = False
            state.status_message = _initial_dashboard_status(state.artifact_form.positions_csv_path)
            render.refresh()
            if state.snapshot_mode and _positions_csv_ready_for_autoload(
                state.artifact_form.positions_csv_path
            ):
                await load_snapshot()

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
                    _set_action_success(state, action_name, message="Live positions refreshed", output_path=str(output_path))
                elif action_name == "flex":
                    action_inputs = _flex_inputs_from_form(state.flex_form)
                    output_path = await asyncio.to_thread(
                        _ACTION_SERVICE.rebuild_flex_performance,
                        action_inputs,
                        sink=state.progress_sink,
                    )
                    state.artifact_form.performance_output_dir = str(output_path.parent)
                    _set_action_success(state, action_name, message="Flex performance refreshed", output_path=str(output_path))
                elif action_name == "combined":
                    action_inputs = _combined_inputs_from_form(state)
                    output_path = await asyncio.to_thread(
                        _ACTION_SERVICE.generate_combined_report,
                        action_inputs,
                        sink=state.progress_sink,
                    )
                    _set_action_success(state, action_name, message="Combined report generated", output_path=str(output_path))
                elif action_name == "security-reference":
                    output_path = await asyncio.to_thread(
                        _ACTION_SERVICE.sync_security_reference,
                        output_path=_optional_text(state.reference_form.security_reference_output_path),
                        sink=state.progress_sink,
                    )
                    state.artifact_form.security_reference_path = str(output_path)
                    _set_action_success(state, action_name, message="Security reference synced", output_path=str(output_path))
                elif action_name == "etf":
                    action_inputs = _etf_inputs_from_form(state.reference_form)
                    output_path = await asyncio.to_thread(
                        _ACTION_SERVICE.sync_etf_sector,
                        action_inputs,
                        sink=state.progress_sink,
                    )
                    _set_action_success(state, action_name, message="ETF sector lookthrough synced", output_path=str(output_path))
                else:
                    raise ValueError(f"Unsupported action: {action_name}")
                state.status_message = state.action_statuses[action_name].message
                await load_snapshot()
            except Exception as exc:
                _set_action_error(state, action_name, str(exc))
                state.status_message = f"Action failed: {exc}"
                render.refresh()
            finally:
                state.active_job = None
                render.refresh()

        state._load_snapshot = load_snapshot  # type: ignore[attr-defined]
        state._run_action = run_action  # type: ignore[attr-defined]
        state._refresh_ui = render.refresh  # type: ignore[attr-defined]
        render()
        ui.timer(0.1, lambda: asyncio.create_task(initialize_page()), once=True)
        ui.timer(0.5, lambda: render.refresh() if state.active_job is not None else None)

    _REGISTERED = True


def _build_initial_state(query_service: PortfolioMonitorQueryService) -> PortfolioPageState:
    inputs = query_service.resolve_inputs()
    positions_path = str(inputs.positions_csv_path or "")
    performance_output_dir = str(inputs.performance_output_dir or "")
    flex_query_id = _resolve_local_env_value(DEFAULT_IBKR_FLEX_QUERY_ID_ENV_VAR)
    flex_token = _resolve_local_env_value(DEFAULT_IBKR_FLEX_TOKEN_ENV_VAR)
    live_account_id = _resolve_default_live_account_id()
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
            vol_method=_normalize_vol_method_label(inputs.vol_method),
            inter_asset_corr=inputs.inter_asset_corr,
        ),
        live_form=LiveActionFormState(output_path=positions_path, account_id=live_account_id),
        flex_form=FlexActionFormState(
            output_dir=performance_output_dir,
            query_id=flex_query_id,
            token=flex_token,
        ),
        export_form=ExportActionFormState(output_path=str(Path(performance_output_dir).parent / "portfolio_combined_report.html")),
        reference_form=ReferenceActionFormState(security_reference_output_path=str(inputs.security_reference_path or "")),
        status_message=_initial_dashboard_status(positions_path),
    )


def _render_portfolio_page(state: PortfolioPageState) -> None:
    add_dashboard_styles()
    with ui.column().classes("w-full max-w-[1600px] mx-auto p-4 pm-shell"):
        _render_header(state)
        if not state.snapshot_mode:
            _render_toolbar(state)
        _render_feedback(state)
        _render_main_tabs(state)
        if not state.snapshot_mode:
            _render_action_console(state)
            _render_logs(state)
        if state.snapshot_mode and not state.is_loading:
            as_of = getattr(state.snapshot, "as_of", "") if state.snapshot is not None else ""
            has_snapshot = "1" if state.snapshot is not None else "0"
            ui.html(
                f'<div id="snapshot-ready" data-as-of="{as_of}" data-has-snapshot="{has_snapshot}"></div>'
            )


def _render_header(state: PortfolioPageState) -> None:
    with ui.card().classes("w-full pm-hero shadow-lg"):
        ui.label("Portfolio Monitor").classes("text-h4")
        ui.label(
            "NiceGUI portfolio surface for artifact-driven analysis and selected report-generation workflows."
        ).classes("text-body1 opacity-80")
        ui.label(state.status_message).classes("text-body2 opacity-80")


def _render_toolbar(state: PortfolioPageState) -> None:
    load_snapshot = getattr(state, "_load_snapshot", None)
    with ui.card().classes("w-full pm-card p-4"):
        ui.label("Artifacts").classes("text-h6")
        with ui.grid(columns=2).classes("w-full gap-3"):
            ui.input("Positions CSV").bind_value(state.artifact_form, "positions_csv_path").classes("w-full")
            ui.select(
                options=list(DEFAULT_VOL_METHOD_LABELS.keys()),
                label="Vol Method",
                value=state.artifact_form.vol_method,
            ).bind_value(state.artifact_form, "vol_method")
            ui.select(
                options=["historical", "corr_0", "corr_1"],
                label="Inter-asset corr",
                value=state.artifact_form.inter_asset_corr,
            ).bind_value(state.artifact_form, "inter_asset_corr")
            ui.input("Performance output dir").bind_value(state.artifact_form, "performance_output_dir").classes("w-full")
            ui.input("Performance history").bind_value(state.artifact_form, "performance_history_path").classes("w-full")
            ui.input("Performance report CSV").bind_value(state.artifact_form, "performance_report_csv_path").classes("w-full")
            ui.input("Returns JSON").bind_value(state.artifact_form, "returns_path").classes("w-full")
            ui.input("Proxy JSON").bind_value(state.artifact_form, "proxy_path").classes("w-full")
            ui.input("Regime JSON").bind_value(state.artifact_form, "regime_path").classes("w-full")
            ui.input("Security reference CSV").bind_value(state.artifact_form, "security_reference_path").classes("w-full")
            ui.input("Risk config YAML").bind_value(state.artifact_form, "risk_config_path").classes("w-full")
            ui.input("Allocation policy YAML").bind_value(state.artifact_form, "allocation_policy_path").classes("w-full")
        with ui.row().classes("items-center gap-3 mt-4"):
            button = ui.button("Refresh Snapshot", on_click=lambda: asyncio.create_task(load_snapshot())).props("color=primary")
            if state.is_loading or state.active_job is not None:
                button.props("disable")
            ui.label("Artifact paths are editable strings; loading is explicit and local-only.").classes("pm-muted")


def _render_feedback(state: PortfolioPageState) -> None:
    if state.is_loading:
        ui.label("Loading portfolio snapshot...").classes("pm-loading w-full")
    if state.load_error:
        ui.label(state.load_error).classes("pm-error w-full")
    for warning in state.warnings:
        ui.label(warning).classes("pm-warning w-full")


def _render_main_tabs(state: PortfolioPageState) -> None:
    if state.snapshot_mode:
        _render_static_top_tabs(state)
        return
    tabs = ui.tabs(
        on_change=lambda event: _update_top_tab(state, event.value),
    ).classes("w-full")
    with tabs:
        tab_perf_usd = ui.tab("Performance USD")
        tab_perf_sgd = ui.tab("Performance SGD")
        tab_risk = ui.tab("Risk")
        tab_artifacts = ui.tab("Artifacts")
    initial_tab = {
        "performance_usd": tab_perf_usd,
        "performance_sgd": tab_perf_sgd,
        "risk": tab_risk,
        "artifacts": tab_artifacts,
    }.get(state.selected_top_tab, tab_perf_usd)
    with ui.tab_panels(tabs, value=initial_tab).classes("w-full"):
        with ui.tab_panel(tab_perf_usd):
            if state.snapshot is None:
                _render_loading_panel("Performance USD")
            else:
                _render_performance_panel(state, state.snapshot.performance_usd_view_model)
        with ui.tab_panel(tab_perf_sgd):
            if state.snapshot is None:
                _render_loading_panel("Performance SGD")
            else:
                _render_performance_panel(state, state.snapshot.performance_sgd_view_model)
        with ui.tab_panel(tab_risk):
            if state.snapshot is None:
                _render_loading_panel("Risk")
            else:
                _render_risk_panel(state.snapshot)
        with ui.tab_panel(tab_artifacts):
            _render_artifact_metadata(state)


def _render_static_top_tabs(state: PortfolioPageState) -> None:
    tabs = [
        ("performance_usd", "Performance USD"),
        ("performance_sgd", "Performance SGD"),
        ("risk", "Risk"),
        ("artifacts", "Artifacts"),
    ]
    with ui.row().classes("w-full pm-static-tab-buttons").props("data-static-tab-buttons=top"):
        for key, label in tabs:
            button = ui.element("button").classes("pm-static-tab-button")
            button.props(f"type=button data-tab-target={key}")
            if state.selected_top_tab == key:
                button.classes(add="is-active")
            with button:
                ui.label(label)

    for key, label in tabs:
        panel = ui.element("section").classes("pm-static-tab-panel")
        panel.props(f"data-static-tab-panel=top data-tab-key={key}")
        if state.selected_top_tab != key:
            panel.props("hidden")
        with panel:
            if key == "performance_usd":
                if state.snapshot is None:
                    _render_loading_panel(label)
                else:
                    _render_performance_panel(state, state.snapshot.performance_usd_view_model)
            elif key == "performance_sgd":
                if state.snapshot is None:
                    _render_loading_panel(label)
                else:
                    _render_performance_panel(state, state.snapshot.performance_sgd_view_model)
            elif key == "risk":
                if state.snapshot is None:
                    _render_loading_panel(label)
                else:
                    _render_risk_panel(state.snapshot, static_mode=True)
            else:
                _render_artifact_metadata(state)


def _render_loading_panel(title: str) -> None:
    with ui.card().classes("w-full pm-card p-4"):
        ui.label(title).classes("text-h6")
        ui.label("Waiting for the portfolio snapshot to load.").classes("pm-muted")


def _render_performance_panel(state: PortfolioPageState, view_model: PerformanceReportViewModel) -> None:
    currency = view_model.primary_currency
    selected_mode = state.selected_perf_mode[currency]
    selected_window = state.selected_perf_window[currency]
    with ui.column().classes("w-full gap-4"):
        with ui.card().classes("w-full pm-card p-4"):
            ui.label(f"{currency} performance overview").classes("text-h6")
            with ui.row().classes("w-full gap-4 wrap"):
                for card in view_model.summary_cards:
                    render_status_card(
                        title=card.label,
                        value=_format_summary_card_value(card.primary_value, card.value_kind),
                        detail=card.secondary_label,
                    )
        with ui.card().classes("w-full pm-card p-4"):
            with ui.row().classes("items-center gap-3"):
                ui.toggle(
                    {"percent": "Percent", "dollar": "Dollar"},
                    value=selected_mode,
                    on_change=lambda event, c=currency: _update_perf_mode(state, c, event.value),
                )
                ui.toggle(
                    {"MTD": "MTD", "YTD": "YTD", "1Y": "1Y", "FULL": "Full"},
                    value=selected_window,
                    on_change=lambda event, c=currency: _update_perf_window(state, c, event.value),
                )
            figure_spec = dict(view_model.chart_specs[selected_mode][selected_window])
            ui.plotly(_with_plotly_config(figure_spec)).classes("w-full h-[560px]")
        with ui.row().classes("w-full gap-4 wrap"):
            with ui.card().classes("grow basis-[560px] pm-card p-4"):
                ui.label("Horizon Metrics").classes("text-h6")
                render_table(
                    columns=[
                        {"name": "label", "label": "Window", "field": "label"},
                        {"name": "twr_return", "label": "TWR", "field": "twr_return"},
                        {"name": "mwr_return", "label": "MWR", "field": "mwr_return"},
                        {"name": "annualized_return", "label": "Ann Return", "field": "annualized_return"},
                        {"name": "annualized_vol", "label": "Ann Vol", "field": "annualized_vol"},
                        {"name": "sharpe_ratio", "label": "Sharpe", "field": "sharpe_ratio"},
                        {"name": "max_drawdown", "label": "Max DD", "field": "max_drawdown"},
                    ],
                    rows=[_performance_metric_row_to_table_row(row) for row in view_model.horizon_rows],
                    row_key="label",
                )
            with ui.card().classes("grow basis-[560px] pm-card p-4"):
                ui.label("Historical Years").classes("text-h6")
                render_table(
                    columns=[
                        {"name": "label", "label": "Year", "field": "label"},
                        {"name": "twr_return", "label": "TWR", "field": "twr_return"},
                        {"name": "mwr_return", "label": "MWR", "field": "mwr_return"},
                        {"name": "annualized_vol", "label": "Ann Vol", "field": "annualized_vol"},
                        {"name": "sharpe_ratio", "label": "Sharpe", "field": "sharpe_ratio"},
                        {"name": "max_drawdown", "label": "Max DD", "field": "max_drawdown"},
                    ],
                    rows=[_performance_metric_row_to_table_row(row) for row in view_model.yearly_rows],
                    row_key="label",
                )


def _render_risk_panel(snapshot: PortfolioReportSnapshot, *, static_mode: bool = False) -> None:
    risk = snapshot.risk_view_model
    if static_mode:
        _render_static_risk_tabs(risk)
        return
    with ui.column().classes("w-full gap-4"):
        risk_tabs = ui.tabs().classes("w-full")
        with risk_tabs:
            tab_overview = ui.tab("Main Overview")
            tab_eq = ui.tab("Equity")
            tab_fi = ui.tab("Fixed Income")
            tab_cm = ui.tab("Commodity")
            tab_fx = ui.tab("FX")
            tab_macro = ui.tab("Macro")
        with ui.tab_panels(risk_tabs, value=tab_overview).classes("w-full"):
            with ui.tab_panel(tab_overview):
                _render_risk_overview(risk)
            with ui.tab_panel(tab_eq):
                _render_risk_equity(risk)
            with ui.tab_panel(tab_fi):
                _render_risk_fixed_income(risk)
            with ui.tab_panel(tab_cm):
                _render_risk_commodity(risk)
            with ui.tab_panel(tab_fx):
                _render_risk_fx(risk)
            with ui.tab_panel(tab_macro):
                _render_risk_macro(risk)


def _render_static_risk_tabs(risk) -> None:
    tabs = [
        ("overview", "Main Overview", _render_risk_overview),
        ("eq", "Equity", _render_risk_equity),
        ("fi", "Fixed Income", _render_risk_fixed_income),
        ("cm", "Commodity", _render_risk_commodity),
        ("fx", "FX", _render_risk_fx),
        ("macro", "Macro", _render_risk_macro),
    ]
    default_key = "overview"
    with ui.column().classes("w-full gap-4"):
        with ui.row().classes("w-full pm-static-tab-buttons").props("data-static-tab-buttons=risk"):
            for key, label, _renderer in tabs:
                button = ui.element("button").classes("pm-static-tab-button")
                button.props(f"type=button data-tab-target={key}")
                if key == default_key:
                    button.classes(add="is-active")
                with button:
                    ui.label(label)
        for key, _label, renderer in tabs:
            panel = ui.element("section").classes("pm-static-tab-panel")
            panel.props(f"data-static-tab-panel=risk data-tab-key={key}")
            if key != default_key:
                panel.props("hidden")
            with panel:
                renderer(risk)


def _render_risk_overview(risk) -> None:
    with ui.column().classes("w-full gap-4"):
        with ui.card().classes("w-full pm-card p-4"):
            ui.label("Portfolio Summary").classes("text-h6")
            with ui.row().classes("w-full gap-4 wrap"):
                for label, value in [
                    ("Vol Long-Term (5Y)", format_percent(risk.summary.portfolio_vol_5y_realized)),
                    ("Vol Fast (1M/3M)", format_percent(risk.summary.portfolio_vol_geomean_1m_3m)),
                    ("Vol Forward-Looking", format_percent(risk.summary.portfolio_vol_forward_looking)),
                    ("Funded AUM USD", format_amount(risk.summary.funded_aum_usd, decimals=0)),
                    ("Funded AUM SGD", format_amount(risk.summary.funded_aum_sgd, decimals=0)),
                    ("Gross Exposure", format_amount(risk.summary.gross_exposure, decimals=0)),
                    ("Net Exposure", format_amount(risk.summary.net_exposure, decimals=0)),
                    ("Mapping Coverage", f"{risk.summary.mapped_positions}/{risk.summary.total_positions}"),
                ]:
                    render_status_card(title=label, value=value)
            ui.label("FX excluded from portfolio vol aggregation.").classes("pm-muted text-caption mt-2")
        with ui.card().classes("w-full pm-card p-4"):
            ui.label("Asset Class Summary").classes("text-h6")
            render_table(
                columns=[
                    {"name": "asset_class", "label": "Asset Class", "field": "asset_class"},
                    {"name": "exposure_usd", "label": "Net Exposure ($)", "field": "exposure_usd"},
                    {"name": "gross_exposure_usd", "label": "Gross Exposure ($)", "field": "gross_exposure_usd"},
                    {"name": "dollar_weight", "label": "Portfolio Allocation %", "field": "dollar_weight"},
                    {"name": "risk_contribution_estimated", "label": "Vol Contribution %", "field": "risk_contribution_estimated"},
                ],
                rows=[
                    {
                        "asset_class": row.asset_class,
                        "exposure_usd": format_amount(row.exposure_usd),
                        "gross_exposure_usd": format_amount(row.gross_exposure_usd),
                        "dollar_weight": format_percent(row.dollar_weight),
                        "risk_contribution_estimated": format_percent(row.risk_contribution_estimated),
                    }
                    for row in risk.allocation_summary
                ],
                row_key="asset_class",
            )
        _render_policy_drift_asset_class(risk)


def _render_risk_equity(risk) -> None:
    eq_rows = [r for r in risk.risk_rows if r.asset_class == "EQ"]
    with ui.column().classes("w-full gap-4"):
        _render_dm_em_policy_drift_summary(risk.policy_drift_country)
        with ui.row().classes("w-full gap-4 wrap"):
            render_risk_chart_block(
                title="Equity Country Active Weight",
                figure=build_policy_drift_figure(risk.policy_drift_country),
                columns=_policy_drift_columns(include_risk=False),
                rows=[_policy_drift_row_to_table_row(row, include_risk=False) for row in risk.policy_drift_country],
                row_key="bucket",
            )
            render_risk_chart_block(
                title="US Sector Active Weight (vs SPY)",
                figure=build_policy_drift_figure(risk.policy_drift_sector),
                columns=_policy_drift_columns(include_risk=False),
                rows=[_policy_drift_row_to_table_row(row, include_risk=False) for row in risk.policy_drift_sector],
                row_key="bucket",
            )
        _render_position_subtable("Equity Holdings", eq_rows)


def _render_policy_drift_asset_class(risk) -> None:
    rows = [_policy_drift_row_to_table_row(row, include_risk=False) for row in risk.policy_drift_asset_class]
    columns = [
        {"name": "bucket", "label": "Bucket", "field": "bucket"},
        {"name": "scope", "label": "Scope", "field": "scope"},
        {"name": "current_weight", "label": "Current %", "field": "current_weight"},
        {"name": "policy_weight", "label": "Policy %", "field": "policy_weight"},
        {"name": "active_weight", "label": "Active %", "field": "active_weight"},
    ]
    with ui.card().classes("w-full pm-card p-4"):
        ui.label("Portfolio Drift - Asset Class").classes("text-h6")
        if not rows:
            ui.label("No data").classes("text-body2 pm-muted")
            render_table(columns=columns, rows=rows, row_key="bucket")
            return
        with ui.row().classes("w-full gap-4 items-start wrap"):
            with ui.column().classes("grow basis-[720px] min-w-[340px]"):
                ui.plotly(build_policy_drift_figure(risk.policy_drift_asset_class)).classes("w-full h-[360px]")
            with ui.column().classes("grow basis-[420px] min-w-[320px]"):
                render_table(columns=columns, rows=rows, row_key="bucket")


def _render_dm_em_policy_drift_summary(policy_drift_country: list[PolicyDriftRow]) -> None:
    region_map = _load_dm_em_bucket_map()
    summary: dict[str, PolicyDriftRow] = {}
    for row in policy_drift_country:
        region = region_map.get(row.bucket.upper())
        if region not in ("DM", "EM"):
            continue
        current = summary.get(region)
        if current is None:
            summary[region] = PolicyDriftRow(
                bucket=region,
                scope="EQ",
                current_weight=row.current_weight,
                policy_weight=row.policy_weight,
                active_weight=row.active_weight,
                current_risk_contribution=row.current_risk_contribution,
            )
            continue
        summary[region] = PolicyDriftRow(
            bucket=region,
            scope="EQ",
            current_weight=current.current_weight + row.current_weight,
            policy_weight=current.policy_weight + row.policy_weight,
            active_weight=current.active_weight + row.active_weight,
            current_risk_contribution=current.current_risk_contribution + row.current_risk_contribution,
        )
    rows = [summary[key] for key in ("DM", "EM") if key in summary]
    if not rows:
        return
    render_risk_chart_block(
        title="DM / EM Active Weight",
        figure=build_policy_drift_figure(rows),
        columns=_policy_drift_columns(include_risk=False),
        rows=[_policy_drift_row_to_table_row(row, include_risk=False) for row in rows],
        row_key="bucket",
    )


@lru_cache(maxsize=1)
def _load_dm_em_bucket_map() -> dict[str, str]:
    path = (
        Path(__file__).resolve().parents[4]
        / "configs"
        / "portfolio_monitor"
        / "eq_country_lookthrough.csv"
    )
    mapping: dict[str, str] = {}
    if not path.exists():
        return mapping
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        dm_buckets: set[str] = set()
        em_buckets: set[str] = set()
        for row in reader:
            region = (row.get("eq_country") or "").strip().upper()
            bucket = (row.get("country_bucket") or "").strip().upper()
            if not bucket or bucket.endswith("-OTHERS") or bucket in {"OTHER", "OTHERS"}:
                continue
            if region == "DM":
                dm_buckets.add(bucket)
            elif region == "EM":
                em_buckets.add(bucket)
    for bucket in dm_buckets - em_buckets:
        mapping[bucket] = "DM"
    for bucket in em_buckets - dm_buckets:
        mapping[bucket] = "EM"
    mapping["DM-OTHERS"] = "DM"
    mapping["EM-OTHERS"] = "EM"
    return mapping


def _render_risk_fixed_income(risk) -> None:
    fi_rows = [r for r in risk.risk_rows if r.asset_class == "FI"]
    total_fi_exposure = sum(r.exposure_usd for r in fi_rows)
    weighted_duration = (
        sum((r.duration or 0.0) * r.exposure_usd for r in fi_rows) / total_fi_exposure
        if total_fi_exposure
        else 0.0
    )
    with ui.column().classes("w-full gap-4"):
        with ui.card().classes("w-full pm-card p-4"):
            ui.label("Fixed Income Summary").classes("text-h6")
            with ui.row().classes("w-full gap-4 wrap"):
                render_status_card(title="Total FI Net Exposure", value=format_amount(total_fi_exposure, decimals=0))
                render_status_card(title="Weighted Avg Duration", value=format_ratio(weighted_duration))
                render_status_card(title="Position Count", value=str(len(fi_rows)))
        with ui.card().classes("w-full pm-card p-4"):
            ui.label("Tenor Bucket Allocation").classes("text-h6")
            render_table(
                columns=_breakdown_columns(),
                rows=[_breakdown_row_to_table_row(row) for row in risk.fi_tenor_breakdown],
                row_key="bucket",
            )
        _render_position_subtable("FI Instruments", fi_rows)


def _render_risk_commodity(risk) -> None:
    cm_rows = [r for r in risk.risk_rows if r.asset_class == "CM"]
    sector_rows: dict[str, dict[str, float]] = {}
    total_exposure = sum(r.exposure_usd for r in cm_rows)
    total_risk = sum(r.risk_contribution_estimated for r in cm_rows)
    for row in cm_rows:
        code = (getattr(row, "cm_sector", "") or "").upper()
        bucket = _CM_SECTOR_LABELS.get(code, "Unmapped") if code else "Unmapped"
        agg = sector_rows.setdefault(
            bucket, {"exposure_usd": 0.0, "gross_exposure_usd": 0.0, "risk_contribution_estimated": 0.0}
        )
        agg["exposure_usd"] += row.exposure_usd
        agg["gross_exposure_usd"] += row.gross_exposure_usd
        agg["risk_contribution_estimated"] += row.risk_contribution_estimated
    with ui.column().classes("w-full gap-4"):
        with ui.card().classes("w-full pm-card p-4"):
            ui.label("Commodity Sector Summary").classes("text-h6")
            if not sector_rows:
                ui.label("No commodity positions.").classes("pm-muted")
            else:
                render_table(
                    columns=[
                        {"name": "bucket", "label": "Sector", "field": "bucket"},
                        {"name": "exposure_usd", "label": "Net Exposure ($)", "field": "exposure_usd"},
                        {"name": "gross_exposure_usd", "label": "Gross Exposure ($)", "field": "gross_exposure_usd"},
                        {"name": "within_cm_weight", "label": "Within-CM Weight %", "field": "within_cm_weight"},
                        {"name": "risk_contribution_estimated", "label": "Vol Contribution %", "field": "risk_contribution_estimated"},
                    ],
                    rows=[
                        {
                            "bucket": bucket,
                            "exposure_usd": format_amount(agg["exposure_usd"]),
                            "gross_exposure_usd": format_amount(agg["gross_exposure_usd"]),
                            "within_cm_weight": format_percent(
                                agg["exposure_usd"] / total_exposure if total_exposure else 0.0
                            ),
                            "risk_contribution_estimated": format_percent(agg["risk_contribution_estimated"]),
                        }
                        for bucket, agg in sorted(sector_rows.items(), key=lambda kv: -kv[1]["exposure_usd"])
                    ],
                    row_key="bucket",
                )
        _render_commodity_correlation_heatmap()
        _render_position_subtable("Commodity Holdings", cm_rows)


def _render_commodity_correlation_heatmap() -> None:
    proxies = _load_commodity_sector_proxies()
    if not proxies:
        return
    matrix = _compute_commodity_sector_correlation(proxies)
    if matrix is None:
        with ui.card().classes("w-full pm-card p-4"):
            ui.label("Commodity Sector Correlation").classes("text-h6")
            ui.label("Proxy return data unavailable — heatmap skipped.").classes("pm-muted")
        return
    labels, corr = matrix
    display_labels = [_CM_SECTOR_LABELS.get(code, code) for code in labels]
    figure = {
        "data": [
            {
                "type": "heatmap",
                "z": corr,
                "x": display_labels,
                "y": display_labels,
                "zmin": -1,
                "zmax": 1,
                "colorscale": "RdBu",
                "reversescale": True,
                "hovertemplate": "%{x} vs %{y}<br>corr=%{z:.2f}<extra></extra>",
            }
        ],
        "layout": {
            "template": "plotly_white",
            "height": 360,
            "margin": {"l": 100, "r": 40, "t": 24, "b": 80},
            "xaxis": {"tickangle": -20},
        },
        "config": {"displayModeBar": False, "responsive": True},
    }
    with ui.card().classes("w-full pm-card p-4"):
        ui.label("Commodity Sector Correlation").classes("text-h6")
        ui.plotly(figure).classes("w-full h-[380px]")


@lru_cache(maxsize=1)
def _load_commodity_sector_proxies() -> tuple[tuple[str, str], ...]:
    import yaml

    path = (
        Path(__file__).resolve().parents[4]
        / "configs"
        / "portfolio_monitor"
        / "report_config.yaml"
    )
    if not path.exists():
        return ()
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    proxies = (data.get("risk_report") or {}).get("commodity_sector_proxies") or {}
    return tuple((str(code).upper(), str(symbol)) for code, symbol in proxies.items() if symbol)


def _compute_commodity_sector_correlation(
    proxies: tuple[tuple[str, str], ...],
) -> tuple[list[str], list[list[float]]] | None:
    from market_helper.data_sources.yahoo_finance import YahooFinanceClient
    from market_helper.domain.portfolio_monitor.services.yahoo_returns import (
        ensure_symbol_return_cache,
    )
    from market_helper.reporting.risk_html import pairwise_corr

    client = YahooFinanceClient()
    series_by_code: dict[str, list[float]] = {}
    for code, symbol in proxies:
        try:
            cache = ensure_symbol_return_cache(symbol, yahoo_client=client, period="5y")
        except Exception:
            continue
        if cache.series is None or cache.series.empty:
            continue
        series_by_code[code] = cache.series.tolist()
    if len(series_by_code) < 2:
        return None
    labels = [code for code, _ in proxies if code in series_by_code]
    corr = [
        [
            1.0 if a == b else pairwise_corr(series_by_code[a], series_by_code[b])
            for b in labels
        ]
        for a in labels
    ]
    return labels, corr


_CM_SECTOR_LABELS: dict[str, str] = {
    "PM": "Precious Metals",
    "IM": "Industrial Metals",
    "EN": "Energy",
    "AG": "Agriculture",
}


def _render_risk_fx(risk) -> None:
    fx_rows = [r for r in risk.risk_rows if r.asset_class == "FX"]
    with ui.column().classes("w-full gap-4"):
        with ui.card().classes("w-full pm-card p-4"):
            ui.label("FX Allocation").classes("text-h6")
            ui.label("Vol Contribution % omitted in MVP (FX vol unstable).").classes("pm-muted text-caption")
        _render_position_subtable("FX Positions", fx_rows, include_vol_contribution=False)


def _render_risk_macro(risk) -> None:
    macro_rows = [r for r in risk.risk_rows if r.asset_class == "MACRO"]
    with ui.column().classes("w-full gap-4"):
        _render_position_subtable("Macro Instruments", macro_rows)


def _render_position_subtable(
    title: str,
    rows: list[RiskMetricsRow],
    *,
    include_vol_contribution: bool = True,
) -> None:
    with ui.card().classes("w-full pm-card p-4"):
        ui.label(title).classes("text-h6")
        if not rows:
            ui.label("No positions in this asset class.").classes("pm-muted")
            return
        columns = [
            {"name": "account", "label": "Account", "field": "account"},
            {"name": "display_ticker", "label": "Ticker", "field": "display_ticker"},
            {"name": "display_name", "label": "Name", "field": "display_name"},
            {"name": "instrument_type", "label": "Type", "field": "instrument_type"},
            {"name": "gross_exposure_usd", "label": "Gross Exposure ($)", "field": "gross_exposure_usd"},
            {"name": "exposure_usd", "label": "Net Exposure ($)", "field": "exposure_usd"},
            {"name": "dollar_weight", "label": "Portfolio Allocation %", "field": "dollar_weight"},
            {"name": "vol_5y_realized", "label": "Vol Long-Term", "field": "vol_5y_realized"},
            {"name": "vol_geomean_1m_3m", "label": "Vol Fast", "field": "vol_geomean_1m_3m"},
        ]
        if include_vol_contribution:
            columns.append({"name": "risk_contribution_estimated", "label": "Vol Contribution %", "field": "risk_contribution_estimated"})
        columns.append({"name": "mapping_status", "label": "Mapping", "field": "mapping_status"})
        render_table(
            columns=columns,
            rows=[_risk_row_to_table_row(row) for row in rows],
            row_key="internal_id",
        )


def _render_artifact_metadata(state: PortfolioPageState) -> None:
    snapshot = state.snapshot
    if snapshot is not None:
        metadata_rows = [
            {"label": "Positions CSV", "value": format_path(snapshot.artifact_metadata.positions_csv_path)},
            {"label": "Positions as of", "value": format_text(snapshot.artifact_metadata.positions_as_of)},
            {"label": "Performance output dir", "value": format_path(snapshot.artifact_metadata.performance_output_dir)},
            {"label": "Performance history", "value": format_path(snapshot.artifact_metadata.performance_history_path)},
            {"label": "Performance report CSV", "value": format_path(snapshot.artifact_metadata.performance_report_csv_path)},
            {"label": "Returns JSON", "value": format_path(snapshot.artifact_metadata.returns_path)},
            {"label": "Proxy JSON", "value": format_path(snapshot.artifact_metadata.proxy_path)},
            {"label": "Regime JSON", "value": format_path(snapshot.artifact_metadata.regime_path)},
            {"label": "Security reference", "value": format_path(snapshot.artifact_metadata.security_reference_path)},
            {"label": "Risk config", "value": format_path(snapshot.artifact_metadata.risk_config_path)},
            {"label": "Allocation policy", "value": format_path(snapshot.artifact_metadata.allocation_policy_path)},
        ]
    else:
        metadata_rows = [
            {"label": "Positions CSV", "value": state.artifact_form.positions_csv_path or "n/a"},
            {"label": "Performance output dir", "value": state.artifact_form.performance_output_dir or "n/a"},
            {"label": "Performance history", "value": state.artifact_form.performance_history_path or "n/a"},
            {"label": "Performance report CSV", "value": state.artifact_form.performance_report_csv_path or "n/a"},
            {"label": "Returns JSON", "value": state.artifact_form.returns_path or "n/a"},
            {"label": "Proxy JSON", "value": state.artifact_form.proxy_path or "n/a"},
            {"label": "Regime JSON", "value": state.artifact_form.regime_path or "n/a"},
            {"label": "Security reference", "value": state.artifact_form.security_reference_path or "n/a"},
            {"label": "Risk config", "value": state.artifact_form.risk_config_path or "n/a"},
            {"label": "Allocation policy", "value": state.artifact_form.allocation_policy_path or "n/a"},
        ]
    with ui.card().classes("w-full pm-card p-4"):
        ui.label("Resolved artifact metadata").classes("text-h6")
        render_table(
            columns=[
                {"name": "label", "label": "Item", "field": "label"},
                {"name": "value", "label": "Value", "field": "value"},
            ],
            rows=metadata_rows,
            row_key="label",
        )


def _render_action_console(state: PortfolioPageState) -> None:
    run_action = getattr(state, "_run_action", None)
    with ui.expansion("Actions", icon="build", value=True).classes("w-full pm-card"):
        with ui.column().classes("w-full p-4 gap-4"):
            with ui.row().classes("w-full gap-4 wrap"):
                render_action_card(
                    title="Live Positions",
                    subtitle="Refresh the tracked position CSV from a local TWS / IB Gateway session.",
                    status=state.action_statuses["live"].status,
                    message=state.action_statuses["live"].message,
                    progress_summary=_action_progress_summary(state, "live"),
                    last_output_path=state.action_statuses["live"].last_output_path,
                    body=lambda: _render_live_action_body(state, run_action),
                )
                render_action_card(
                    title="Flex Performance",
                    subtitle="Rebuild flex-based performance artifacts from local XML or live Flex credentials.",
                    status=state.action_statuses["flex"].status,
                    message=state.action_statuses["flex"].message,
                    progress_summary=_action_progress_summary(state, "flex"),
                    last_output_path=state.action_statuses["flex"].last_output_path,
                    body=lambda: _render_flex_action_body(state, run_action),
                )
                render_action_card(
                    title="Static Export",
                    subtitle="Regenerate the compatibility combined HTML report from the current artifact form.",
                    status=state.action_statuses["combined"].status,
                    message=state.action_statuses["combined"].message,
                    progress_summary=_action_progress_summary(state, "combined"),
                    last_output_path=state.action_statuses["combined"].last_output_path,
                    body=lambda: _render_export_action_body(state, run_action),
                )
                render_action_card(
                    title="Reference Sync",
                    subtitle="Sync security reference outputs and ETF sector lookthrough with explicit inputs.",
                    status=_combined_reference_status(state),
                    message=_combined_reference_message(state),
                    progress_summary=_combined_reference_progress(state),
                    last_output_path=_combined_reference_output(state),
                    body=lambda: _render_reference_action_body(state, run_action),
                )


def _render_live_action_body(state: PortfolioPageState, run_action) -> None:
    disabled = state.active_job is not None
    ui.input("Output path").bind_value(state.live_form, "output_path").classes("w-full")
    with ui.row().classes("w-full gap-3 wrap"):
        ui.input("Host").bind_value(state.live_form, "host")
        ui.input("Port").bind_value(state.live_form, "port")
        ui.input("Client ID").bind_value(state.live_form, "client_id")
        ui.input("Timeout").bind_value(state.live_form, "timeout")
    with ui.expansion("Advanced", icon="tune").classes("w-full"):
        ui.input("Account ID").bind_value(state.live_form, "account_id").classes("w-full")
        ui.input("As Of").bind_value(state.live_form, "as_of").classes("w-full")
    button = ui.button("Run Live Refresh", on_click=lambda: asyncio.create_task(run_action("live"))).props("color=primary")
    if disabled:
        button.props("disable")


def _render_flex_action_body(state: PortfolioPageState, run_action) -> None:
    disabled = state.active_job is not None
    ui.input("Output dir").bind_value(state.flex_form, "output_dir").classes("w-full")
    ui.input("Flex XML path").bind_value(state.flex_form, "flex_xml_path").classes("w-full")
    with ui.expansion("Advanced", icon="tune").classes("w-full"):
        ui.input("Query ID").bind_value(state.flex_form, "query_id").classes("w-full")
        ui.input("Token").bind_value(state.flex_form, "token").classes("w-full")
        ui.input("From date").bind_value(state.flex_form, "from_date").classes("w-full")
        ui.input("To date").bind_value(state.flex_form, "to_date").classes("w-full")
        ui.input("Period").bind_value(state.flex_form, "period").classes("w-full")
        ui.input("XML output path").bind_value(state.flex_form, "xml_output_path").classes("w-full")
    button = ui.button("Run Flex Refresh", on_click=lambda: asyncio.create_task(run_action("flex"))).props("color=primary")
    if disabled:
        button.props("disable")


def _render_export_action_body(state: PortfolioPageState, run_action) -> None:
    disabled = state.active_job is not None
    ui.input("Combined HTML output").bind_value(state.export_form, "output_path").classes("w-full")
    button = ui.button("Generate Combined HTML", on_click=lambda: asyncio.create_task(run_action("combined"))).props("color=primary")
    if disabled:
        button.props("disable")


def _render_reference_action_body(state: PortfolioPageState, run_action) -> None:
    disabled = state.active_job is not None
    ui.input("Security reference output").bind_value(state.reference_form, "security_reference_output_path").classes("w-full")
    button_ref = ui.button("Sync Security Reference", on_click=lambda: asyncio.create_task(run_action("security-reference"))).props("outline")
    if disabled:
        button_ref.props("disable")
    ui.separator().classes("my-3")
    ui.input("ETF symbols (comma-separated)").bind_value(state.reference_form, "etf_symbols").classes("w-full")
    ui.input("ETF output path").bind_value(state.reference_form, "etf_output_path").classes("w-full")
    with ui.expansion("Advanced", icon="vpn_key").classes("w-full"):
        ui.input("FMP API Key").bind_value(state.reference_form, "api_key").classes("w-full")
    button_etf = ui.button("Sync ETF Sectors", on_click=lambda: asyncio.create_task(run_action("etf"))).props("outline")
    if disabled:
        button_etf.props("disable")


def _render_logs(state: PortfolioPageState) -> None:
    with ui.expansion("Run History", icon="receipt_long").classes("w-full pm-card"):
        with ui.column().classes("w-full p-4 gap-3"):
            ui.label("Workflow progress events").classes("text-subtitle1")
            rows = [
                {
                    "timestamp": event.timestamp,
                    "kind": event.kind,
                    "label": event.label,
                    "detail": event.detail or "",
                    "progress": _format_progress_event(event),
                }
                for event in reversed(state.progress_sink.events)
            ]
            with ui.element("div").classes("w-full pm-log"):
                render_table(
                    columns=[
                        {"name": "timestamp", "label": "Timestamp", "field": "timestamp"},
                        {"name": "kind", "label": "Kind", "field": "kind"},
                        {"name": "label", "label": "Label", "field": "label"},
                        {"name": "detail", "label": "Detail", "field": "detail"},
                        {"name": "progress", "label": "Progress", "field": "progress"},
                    ],
                    rows=rows,
                    row_key="timestamp",
                )


def _artifact_inputs_from_form(form: PortfolioArtifactFormState) -> PortfolioReportInputs:
    return PortfolioReportInputs(
        positions_csv_path=_required_text(form.positions_csv_path, "Positions CSV"),
        performance_output_dir=_optional_text(form.performance_output_dir),
        performance_history_path=_optional_text(form.performance_history_path),
        performance_report_csv_path=_optional_text(form.performance_report_csv_path),
        returns_path=_optional_text(form.returns_path),
        proxy_path=_optional_text(form.proxy_path),
        regime_path=_optional_text(form.regime_path),
        security_reference_path=_optional_text(form.security_reference_path),
        risk_config_path=_optional_text(form.risk_config_path),
        allocation_policy_path=_optional_text(form.allocation_policy_path),
        vol_method=form.vol_method,
        inter_asset_corr=form.inter_asset_corr,
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


def _format_summary_card_value(value: float | str | None, kind: str) -> str:
    if isinstance(value, str):
        return value
    if kind == "percent":
        return format_percent(value)
    if kind == "ratio":
        return format_ratio(value)
    return format_text(str(value) if value is not None else None)


def _performance_metric_row_to_table_row(row: PerformanceMetricRow) -> dict[str, str]:
    return {
        "label": row.label,
        "twr_return": format_percent(row.twr_return),
        "mwr_return": format_percent(row.mwr_return),
        "annualized_return": format_percent(row.annualized_return),
        "annualized_vol": format_percent(row.annualized_vol),
        "sharpe_ratio": format_ratio(row.sharpe_ratio),
        "max_drawdown": format_percent(row.max_drawdown),
    }


def _policy_drift_row_to_table_row(row: PolicyDriftRow, *, include_risk: bool = True) -> dict[str, str]:
    out = {
        "bucket": row.bucket,
        "scope": row.scope,
        "current_weight": format_percent(row.current_weight),
        "policy_weight": format_percent(row.policy_weight),
        "active_weight": format_percent(row.active_weight),
    }
    if include_risk:
        out["current_risk_contribution"] = format_percent(row.current_risk_contribution)
    return out


def _risk_row_to_table_row(row: RiskMetricsRow) -> dict[str, str]:
    return {
        "internal_id": row.internal_id,
        "account": row.account,
        "display_ticker": row.display_ticker,
        "display_name": row.display_name,
        "asset_class": row.asset_class,
        "instrument_type": row.instrument_type,
        "gross_exposure_usd": format_amount(row.gross_exposure_usd),
        "exposure_usd": format_amount(row.exposure_usd),
        "dollar_weight": format_percent(row.dollar_weight),
        "vol_geomean_1m_3m": format_percent(row.vol_geomean_1m_3m),
        "vol_5y_realized": format_percent(row.vol_5y_realized),
        "vol_ewma": format_percent(row.vol_ewma),
        "risk_contribution_estimated": format_percent(row.risk_contribution_estimated),
        "mapping_status": row.mapping_status,
        "report_scope": row.report_scope,
    }


def _breakdown_columns() -> list[dict[str, str]]:
    return [
        {"name": "bucket", "label": "Bucket", "field": "bucket"},
        {"name": "parent", "label": "Scope", "field": "parent"},
        {"name": "exposure_usd", "label": "Net Exposure", "field": "exposure_usd"},
        {"name": "gross_exposure_usd", "label": "Gross Exposure", "field": "gross_exposure_usd"},
        {"name": "dollar_weight", "label": "Dollar%", "field": "dollar_weight"},
        {"name": "risk_contribution_estimated", "label": "Vol Contribution", "field": "risk_contribution_estimated"},
    ]


def _breakdown_row_to_table_row(row: BreakdownRow) -> dict[str, str]:
    return {
        "bucket": row.bucket,
        "parent": row.parent,
        "exposure_usd": format_amount(row.exposure_usd),
        "gross_exposure_usd": format_amount(row.gross_exposure_usd),
        "dollar_weight": format_percent(row.dollar_weight),
        "risk_contribution_estimated": format_percent(row.risk_contribution_estimated),
    }


def _policy_drift_columns(*, include_risk: bool = True) -> list[dict[str, str]]:
    columns = [
        {"name": "bucket", "label": "Bucket", "field": "bucket"},
        {"name": "scope", "label": "Scope", "field": "scope"},
        {"name": "current_weight", "label": "Current %", "field": "current_weight"},
        {"name": "policy_weight", "label": "Policy %", "field": "policy_weight"},
        {"name": "active_weight", "label": "Active %", "field": "active_weight"},
    ]
    if include_risk:
        columns.append(
            {"name": "current_risk_contribution", "label": "Current Risk %", "field": "current_risk_contribution"}
        )
    return columns


def _with_plotly_config(figure_spec: dict[str, Any]) -> dict[str, Any]:
    output = dict(figure_spec)
    output.setdefault("config", {"displayModeBar": False, "responsive": True})
    return output


_TOP_TAB_LABEL_TO_KEY: dict[str, str] = {
    "Performance USD": "performance_usd",
    "Performance SGD": "performance_sgd",
    "Risk": "risk",
    "Artifacts": "artifacts",
}


def _update_top_tab(state: PortfolioPageState, value: str) -> None:
    key = _TOP_TAB_LABEL_TO_KEY.get(str(value or "").strip())
    if key is None:
        return
    state.selected_top_tab = key


def _update_perf_mode(state: PortfolioPageState, currency: str, value: str) -> None:
    state.selected_perf_mode[currency] = value
    refresh = getattr(state, "_refresh_ui", None)
    if refresh is not None:
        refresh()


def _update_perf_window(state: PortfolioPageState, currency: str, value: str) -> None:
    state.selected_perf_window[currency] = value
    refresh = getattr(state, "_refresh_ui", None)
    if refresh is not None:
        refresh()


def _format_progress_event(event: Any) -> str:
    if event.completed is not None and event.total is not None:
        return f"{event.completed} / {event.total}"
    if event.current is not None and event.total is not None:
        return f"{event.current} / {event.total}"
    return ""


def _combined_reference_status(state: PortfolioPageState) -> str:
    statuses = [state.action_statuses["security-reference"].status, state.action_statuses["etf"].status]
    if "running" in statuses:
        return "running"
    if "error" in statuses:
        return "error"
    if "success" in statuses:
        return "success"
    return "idle"


def _combined_reference_message(state: PortfolioPageState) -> str:
    security_ref = state.action_statuses["security-reference"].message
    etf = state.action_statuses["etf"].message
    return f"Reference: {security_ref} | ETF: {etf}"


def _combined_reference_progress(state: PortfolioPageState) -> str:
    return f"Reference: {state.action_statuses['security-reference'].progress_summary} | ETF: {state.action_statuses['etf'].progress_summary}"


def _combined_reference_output(state: PortfolioPageState) -> str:
    reference_output = state.action_statuses["security-reference"].last_output_path
    etf_output = state.action_statuses["etf"].last_output_path
    if reference_output != "n/a":
        return reference_output
    return etf_output
