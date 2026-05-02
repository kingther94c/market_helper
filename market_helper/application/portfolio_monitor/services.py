from __future__ import annotations

import csv
import datetime
import logging
from dataclasses import dataclass, field, replace
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

from market_helper.app.paths import PORTFOLIO_ARTIFACTS_DIR
from market_helper.application.portfolio_monitor.contracts import (
    ArtifactMetadata,
    EtfSectorSyncInputs,
    FlexPerformanceRefreshInputs,
    GenerateCombinedReportInputs,
    GeneratedReportArtifact,
    LivePortfolioRefreshInputs,
    PortfolioReportData,
    PortfolioReportInputs,
    UiProgressEvent,
    UiProgressSink,
)
from market_helper.application.portfolio_monitor.progress import UiProgressReporterAdapter
from market_helper.common.models.security_reference import DEFAULT_SECURITY_REFERENCE_PATH
from market_helper.reporting.performance_html import (
    build_performance_chart_specs,
    build_performance_report_view_model,
    load_nav_cashflow_history_frame,
)
from market_helper.reporting.regime_html import (
    RegimeHtmlViewModel,
    build_regime_html_view_model,
)
from market_helper.reporting.risk_html import DEFAULT_RISK_REPORT_CONFIG_PATH, build_risk_report_view_model
from market_helper.workflows import generate_report as report_workflows


DEFAULT_POSITIONS_CSV_PATH = PORTFOLIO_ARTIFACTS_DIR / "live_ibkr_position_report.csv"
DEFAULT_COMBINED_REPORT_PATH = PORTFOLIO_ARTIFACTS_DIR / "portfolio_combined_report.html"
DEFAULT_PERFORMANCE_OUTPUT_DIR = PORTFOLIO_ARTIFACTS_DIR / "flex"


@dataclass
class _PerformanceCacheEntry:
    """In-process daily cache for the performance view models.

    Invalidated when the calendar date changes, when the history or CSV
    path changes, or when the underlying feather file is modified on disk.
    """
    date: datetime.date
    history_path: Path | None
    report_csv_path: Path | None
    history_mtime: float | None  # None when file doesn't exist
    usd_view_model: object  # PerformanceReportViewModel
    sgd_view_model: object  # PerformanceReportViewModel
    perf_warnings: list[str] = field(default_factory=list)

    def is_valid_for(
        self,
        *,
        history_path: Path | None,
        report_csv_path: Path | None,
    ) -> bool:
        if self.date != datetime.date.today():
            return False
        if self.history_path != history_path or self.report_csv_path != report_csv_path:
            return False
        # Invalidate if the feather file has been updated on disk.
        current_mtime = _file_mtime(history_path)
        if current_mtime != self.history_mtime:
            return False
        return True


def _file_mtime(path: Path | None) -> float | None:
    if path is None or not path.exists():
        return None
    return path.stat().st_mtime


def _resolve_performance_report_csv_path(
    *,
    performance_report_csv_path: str | Path | None,
    performance_output_dir: str | Path | None,
) -> Path | None:
    if performance_report_csv_path is not None:
        return Path(performance_report_csv_path)
    if performance_output_dir is None:
        return None
    candidates = sorted(Path(performance_output_dir).glob("performance_report_*.csv"))
    if not candidates:
        return None
    return candidates[-1]


