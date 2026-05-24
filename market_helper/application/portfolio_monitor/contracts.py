from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

from market_helper.domain.regime_detection.services.regime_report_provider import (
    RegimeArtifactState,
    RegimeMode,
)
from market_helper.reporting.performance_html import PerformanceReportViewModel
from market_helper.reporting.risk_html import RiskReportViewModel


@dataclass
class PortfolioReportInputs:
    positions_csv_path: str | Path | None = None
    performance_output_dir: str | Path | None = None
    performance_history_path: str | Path | None = None
    performance_report_csv_path: str | Path | None = None
    returns_path: str | Path | None = None
    proxy_path: str | Path | None = None
    regime_path: str | Path | None = None
    security_reference_path: str | Path | None = None
    risk_config_path: str | Path | None = None
    allocation_policy_path: str | Path | None = None
    vol_method: str = "geomean_1m_3m"
    inter_asset_corr: str = "historical"
    # Combined-report regime orchestration: the report pipeline asks the
    # regime provider for data in this mode. Default refresh-if-stale keeps
    # cron + dashboard "always fresh" without per-call configuration.
    regime_mode: RegimeMode = "refresh-if-stale"


@dataclass(frozen=True)
class ArtifactMetadata:
    positions_csv_path: Path
    performance_output_dir: Path | None
    performance_history_path: Path | None
    performance_report_csv_path: Path | None
    returns_path: Path | None
    proxy_path: Path | None
    regime_path: Path | None
    security_reference_path: Path | None
    risk_config_path: Path | None
    allocation_policy_path: Path | None
    positions_as_of: str | None


@dataclass(frozen=True)
class GeneratedReportArtifact:
    report_type: str
    title: str
    output_path: Path
    as_of: str
    mirrored_output_path: Path | None = None
    warnings: list[str] = field(default_factory=list)
    exists: bool = False


def _empty_regime_state() -> RegimeArtifactState:
    """Construct a missing-state sentinel for tests / callers that build report
    data directly without going through the provider."""
    return RegimeArtifactState(
        state="missing",
        mode_used="cached",
        view_model=None,
        regime_as_of=None,
        last_run_at=None,
        error_message="No regime artifact configured.",
    )


@dataclass(frozen=True)
class PortfolioReportData:
    as_of: str
    risk_view_model: RiskReportViewModel
    performance_usd_view_model: PerformanceReportViewModel
    performance_sgd_view_model: PerformanceReportViewModel
    artifact_metadata: ArtifactMetadata
    warnings: list[str] = field(default_factory=list)
    # Always present: the regime provider returns a tagged state (ok / stale /
    # missing / engine_error). The combined report always renders the section,
    # choosing the body presentation from this state — no Optional-fan-out.
    regime_state: RegimeArtifactState = field(default_factory=_empty_regime_state)
    as_of_freshness_note: str | None = None


@dataclass
class LivePortfolioRefreshInputs:
    output_path: str | Path
    host: str = "127.0.0.1"
    port: int = 7497
    client_id: int = 1
    account_id: str | None = None
    timeout: float = 4.0
    as_of: str | None = None


@dataclass
class FlexPerformanceRefreshInputs:
    output_dir: str | Path
    flex_xml_path: str | Path | None = None
    query_id: str | None = None
    token: str | None = None
    from_date: str | None = None
    to_date: str | None = None
    period: str | None = None
    xml_output_path: str | Path | None = None


@dataclass
class RegimeReportRunInputs:
    output_regime_path: str | Path | None = None
    output_html_path: str | Path | None = None
    latest_only: bool = False


@dataclass
class RegimeReportRefreshInputs(RegimeReportRunInputs):
    max_age_days: int = 7
    force_refresh: bool = False


@dataclass
class GenerateCombinedReportInputs(PortfolioReportInputs):
    output_path: str | Path | None = None


@dataclass
class EtfSectorSyncInputs:
    symbols: list[str]
    output_path: str | Path | None = None
    api_key: str | None = None


@dataclass
class BenchmarkRefreshInputs:
    performance_history_path: str | Path
    force_refresh: bool = False


@dataclass(frozen=True)
class UiProgressEvent:
    kind: str
    label: str
    detail: str | None = None
    current: int | None = None
    total: int | None = None
    completed: int | None = None
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class UiProgressSink(Protocol):
    def record(self, event: UiProgressEvent) -> None: ...
