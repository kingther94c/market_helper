from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from market_helper.common.models import SecurityReferenceTable
from market_helper.reporting.risk_html import (
    CategorySummaryRow,
    PortfolioRiskSummary,
    RegimeReportSummary,
    RiskInputRow,
    RiskMetricsRow,
    build_allocation_summary,
    build_estimated_correlation,
    build_historical_correlation,
    estimated_asset_class_vol,
    historical_geomean_vol,
    load_position_rows,
    portfolio_volatility,
)


@dataclass(frozen=True)
class RiskReportBundle:
    rows: list[RiskInputRow]
    historical_correlation: dict[tuple[str, str], float]
    estimated_correlation: dict[tuple[str, str], float]
    historical_vols: dict[str, float]
    estimated_vols: dict[str, float]
    portfolio_summary: PortfolioRiskSummary
    allocation_summary: list[CategorySummaryRow]
    regime_summary: RegimeReportSummary | None = None
    risk_rows: list[RiskMetricsRow] | None = None
    proxy: dict[str, float] | None = None
    returns: dict[str, list[float]] | None = None


def load_risk_inputs(
    *,
    positions_csv_path: str | Path,
    security_reference_path: str | Path | None = None,
) -> list[RiskInputRow]:
    reference_table = (
        SecurityReferenceTable.from_csv(security_reference_path)
        if security_reference_path is not None
        else None
    )
    return load_position_rows(
        positions_csv_path,
        security_reference_table=reference_table,
    )


def summarize_asset_class_vol(
    asset_class: str,
    proxy: dict[str, float],
) -> float:
    return estimated_asset_class_vol(asset_class, proxy)


__all__ = [
    "CategorySummaryRow",
    "PortfolioRiskSummary",
    "RegimeReportSummary",
    "RiskInputRow",
    "RiskMetricsRow",
    "RiskReportBundle",
    "build_allocation_summary",
    "build_estimated_correlation",
    "build_historical_correlation",
    "estimated_asset_class_vol",
    "historical_geomean_vol",
    "load_risk_inputs",
    "load_position_rows",
    "portfolio_volatility",
]
