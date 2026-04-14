from __future__ import annotations

import csv
from dataclasses import replace
from pathlib import Path

import pandas as pd

from market_helper.app.paths import PORTFOLIO_ARTIFACTS_DIR
from market_helper.application.portfolio_monitor.contracts import (
    ArtifactMetadata,
    EtfSectorSyncInputs,
    FlexPerformanceRefreshInputs,
    GenerateCombinedReportInputs,
    LivePortfolioRefreshInputs,
    PortfolioReportInputs,
    PortfolioReportSnapshot,
    UiProgressEvent,
    UiProgressSink,
)
from market_helper.application.portfolio_monitor.progress import UiProgressReporterAdapter
from market_helper.common.models.security_reference import DEFAULT_SECURITY_REFERENCE_PATH
from market_helper.reporting.combined_html import _resolve_performance_report_csv_path
from market_helper.reporting.performance_html import (
    build_performance_chart_specs,
    build_performance_report_view_model,
    load_nav_cashflow_history_frame,
)
from market_helper.reporting.risk_html import DEFAULT_RISK_REPORT_CONFIG_PATH, build_risk_report_view_model
from market_helper.workflows import generate_report as report_workflows


DEFAULT_POSITIONS_CSV_PATH = PORTFOLIO_ARTIFACTS_DIR / "live_ibkr_position_report.csv"
DEFAULT_COMBINED_REPORT_PATH = PORTFOLIO_ARTIFACTS_DIR / "portfolio_combined_report.html"
DEFAULT_PERFORMANCE_OUTPUT_DIR = PORTFOLIO_ARTIFACTS_DIR / "flex"


