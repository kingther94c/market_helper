from __future__ import annotations

from dataclasses import asdict
import html
from pathlib import Path
from typing import TYPE_CHECKING

from market_helper.common.datetime_display import format_local_datetime
from market_helper.reporting.html_tables import HtmlTableColumn, HtmlTableRow, render_html_table
from market_helper.reporting.performance_html import (
    PerformanceMetricRow,
    PerformanceReportViewModel,
    render_performance_assets,
    render_performance_tab,
)
from market_helper.reporting.report_document import ReportDocument, ReportSection, render_report_document
from market_helper.reporting.risk_html import (
    RiskReportViewModel,
    render_risk_report_script,
    render_risk_report_styles,
    render_risk_tab,
)

if TYPE_CHECKING:
    from market_helper.application.portfolio_monitor.contracts import (
        ArtifactMetadata,
        GeneratedReportArtifact,
        PortfolioReportData,
    )


def _format_pct(value: float | None, *, signed: bool = False, places: int = 2) -> str:
    if value is None:
        return "—"
    pct = float(value) * 100.0
    sign = "+" if signed and pct > 0 else ""
    return f"{sign}{pct:.{places}f}%"


def _format_money_usd(value: float | None) -> str:
    if value is None:
        return "—"
    return f"${value:,.0f}"


def _format_ratio(value: float | None, *, places: int = 2) -> str:
    if value is None:
        return "—"
    return f"{float(value):.{places}f}"


def _horizon_row(view_model: PerformanceReportViewModel | None, label: str) -> PerformanceMetricRow | None:
    if view_model is None:
        return None
    for row in view_model.horizon_rows:
        if row.label == label:
            return row
    return None


def _largest_drift_summary(rows) -> tuple[str, float] | None:
    """Return (bucket, drift_pct) for the row with the largest absolute active weight."""
    best: tuple[str, float] | None = None
    for row in rows:
        active = getattr(row, "active_weight", None)
        if active is None:
            continue
        if best is None or abs(active) > abs(best[1]):
            best = (str(getattr(row, "bucket", "")), float(active))
    return best


def _delta_class(value: float | None) -> str:
    if value is None:
        return ""
    if value > 0:
        return " tone-positive"
    if value < 0:
        return " tone-negative"
    return ""


def _kpi_cell(label: str, value_html: str, sub_html: str = "", *, value_class: str = "") -> str:
    return (
        "<div class='kpi'>"
        f"<span class='kpi__label'>{html.escape(label)}</span>"
        f"<span class='kpi__value{html.escape(value_class)}'>{value_html}</span>"
        f"<span class='kpi__sub'>{sub_html}</span>"
        "</div>"
    )


def build_topline_html(report_data: "PortfolioReportData") -> str:
    """Build the 8-cell KPI strip rendered above the section content (P4).

    Pulls from the existing performance + risk view-models — no new computation.
    Cells that can't be sourced from current view-models render as `—`.
    """
    perf = report_data.performance_usd_view_model
    risk = report_data.risk_view_model
    summary = risk.summary if risk is not None else None

    mtd = _horizon_row(perf, "MTD")
    ytd = _horizon_row(perf, "YTD")
    one_year = _horizon_row(perf, "1Y")

    nav = summary.funded_aum_usd if summary is not None else None
    nav_sub = ""
    if summary is not None and summary.funded_aum_sgd is not None:
        nav_sub = f"SGD {summary.funded_aum_sgd:,.0f}"

    drift_pair = _largest_drift_summary(risk.policy_drift_asset_class) if risk is not None else None
    if drift_pair is not None:
        drift_pct = drift_pair[1] * 100.0
        drift_sign = "+" if drift_pct > 0 else ("−" if drift_pct < 0 else "")
        drift_value = f"{drift_sign}{abs(drift_pct):.1f}pp {html.escape(drift_pair[0])}"
        drift_class = " is-warn" if abs(drift_pct) >= 2.0 else ""
    else:
        drift_value = "—"
        drift_class = ""

    cells = [
        _kpi_cell(
            "NAV (USD)",
            html.escape(_format_money_usd(nav)),
            html.escape(nav_sub),
        ),
        _kpi_cell(
            "MTD",
            html.escape(_format_pct(mtd.twr_return if mtd else None, signed=True)),
            value_class=_delta_class(mtd.twr_return if mtd else None),
        ),
        _kpi_cell(
            "YTD",
            html.escape(_format_pct(ytd.twr_return if ytd else None, signed=True)),
            value_class=_delta_class(ytd.twr_return if ytd else None),
        ),
        _kpi_cell(
            "1Y",
            html.escape(_format_pct(one_year.twr_return if one_year else None, signed=True)),
            value_class=_delta_class(one_year.twr_return if one_year else None),
        ),
        _kpi_cell(
            "Ann. Vol (1Y)",
            html.escape(_format_pct(one_year.annualized_vol if one_year else None)),
            "EWMA + 1m/3m blend",
        ),
        _kpi_cell(
            "Sharpe (1Y)",
            html.escape(_format_ratio(one_year.sharpe_ratio if one_year else None)),
        ),
        _kpi_cell(
            "Max DD (1Y)",
            html.escape(_format_pct(one_year.max_drawdown if one_year else None)),
            value_class=_delta_class(one_year.max_drawdown if one_year else None),
        ),
        _kpi_cell(
            "Policy drift",
            html.escape(drift_value),
            "vs target asset-class",
            value_class=drift_class,
        ),
    ]
    cell_count = len(cells)
    grid_style = f"grid-template-columns: repeat({cell_count}, minmax(0, 1fr));"
    return (
        "<div class='kpi-strip-wrap'>"
        f"<div class='kpi-strip' style='{grid_style}'>"
        f"{''.join(cells)}"
        "</div>"
        "</div>"
    )


