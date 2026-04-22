from __future__ import annotations

from dataclasses import asdict
import html
from pathlib import Path
from typing import TYPE_CHECKING

from market_helper.common.datetime_display import format_local_datetime
from market_helper.reporting.html_tables import HtmlTableColumn, HtmlTableRow, render_html_table
from market_helper.reporting.performance_html import render_performance_assets, render_performance_tab
from market_helper.reporting.report_document import ReportDocument, ReportSection, render_report_document
from market_helper.reporting.risk_html import render_risk_report_script, render_risk_report_styles, render_risk_tab

if TYPE_CHECKING:
    from market_helper.application.portfolio_monitor.contracts import (
        ArtifactMetadata,
        GeneratedReportArtifact,
        PortfolioReportData,
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