class PortfolioMonitorQueryService:
    def resolve_inputs(self, inputs: PortfolioReportInputs | None = None) -> PortfolioReportInputs:
        source = inputs or PortfolioReportInputs()
        output_dir = Path(source.performance_output_dir) if source.performance_output_dir is not None else DEFAULT_PERFORMANCE_OUTPUT_DIR
        positions_csv_path = (
            Path(source.positions_csv_path)
            if source.positions_csv_path is not None
            else DEFAULT_POSITIONS_CSV_PATH
        )
        security_reference_path = (
            Path(source.security_reference_path)
            if source.security_reference_path is not None
            else DEFAULT_SECURITY_REFERENCE_PATH
        )
        risk_config_path = (
            Path(source.risk_config_path)
            if source.risk_config_path is not None
            else DEFAULT_RISK_REPORT_CONFIG_PATH
        )
        return PortfolioReportInputs(
            positions_csv_path=positions_csv_path,
            performance_output_dir=output_dir,
            performance_history_path=(
                Path(source.performance_history_path)
                if source.performance_history_path is not None
                else output_dir / "nav_cashflow_history.feather"
            ),
            performance_report_csv_path=(
                Path(source.performance_report_csv_path)
                if source.performance_report_csv_path is not None
                else _resolve_performance_report_csv_path(
                    performance_report_csv_path=None,
                    performance_output_dir=output_dir,
                )
            ),
            returns_path=Path(source.returns_path) if source.returns_path is not None else None,
            proxy_path=Path(source.proxy_path) if source.proxy_path is not None else None,
            regime_path=Path(source.regime_path) if source.regime_path is not None else None,
            security_reference_path=security_reference_path,
            risk_config_path=risk_config_path,
            allocation_policy_path=Path(source.allocation_policy_path) if source.allocation_policy_path is not None else None,
            vol_method=source.vol_method,
        )

    def load_snapshot(self, inputs: PortfolioReportInputs | None = None) -> PortfolioReportSnapshot:
        resolved = self.resolve_inputs(inputs)
        positions_path = Path(str(resolved.positions_csv_path))
        if not positions_path.exists():
            raise FileNotFoundError(f"Position CSV not found: {positions_path}")

        warnings: list[str] = []
        performance_history_path = Path(str(resolved.performance_history_path)) if resolved.performance_history_path is not None else None
        performance_report_csv_path = (
            Path(str(resolved.performance_report_csv_path))
            if resolved.performance_report_csv_path is not None
            else None
        )
        history = self._load_history_frame(performance_history_path, warnings=warnings)
        risk_view_model = build_risk_report_view_model(
            positions_csv_path=positions_path,
            returns_path=resolved.returns_path,
            proxy_path=resolved.proxy_path,
            regime_path=resolved.regime_path,
            security_reference_path=resolved.security_reference_path,
            risk_config_path=resolved.risk_config_path,
            allocation_policy_path=resolved.allocation_policy_path,
            vol_method=resolved.vol_method,
        )
        performance_usd_view_model = build_performance_report_view_model(
            history,
            report_csv_path=performance_report_csv_path,
            primary_currency="USD",
            secondary_currency=None,
            primary_basis="TWR",
        )
        performance_sgd_view_model = build_performance_report_view_model(
            history,
            report_csv_path=performance_report_csv_path,
            primary_currency="SGD",
            secondary_currency=None,
            primary_basis="TWR",
        )
        positions_as_of = _read_positions_as_of(positions_path)
        if history.empty:
            warnings.append("Performance history artifact is missing or empty; performance cards and charts show placeholders.")
        if performance_report_csv_path is None or not performance_report_csv_path.exists():
            warnings.append("Dated performance report CSV is missing; only history-derived metrics are available.")
        metadata = ArtifactMetadata(
            positions_csv_path=positions_path,
            performance_output_dir=Path(str(resolved.performance_output_dir)) if resolved.performance_output_dir is not None else None,
            performance_history_path=performance_history_path,
            performance_report_csv_path=performance_report_csv_path,
            returns_path=Path(str(resolved.returns_path)) if resolved.returns_path is not None else None,
            proxy_path=Path(str(resolved.proxy_path)) if resolved.proxy_path is not None else None,
            regime_path=Path(str(resolved.regime_path)) if resolved.regime_path is not None else None,
            security_reference_path=Path(str(resolved.security_reference_path)) if resolved.security_reference_path is not None else None,
            risk_config_path=Path(str(resolved.risk_config_path)) if resolved.risk_config_path is not None else None,
            allocation_policy_path=Path(str(resolved.allocation_policy_path)) if resolved.allocation_policy_path is not None else None,
            positions_as_of=positions_as_of,
        )
        return PortfolioReportSnapshot(
            as_of=_resolve_snapshot_as_of(
                positions_as_of=positions_as_of,
                performance_as_of=performance_usd_view_model.as_of,
                risk_as_of=risk_view_model.as_of,
            ),
            risk_view_model=replace(risk_view_model, as_of=_resolve_snapshot_as_of(
                positions_as_of=positions_as_of,
                performance_as_of=performance_usd_view_model.as_of,
                risk_as_of=risk_view_model.as_of,
            )),
            performance_usd_view_model=replace(
                performance_usd_view_model,
                chart_specs=build_performance_chart_specs(history, "USD"),
            ),
            performance_sgd_view_model=replace(
                performance_sgd_view_model,
                chart_specs=build_performance_chart_specs(history, "SGD"),
            ),
            artifact_metadata=metadata,
            warnings=warnings,
        )

    def _load_history_frame(self, path: Path | None, *, warnings: list[str]) -> pd.DataFrame:
        if path is None:
            warnings.append("Performance history path is not configured.")
            return _empty_nav_cashflow_history_frame()
        if not path.exists():
            warnings.append(f"Performance history file not found: {path}")
            return _empty_nav_cashflow_history_frame()
        loaded = load_nav_cashflow_history_frame(path)
        if loaded.empty:
            warnings.append(f"Performance history file is empty: {path}")
        return loaded