class PortfolioMonitorQueryService:
    def __init__(self) -> None:
        self._perf_cache: _PerformanceCacheEntry | None = None

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
            inter_asset_corr=source.inter_asset_corr,
        )

    def load_report_data(self, inputs: PortfolioReportInputs | None = None) -> PortfolioReportData:
        resolved = self.resolve_inputs(inputs)
        return self._assemble_report_data(resolved)

    def _assemble_report_data(self, resolved: PortfolioReportInputs) -> PortfolioReportData:
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
        perf_entry = self._load_perf_cached(
            performance_history_path=performance_history_path,
            performance_report_csv_path=performance_report_csv_path,
        )
        warnings.extend(perf_entry.perf_warnings)
        risk_view_model = build_risk_report_view_model(
            positions_csv_path=positions_path,
            returns_path=resolved.returns_path,
            proxy_path=resolved.proxy_path,
            regime_path=resolved.regime_path,
            security_reference_path=resolved.security_reference_path,
            risk_config_path=resolved.risk_config_path,
            allocation_policy_path=resolved.allocation_policy_path,
            vol_method=resolved.vol_method,
            inter_asset_corr=resolved.inter_asset_corr,
        )
        regime_view_model = self._load_regime_view_model(
            regime_path=resolved.regime_path,
            policy_path=resolved.allocation_policy_path,
            warnings=warnings,
        )
        performance_usd_view_model = perf_entry.usd_view_model
        performance_sgd_view_model = perf_entry.sgd_view_model
        positions_as_of = _read_positions_as_of(positions_path)
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
        report_as_of = _resolve_report_as_of(
            positions_as_of=positions_as_of,
            performance_as_of=performance_usd_view_model.as_of,
            risk_as_of=risk_view_model.as_of,
        )
        return PortfolioReportData(
            as_of=report_as_of,
            risk_view_model=replace(risk_view_model, as_of=report_as_of),
            performance_usd_view_model=performance_usd_view_model,
            performance_sgd_view_model=performance_sgd_view_model,
            artifact_metadata=metadata,
            warnings=warnings,
            regime_view_model=regime_view_model,
        )

    @staticmethod
    def _load_regime_view_model(
        *,
        regime_path: str | Path | None,
        policy_path: str | Path | None,
        warnings: list[str],
    ) -> RegimeHtmlViewModel | None:
        """Best-effort regime view-model load — failures degrade to a warning."""
        if regime_path is None:
            return None
        path = Path(str(regime_path))
        if not path.exists():
            warnings.append(f"Regime artifact not found at {path}; regime section will be omitted.")
            return None
        try:
            return build_regime_html_view_model(
                regime_path=path,
                policy_path=policy_path,
            )
        except Exception as exc:  # noqa: BLE001 — swallow into a warning to keep the report alive
            logger.warning("Failed to build regime view-model from %s: %s", path, exc)
            warnings.append(f"Regime artifact at {path} could not be parsed ({exc}); regime section will be omitted.")
            return None

    def resolve_report_artifact(
        self,
        *,
        inputs: PortfolioReportInputs | None = None,
        output_path: str | Path | None = None,
        report_data: PortfolioReportData | None = None,
        as_of: str = "n/a",
        mirrored_output_path: Path | None = None,
        warnings: list[str] | None = None,
    ) -> GeneratedReportArtifact:
        resolved = self.resolve_inputs(inputs)
        target_path = Path(output_path) if output_path is not None else DEFAULT_COMBINED_REPORT_PATH
        if report_data is not None:
            as_of = report_data.as_of
            warnings = report_data.warnings
        return GeneratedReportArtifact(
            report_type="portfolio_monitor",
            title="Portfolio Monitor HTML Report",
            output_path=target_path,
            as_of=as_of,
            mirrored_output_path=mirrored_output_path,
            warnings=list(warnings or []),
            exists=target_path.exists(),
        )

    def _load_perf_cached(
        self,
        *,
        performance_history_path: Path | None,
        performance_report_csv_path: Path | None,
    ) -> _PerformanceCacheEntry:
        """Return a performance cache entry, rebuilding at most once per calendar day.

        Invalidation triggers:
        - Calendar date change.
        - Path inputs differ from cached entry.
        - The feather history file has been modified on disk (mtime changed).
        """
        if (
            self._perf_cache is not None
            and self._perf_cache.is_valid_for(
                history_path=performance_history_path,
                report_csv_path=performance_report_csv_path,
            )
        ):
            logger.debug("Performance cache hit (date=%s)", self._perf_cache.date)
            return self._perf_cache

        logger.debug(
            "Performance cache miss — rebuilding (date=%s, history=%s)",
            datetime.date.today(),
            performance_history_path,
        )
        perf_warnings: list[str] = []
        history = self._load_history_frame(performance_history_path, warnings=perf_warnings)
        if performance_report_csv_path is None or not performance_report_csv_path.exists():
            perf_warnings.append(
                "Dated performance report CSV is missing; only history-derived metrics are available."
            )
        usd_vm = replace(
            build_performance_report_view_model(
                history,
                report_csv_path=performance_report_csv_path,
                primary_currency="USD",
                secondary_currency=None,
                primary_basis="TWR",
            ),
            chart_specs=build_performance_chart_specs(history, "USD"),
        )
        sgd_vm = replace(
            build_performance_report_view_model(
                history,
                report_csv_path=performance_report_csv_path,
                primary_currency="SGD",
                secondary_currency=None,
                primary_basis="TWR",
            ),
            chart_specs=build_performance_chart_specs(history, "SGD"),
        )
        self._perf_cache = _PerformanceCacheEntry(
            date=datetime.date.today(),
            history_path=performance_history_path,
            report_csv_path=performance_report_csv_path,
            history_mtime=_file_mtime(performance_history_path),
            usd_view_model=usd_vm,
            sgd_view_model=sgd_vm,
            perf_warnings=perf_warnings,
        )
        return self._perf_cache

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
    def __init__(self, *, query_service: PortfolioMonitorQueryService | None = None) -> None:
        self._query_service = query_service or PortfolioMonitorQueryService()

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
    ) -> GeneratedReportArtifact:
        resolved = self._query_service.resolve_inputs(inputs)
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
            inter_asset_corr=resolved.inter_asset_corr,
        )
        mirrored = report_workflows.ensure_google_drive_artifact_mirror(
            source_path=written,
            target_name="portfolio_combined_report.html",
            config_path=Path(str(resolved.risk_config_path)) if resolved.risk_config_path is not None else None,
        )
        _record_manual_event(sink, kind="done", label="Combined HTML", detail=f"wrote {written}")
        report_data = self._query_service.load_report_data(resolved)
        return self._query_service.resolve_report_artifact(
            inputs=resolved,
            output_path=written,
            report_data=report_data,
            mirrored_output_path=mirrored,
        )

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


def _resolve_report_as_of(*, positions_as_of: str | None, performance_as_of: str, risk_as_of: str) -> str:
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
