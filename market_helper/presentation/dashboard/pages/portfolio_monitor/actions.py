"""Form-to-inputs converters, action-status helpers, remediation, and job log.

The orchestration *bodies* (live/flex/combined/regime/...) live as closures in
:mod:`page` (they capture the page's ``render.refresh`` + service singletons).
This module holds the stateless, reusable pieces those closures call: pure
form-string -> ``*Inputs`` converters, the per-action status mutators, warning
remediation classification, and the completion toast + job-history recorder.
"""
from __future__ import annotations

import logging
from datetime import datetime

from nicegui import ui

from market_helper.application.portfolio_monitor import (
    BenchmarkRefreshInputs,
    EtfSectorSyncInputs,
    FlexPerformanceRefreshInputs,
    GenerateCombinedReportInputs,
    LivePortfolioRefreshInputs,
    PortfolioReportInputs,
    RegimeReportRefreshInputs,
    RegimeReportRunInputs,
)
from market_helper.presentation.dashboard.pages.portfolio_monitor.state import (
    ActionStatusState,
    FlexActionFormState,
    JobHistoryEntry,
    LiveActionFormState,
    PortfolioArtifactFormState,
    PortfolioPageState,
    ReferenceActionFormState,
    RegimeActionFormState,
    _JOB_HISTORY_MAX_ENTRIES,
    _optional_text,
    _parse_float,
    _parse_int,
    _required_text,
    _summarize_progress,
)

# ----- warning remediation --------------------------------------------------

_REMEDIATION_HINTS: tuple[tuple[str, str, str], ...] = (
    # (warning prefix, action_name, button label)
    # All three are fixed by running the same Flex performance refresh that the
    # "Flex" action button triggers — the feather + dated CSV are co-produced.
    ("Performance history file not found", "flex", "Run Flex Refresh"),
    ("Performance history file is empty", "flex", "Run Flex Refresh"),
    ("Dated performance report CSV is missing", "flex", "Run Flex Refresh"),
    # Yahoo benchmark cache (SPY/BIL) feeds the cash-Sharpe + benchmark traces
    # in the Performance section. Yahoo path is independent of Flex, so this
    # gets its own action handler that touches only the history feather.
    ("SPY/BIL benchmark return cache is missing", "yahoo", "Refresh Benchmark Cache"),
)


def _classify_warning(warning: str) -> tuple[str, str] | None:
    for prefix, action_name, button_label in _REMEDIATION_HINTS:
        if warning.startswith(prefix):
            return action_name, button_label
    return None


# ----- form string -> typed `*Inputs` ---------------------------------------


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


def _regime_run_inputs_from_form(form: RegimeActionFormState) -> RegimeReportRunInputs:
    return RegimeReportRunInputs(
        output_regime_path=_required_text(form.output_regime_path, "Regime JSON output path"),
        output_html_path=_required_text(form.output_html_path, "Regime HTML output path"),
        latest_only=bool(form.latest_only),
    )


def _regime_refresh_inputs_from_form(form: RegimeActionFormState) -> RegimeReportRefreshInputs:
    return RegimeReportRefreshInputs(
        output_regime_path=_required_text(form.output_regime_path, "Regime JSON output path"),
        output_html_path=_required_text(form.output_html_path, "Regime HTML output path"),
        latest_only=bool(form.latest_only),
        max_age_days=_parse_int(form.max_age_days, "Regime max age days"),
        force_refresh=bool(form.force_refresh),
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


def _benchmark_inputs_from_form(state: PortfolioPageState) -> BenchmarkRefreshInputs:
    return BenchmarkRefreshInputs(
        performance_history_path=_required_text(
            state.artifact_form.performance_history_path,
            "Performance history path",
        ),
    )


# ----- per-action status mutators + summaries -------------------------------


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


def _regime_progress_summary(state: PortfolioPageState) -> str:
    if state.active_job in {"regime-run", "regime-refresh"} and state.progress_sink.events:
        return _summarize_progress(state)
    run_status = state.action_statuses["regime-run"]
    refresh_status = state.action_statuses["regime-refresh"]
    if refresh_status.status != "idle":
        return refresh_status.progress_summary
    return run_status.progress_summary


def _merged_action_status(state: PortfolioPageState, primary: str, secondary: str) -> ActionStatusState:
    primary_status = state.action_statuses[primary]
    secondary_status = state.action_statuses[secondary]
    if state.active_job == secondary or secondary_status.status != "idle":
        return secondary_status
    return primary_status


# ----- P8: progress fraction + completion toast + job history ---------------


def _progress_fraction(state: PortfolioPageState) -> float | None:
    """Return the latest measurable progress fraction in [0,1], or None for indeterminate."""
    if not state.progress_sink.events:
        return None
    for event in reversed(state.progress_sink.events):
        if event.total and event.total > 0:
            value = event.completed if event.completed is not None else event.current
            if value is None:
                continue
            try:
                return max(0.0, min(1.0, float(value) / float(event.total)))
            except (TypeError, ValueError):
                continue
    return None


def _record_job_completion(state: PortfolioPageState, action_name: str) -> None:
    """Append a `JobHistoryEntry` for `action_name` based on the latest action status."""
    status = state.action_statuses.get(action_name)
    if status is None:
        return
    started_at = state.active_job_started_at or datetime.now()
    finished_at = datetime.now()
    duration = max(0.0, (finished_at - started_at).total_seconds())
    entry = JobHistoryEntry(
        action_name=action_name,
        started_at=started_at,
        finished_at=finished_at,
        status=status.status,
        message=status.message,
        output_path=status.last_output_path,
        duration_seconds=duration,
    )
    state.job_history.append(entry)
    if len(state.job_history) > _JOB_HISTORY_MAX_ENTRIES:
        del state.job_history[: -_JOB_HISTORY_MAX_ENTRIES]


def _push_completion_toast(state: PortfolioPageState, action_name: str) -> None:
    """Surface a Quasar toast on success/error so a finished background job is visible."""
    status = state.action_statuses.get(action_name)
    if status is None or status.status not in {"success", "error"}:
        return
    duration = ""
    if state.active_job_started_at is not None:
        elapsed = (datetime.now() - state.active_job_started_at).total_seconds()
        duration = f" ({elapsed:.1f}s)"
    toast_type = "positive" if status.status == "success" else "negative"
    pretty = _ACTION_PRETTY_NAMES.get(action_name, action_name.replace("-", " ").title())
    try:
        ui.notify(
            f"{pretty}: {status.message}{duration}",
            type=toast_type,
            position="top-right",
            timeout=6000 if status.status == "success" else 0,  # error toasts persist
            close_button="Dismiss",
        )
    except Exception as exc:  # noqa: BLE001 — toast failure must not bubble back into the action handler
        logging.getLogger(__name__).debug("ui.notify failed: %s", exc)


_ACTION_PRETTY_NAMES: dict[str, str] = {
    "refresh": "Refresh pipeline",
    "live": "Live refresh",
    "flex": "Flex refresh",
    "combined": "HTML report",
    "regime-run": "Regime report",
    "regime-refresh": "Regime refresh",
    "security-reference": "Security reference sync",
    "etf": "ETF sector sync",
    "yahoo": "Benchmark cache refresh",
}
