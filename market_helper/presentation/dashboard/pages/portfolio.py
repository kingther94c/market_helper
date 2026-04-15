from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
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
from market_helper.reporting.risk_html import BreakdownRow, PolicyDriftRow, RiskMetricsRow


_REGISTERED = False
_QUERY_SERVICE: PortfolioMonitorQueryService = PortfolioMonitorQueryService()
_ACTION_SERVICE: PortfolioMonitorActionService = PortfolioMonitorActionService()


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
    snapshot: PortfolioReportSnapshot | None = None
    warnings: list[str] = field(default_factory=list)
    is_loading: bool = False
    load_error: str | None = None
    active_job: str | None = None
    status_message: str = "Ready"
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
    async def portfolio_page() -> None:
        state = _build_initial_state(_QUERY_SERVICE)

        @ui.refreshable
        def render() -> None:
            _render_portfolio_page(state)

        async def load_snapshot() -> None:
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
                ui.notify(state.status_message, type="positive")
                await load_snapshot()
            except Exception as exc:
                _set_action_error(state, action_name, str(exc))
                state.status_message = f"Action failed: {exc}"
                ui.notify(state.status_message, type="negative")
                render.refresh()
            finally:
                state.active_job = None
                render.refresh()

        state._load_snapshot = load_snapshot  # type: ignore[attr-defined]
        state._run_action = run_action  # type: ignore[attr-defined]
        state._refresh_ui = render.refresh  # type: ignore[attr-defined]
        render()
        ui.timer(0.1, lambda: asyncio.create_task(load_snapshot()), once=True)

    _REGISTERED = True


def _build_initial_state(query_service: PortfolioMonitorQueryService) -> PortfolioPageState:
    inputs = query_service.resolve_inputs()
    positions_path = str(inputs.positions_csv_path or "")
    performance_output_dir = str(inputs.performance_output_dir or "")
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
            vol_method=inputs.vol_method,
            inter_asset_corr=inputs.inter_asset_corr,
        ),
        live_form=LiveActionFormState(output_path=positions_path),
        flex_form=FlexActionFormState(output_dir=performance_output_dir),
        export_form=ExportActionFormState(output_path=str(Path(performance_output_dir).parent / "portfolio_combined_report.html")),
        reference_form=ReferenceActionFormState(security_reference_output_path=str(inputs.security_reference_path or "")),
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
                options=["geomean_1m_3m", "5y_realized", "ewma", "forward_looking"],
                label="Risk vol method",
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
    tabs = ui.tabs().classes("w-full")
    with tabs:
        tab_perf_usd = ui.tab("Performance USD")
        tab_perf_sgd = ui.tab("Performance SGD")
        tab_risk = ui.tab("Risk")
        tab_artifacts = ui.tab("Artifacts")
    with ui.tab_panels(tabs, value=tab_perf_usd).classes("w-full"):
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