def build_portfolio_report_document(report_data: "PortfolioReportData") -> ReportDocument:
    sections = [
        ReportSection(
            key="performance-usd",
            title="Performance USD",
            summary="Primary time-weighted performance in USD with improved tables and interactive chart windows.",
            body_html=render_performance_tab(report_data.performance_usd_view_model),
        ),
        ReportSection(
            key="performance-sgd",
            title="Performance SGD",
            summary="Secondary performance view translated into SGD for local reporting and monitoring.",
            body_html=render_performance_tab(report_data.performance_sgd_view_model),
        ),
        ReportSection(
            key="risk",
            title="Risk",
            summary="Allocation, drift, breakdown, and position decomposition rendered as the canonical HTML report.",
            body_html=render_risk_tab(report_data.risk_view_model),
        ),
        ReportSection(
            key="artifacts",
            title="Artifacts",
            summary="Source artifact references used to build this report.",
            body_html=_render_artifact_section(report_data.artifact_metadata),
        ),
    ]
    return ReportDocument(
        title="Portfolio Monitor",
        subtitle="HTML-first portfolio report for export, embedding, and future report-type expansion.",
        as_of=report_data.as_of,
        sections=sections,
        warning_messages=tuple(report_data.warnings),
        head_html=f"<style>{render_risk_report_styles()}</style>{render_performance_assets()}",
        body_end_html=render_risk_report_script(),
        topline_html=build_topline_html(report_data),
    )


def render_portfolio_report(report_data: "PortfolioReportData") -> str:
    return render_report_document(build_portfolio_report_document(report_data))


def write_portfolio_report(report_data: "PortfolioReportData", output_path: str | Path) -> Path:
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render_portfolio_report(report_data), encoding="utf-8")
    return target


def render_portfolio_report_artifact(
    report_data: "PortfolioReportData",
    *,
    output_path: str | Path,
) -> "GeneratedReportArtifact":
    target = write_portfolio_report(report_data, output_path)
    from market_helper.application.portfolio_monitor.contracts import GeneratedReportArtifact

    return GeneratedReportArtifact(
        report_type="portfolio_monitor",
        title="Portfolio Monitor HTML Report",
        output_path=target,
        as_of=report_data.as_of,
        warnings=list(report_data.warnings),
        exists=target.exists(),
    )


def _render_artifact_section(metadata: "ArtifactMetadata") -> str:
    rows: list[HtmlTableRow] = []
    for key, value in asdict(metadata).items():
        rows.append(
            HtmlTableRow(
                cells={
                    "name": key.replace("_", " ").title(),
                    "value": _format_artifact_value(key, value),
                }
            )
        )
    return (
        "<div class='card'>"
        "<h2>Resolved Inputs</h2>"
        "<p>This appendix captures the resolved artifact paths used when the HTML report was rendered.</p>"
        f"{render_html_table(columns=_artifact_columns(), rows=rows, empty_message='No artifact metadata')}"
        "</div>"
    )


def _artifact_columns() -> list[HtmlTableColumn]:
    return [
        HtmlTableColumn("name", "Field"),
        HtmlTableColumn("value", "Value"),
    ]


def _format_artifact_value(key: str, value: object) -> str:
    if value is None:
        return "<span class='tone-muted'>n/a</span>"
    if key.endswith("as_of"):
        return html.escape(format_local_datetime(str(value)))
    if isinstance(value, Path):
        return html.escape(str(value))
    return html.escape(str(value))