class PortfolioMonitorActionService:
    def refresh_live_positions(
        self,
        inputs: LivePortfolioRefreshInputs,
        *,
        sink: UiProgressSink | None = None,
    ) -> Path:
        reporter = UiProgressReporterAdapter(sink)
        return report_workflows.generate_live_ibkr_position_report(
            output_path=Path(inputs.output_path),
            host=inputs.host,
            port=inputs.port,
            client_id=inputs.client_id,
            account_id=inputs.account_id,
            timeout=inputs.timeout,
            as_of=inputs.as_of,
            progress=reporter,
        )

    def rebuild_flex_performance(
        self,
        inputs: FlexPerformanceRefreshInputs,
        *,
        sink: UiProgressSink | None = None,
    ) -> Path:
        reporter = UiProgressReporterAdapter(sink)
        return report_workflows.generate_ibkr_flex_performance_report(
            output_dir=Path(inputs.output_dir),
            flex_xml_path=Path(inputs.flex_xml_path) if inputs.flex_xml_path is not None else None,
            query_id=inputs.query_id,
            token=inputs.token,
            from_date=inputs.from_date,
            to_date=inputs.to_date,
            period=inputs.period,
            xml_output_path=Path(inputs.xml_output_path) if inputs.xml_output_path is not None else None,
            progress=reporter,
        )

    def generate_combined_report(
        self,
        inputs: GenerateCombinedReportInputs,
        *,
        sink: UiProgressSink | None = None,
    ) -> Path:
        resolved = PortfolioMonitorQueryService().resolve_inputs(inputs)
        output_path = Path(inputs.output_path) if inputs.output_path is not None else DEFAULT_COMBINED_REPORT_PATH
        _record_manual_event(sink, kind="spinner", label="Combined HTML", detail="rendering")
        written = report_workflows.generate_combined_html_report(
            positions_csv_path=Path(str(resolved.positions_csv_path)),
            output_path=output_path,
            performance_history_path=Path(str(resolved.performance_history_path)) if resolved.performance_history_path is not None else None,
            performance_output_dir=Path(str(resolved.performance_output_dir)) if resolved.performance_output_dir is not None else None,
            performance_report_csv_path=Path(str(resolved.performance_report_csv_path)) if resolved.performance_report_csv_path is not None else None,
            returns_path=Path(str(resolved.returns_path)) if resolved.returns_path is not None else None,
            proxy_path=Path(str(resolved.proxy_path)) if resolved.proxy_path is not None else None,
            regime_path=Path(str(resolved.regime_path)) if resolved.regime_path is not None else None,
            security_reference_path=Path(str(resolved.security_reference_path)) if resolved.security_reference_path is not None else None,
            risk_config_path=Path(str(resolved.risk_config_path)) if resolved.risk_config_path is not None else None,
            allocation_policy_path=Path(str(resolved.allocation_policy_path)) if resolved.allocation_policy_path is not None else None,
            vol_method=resolved.vol_method,
        )
        _record_manual_event(sink, kind="done", label="Combined HTML", detail=f"wrote {written}")
        return written

    def sync_security_reference(
        self,
        *,
        output_path: str | Path | None = None,
        sink: UiProgressSink | None = None,
    ) -> Path:
        _record_manual_event(sink, kind="spinner", label="Security reference", detail="syncing")
        written = report_workflows.generate_security_reference_sync(
            output_path=Path(output_path) if output_path is not None else None,
        )
        _record_manual_event(sink, kind="done", label="Security reference", detail=f"wrote {written}")
        return written

    def sync_etf_sector(
        self,
        inputs: EtfSectorSyncInputs,
        *,
        sink: UiProgressSink | None = None,
    ) -> Path:
        reporter = UiProgressReporterAdapter(sink)
        return report_workflows.generate_etf_sector_sync(
            symbols=inputs.symbols,
            output_path=Path(inputs.output_path) if inputs.output_path is not None else None,
            api_key=inputs.api_key,
            progress=reporter,
        )


def _empty_nav_cashflow_history_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": pd.Series(dtype="datetime64[ns]"),
            "nav_eod_usd": pd.Series(dtype=float),
            "nav_eod_sgd": pd.Series(dtype=float),
            "cashflow_usd": pd.Series(dtype=float),
            "cashflow_sgd": pd.Series(dtype=float),
            "fx_usdsgd_eod": pd.Series(dtype=float),
            "pnl_amt_usd": pd.Series(dtype=float),
            "pnl_amt_sgd": pd.Series(dtype=float),
            "pnl_usd": pd.Series(dtype=float),
            "pnl_sgd": pd.Series(dtype=float),
            "is_final": pd.Series(dtype=bool),
            "source_kind": pd.Series(dtype=str),
            "source_file": pd.Series(dtype=str),
            "source_as_of": pd.Series(dtype="datetime64[ns]"),
        }
    )


def _read_positions_as_of(path: Path) -> str | None:
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        first_row = next(reader, None)
    if first_row is None:
        return None
    raw_value = str(first_row.get("as_of") or "").strip()
    return raw_value or None


def _resolve_snapshot_as_of(*, positions_as_of: str | None, performance_as_of: str, risk_as_of: str) -> str:
    for candidate in (positions_as_of, performance_as_of, risk_as_of):
        normalized = (candidate or "").strip()
        if normalized and normalized.lower() != "n/a":
            return normalized
    return "n/a"


def _record_manual_event(
    sink: UiProgressSink | None,
    *,
    kind: str,
    label: str,
    detail: str | None = None,
) -> None:
    if sink is None:
        return
    sink.record(UiProgressEvent(kind=kind, label=label, detail=detail))