def _render_risk_panel(snapshot: PortfolioReportSnapshot) -> None:
    risk = snapshot.risk_view_model
    with ui.column().classes("w-full gap-4"):
        with ui.card().classes("w-full pm-card p-4"):
            ui.label("Portfolio Summary").classes("text-h6")
            with ui.row().classes("w-full gap-4 wrap"):
                for label, value in [
                    ("Vol 1M/3M", format_percent(risk.summary.portfolio_vol_geomean_1m_3m)),
                    ("Vol 5Y", format_percent(risk.summary.portfolio_vol_5y_realized)),
                    ("Vol EWMA", format_percent(risk.summary.portfolio_vol_ewma)),
                    ("Funded AUM USD", format_amount(risk.summary.funded_aum_usd, decimals=0)),
                    ("Funded AUM SGD", format_amount(risk.summary.funded_aum_sgd, decimals=0)),
                    ("Gross Exposure", format_amount(risk.summary.gross_exposure, decimals=0)),
                    ("Net Exposure", format_amount(risk.summary.net_exposure, decimals=0)),
                    ("Mapping Coverage", f"{risk.summary.mapped_positions}/{risk.summary.total_positions}"),
                ]:
                    render_status_card(title=label, value=value)
        with ui.row().classes("w-full gap-4 wrap"):
            with ui.card().classes("grow basis-[520px] pm-card p-4"):
                ui.label("Asset Class Summary").classes("text-h6")
                render_table(
                    columns=[
                        {"name": "asset_class", "label": "Asset Class", "field": "asset_class"},
                        {"name": "exposure_usd", "label": "Net Exposure", "field": "exposure_usd"},
                        {"name": "gross_exposure_usd", "label": "Gross Exposure", "field": "gross_exposure_usd"},
                        {"name": "dollar_weight", "label": "Dollar%", "field": "dollar_weight"},
                        {"name": "risk_contribution_estimated", "label": "Vol Contribution", "field": "risk_contribution_estimated"},
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
            render_risk_chart_block(
                title="Policy Drift - Asset Class",
                figure=build_policy_drift_figure(risk.policy_drift_asset_class),
                columns=[
                    {"name": "bucket", "label": "Bucket", "field": "bucket"},
                    {"name": "scope", "label": "Scope", "field": "scope"},
                    {"name": "current_weight", "label": "Current", "field": "current_weight"},
                    {"name": "policy_weight", "label": "Policy", "field": "policy_weight"},
                    {"name": "active_weight", "label": "Active", "field": "active_weight"},
                    {"name": "current_risk_contribution", "label": "Vol Contribution", "field": "current_risk_contribution"},
                ],
                rows=[_policy_drift_row_to_table_row(row) for row in risk.policy_drift_asset_class],
                row_key="bucket",
            )
        with ui.row().classes("w-full gap-4 wrap"):
            render_risk_chart_block(
                title="EQ Country Breakdown",
                figure=build_breakdown_figure(risk.country_breakdown, title="EQ Country Breakdown"),
                columns=_breakdown_columns(),
                rows=[_breakdown_row_to_table_row(row) for row in risk.country_breakdown],
                row_key="bucket",
            )
            render_risk_chart_block(
                title="US Sector Breakdown",
                figure=build_breakdown_figure(risk.sector_breakdown, title="US Sector Breakdown"),
                columns=_breakdown_columns(),
                rows=[_breakdown_row_to_table_row(row) for row in risk.sector_breakdown],
                row_key="bucket",
            )
        with ui.card().classes("w-full pm-card p-4"):
            ui.label("Position Risk Decomposition").classes("text-h6")
            render_table(
                columns=[
                    {"name": "account", "label": "Account", "field": "account"},
                    {"name": "display_ticker", "label": "Ticker", "field": "display_ticker"},
                    {"name": "display_name", "label": "Name", "field": "display_name"},
                    {"name": "asset_class", "label": "Asset Class", "field": "asset_class"},
                    {"name": "instrument_type", "label": "Type", "field": "instrument_type"},
                    {"name": "gross_exposure_usd", "label": "Gross Exposure", "field": "gross_exposure_usd"},
                    {"name": "exposure_usd", "label": "Net Exposure", "field": "exposure_usd"},
                    {"name": "dollar_weight", "label": "Dollar%", "field": "dollar_weight"},
                    {"name": "vol_geomean_1m_3m", "label": "Vol 1M/3M", "field": "vol_geomean_1m_3m"},
                    {"name": "vol_5y_realized", "label": "Vol 5Y", "field": "vol_5y_realized"},
                    {"name": "vol_ewma", "label": "Vol EWMA", "field": "vol_ewma"},
                    {"name": "risk_contribution_estimated", "label": "Vol Contribution", "field": "risk_contribution_estimated"},
                    {"name": "mapping_status", "label": "Mapping", "field": "mapping_status"},
                    {"name": "report_scope", "label": "Scope", "field": "report_scope"},
                ],
                rows=[_risk_row_to_table_row(row) for row in risk.risk_rows],
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
                    progress_summary=state.action_statuses["live"].progress_summary,
                    last_output_path=state.action_statuses["live"].last_output_path,
                    body=lambda: _render_live_action_body(state, run_action),
                )
                render_action_card(
                    title="Flex Performance",
                    subtitle="Rebuild flex-based performance artifacts from local XML or live Flex credentials.",
                    status=state.action_statuses["flex"].status,
                    message=state.action_statuses["flex"].message,
                    progress_summary=state.action_statuses["flex"].progress_summary,
                    last_output_path=state.action_statuses["flex"].last_output_path,
                    body=lambda: _render_flex_action_body(state, run_action),
                )
                render_action_card(
                    title="Static Export",
                    subtitle="Regenerate the compatibility combined HTML report from the current artifact form.",
                    status=state.action_statuses["combined"].status,
                    message=state.action_statuses["combined"].message,
                    progress_summary=state.action_statuses["combined"].progress_summary,
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


def _policy_drift_row_to_table_row(row: PolicyDriftRow) -> dict[str, str]:
    return {
        "bucket": row.bucket,
        "scope": row.scope,
        "current_weight": format_percent(row.current_weight),
        "policy_weight": format_percent(row.policy_weight),
        "active_weight": format_percent(row.active_weight),
        "current_risk_contribution": format_percent(row.current_risk_contribution),
    }


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


def _with_plotly_config(figure_spec: dict[str, Any]) -> dict[str, Any]:
    output = dict(figure_spec)
    output.setdefault("config", {"displayModeBar": False, "responsive": True})
    return output


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
        return f"{event.completed}/{event.total}"
    if event.current is not None and event.total is not None:
        return f"{event.current}/{event.total}"
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
