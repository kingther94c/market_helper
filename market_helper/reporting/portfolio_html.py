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
from market_helper.reporting.regime_html import (
    RegimeHtmlViewModel,
    regime_section_styles,
    render_regime_section_body,
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


def _horizon_row(view_model: PerformanceReportViewModel | None, label: str) -> PerformanceMetricRow | None:
    if view_model is None:
        return None
    for row in view_model.horizon_rows:
        if row.label == label:
            return row
    return None


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


def _regime_kpi_cell(view_model: RegimeHtmlViewModel | None) -> str:
    """Regime summary cell: regime label with an agreement + risk-overlay sub-line."""
    if view_model is None:
        return _kpi_cell("Regime", "—", "no regime artifact")
    sub_parts: list[str] = []
    if view_model.method_agreement is not None:
        sub_parts.append(f"Agreement {view_model.method_agreement:.0%}")
    if view_model.crisis_flag is not None:
        if view_model.schema == "regime-engine-v2":
            sub_parts.append("Risk overlay on" if view_model.crisis_flag else "Risk overlay off")
        else:
            sub_parts.append("Crisis on" if view_model.crisis_flag else "Crisis off")
    value_class = " is-warn" if view_model.crisis_flag else ""
    value_html = (
        "<span class='kpi__regime'>"
        "<span class='kpi__regime-dot' aria-hidden='true'></span>"
        f"{html.escape(view_model.regime)}"
        "</span>"
    )
    return _kpi_cell("Regime", value_html, html.escape(" · ".join(sub_parts)), value_class=value_class)


def build_topline_html(report_data: "PortfolioReportData") -> str:
    """Build the KPI summary strip rendered above the section content.

    Pulls from the existing performance + risk + regime view-models — no new
    computation. Cells that can't be sourced render as `—`.
    """
    risk = report_data.risk_view_model
    summary = risk.summary if risk is not None else None
    perf_sgd = report_data.performance_sgd_view_model

    mtd_sgd = _horizon_row(perf_sgd, "MTD")
    ytd_sgd = _horizon_row(perf_sgd, "YTD")

    nav_usd = summary.funded_aum_usd if summary is not None else None
    nav_sgd = summary.funded_aum_sgd if summary is not None else None

    # Target Vol (Fast): the portfolio's realised vol under the Fast method
    # (geomean 1m/3m) at the report's historical-correlation snapshot — i.e. the
    # Historical row / Fast column of the Portfolio Vol Matrix.
    target_vol_fast = None
    if risk is not None:
        target_vol_fast = risk.portfolio_vol_matrix.get("historical", {}).get("geomean_1m_3m")

    cells = [
        _kpi_cell(
            "NAV (USD)",
            html.escape(_format_money_usd(nav_usd)),
        ),
        _kpi_cell(
            "NAV (SGD)",
            html.escape(_format_money_usd(nav_sgd)),
        ),
        _kpi_cell(
            "Return MTD (SGD)",
            html.escape(_format_pct(mtd_sgd.twr_return if mtd_sgd else None, signed=True)),
            value_class=_delta_class(mtd_sgd.twr_return if mtd_sgd else None),
        ),
        _kpi_cell(
            "Return YTD (SGD)",
            html.escape(_format_pct(ytd_sgd.twr_return if ytd_sgd else None, signed=True)),
            value_class=_delta_class(ytd_sgd.twr_return if ytd_sgd else None),
        ),
        _kpi_cell(
            "Target Vol (Fast)",
            html.escape(_format_pct(target_vol_fast)),
            "geomean 1m/3m · historical corr",
        ),
        _regime_kpi_cell(report_data.regime_view_model),
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


def build_regime_ribbon_html(view_model: RegimeHtmlViewModel | None) -> str:
    """Single-line sticky regime ribbon rendered under the app-bar (P5).

    Returns an empty string when no regime data is available so the shell
    naturally collapses the slot.
    """
    if view_model is None:
        return ""
    pieces: list[str] = [
        f"<span class='regime-ribbon__pill'><span class='regime-ribbon__dot'></span>{html.escape(view_model.regime)}</span>"
    ]
    meta_pieces: list[str] = []
    if view_model.method_agreement is not None:
        meta_pieces.append(f"Agreement <b>{view_model.method_agreement:.0%}</b>")
    if view_model.duration_days is not None:
        meta_pieces.append(f"Duration <b class='num'>{view_model.duration_days}d</b>")
    if meta_pieces:
        pieces.append(
            "<div class='regime-ribbon__meta'>"
            + "".join(f"<span>{m}</span>" for m in meta_pieces)
            + "</div>"
        )
    crisis_class = "regime-ribbon__crisis is-on" if view_model.crisis_flag else "regime-ribbon__crisis"
    if view_model.schema == "regime-engine-v2":
        crisis_label = "Risk overlay on" if view_model.crisis_flag else "Risk overlay off"
        if view_model.crisis_flag and view_model.crisis_intensity is not None:
            crisis_label = f"Risk overlay on · {view_model.crisis_intensity:.2f}"
    else:
        crisis_label = "Crisis on" if view_model.crisis_flag else "Crisis off"
        if view_model.crisis_flag and view_model.crisis_intensity is not None:
            crisis_label = f"Crisis on · {view_model.crisis_intensity:.2f}"
    pieces.append(f"<span class='{crisis_class}'>{html.escape(crisis_label)}</span>")
    if view_model.transitions:
        last = view_model.transitions[-1]
        pieces.append(
            "<span class='regime-ribbon__transition'>"
            f"Last change <b class='num'>{html.escape(last.as_of)}</b> · "
            f"{html.escape(last.from_regime)} → {html.escape(last.to_regime)}"
            "</span>"
        )
    return (
        "<div class='regime-ribbon'>"
        "<div class='regime-ribbon__row'>"
        + "".join(pieces)
        + "</div>"
        "</div>"
    )


_REGIME_RIBBON_STYLES = """
.regime-ribbon { position: sticky; top: 49px; z-index: 20; background: var(--surface); border-bottom: 1px solid var(--panel-border); }
.regime-ribbon__row { max-width: 1540px; margin: 0 auto; padding: 8px 24px; display: flex; align-items: center; gap: 20px; font-size: 13px; flex-wrap: wrap; }
.regime-ribbon__pill { display: inline-flex; align-items: center; gap: 8px; padding: 4px 10px; border-radius: 999px; background: var(--accent-soft); color: var(--accent-ink); font-weight: 700; font-size: 12px; letter-spacing: 0.02em; }
.regime-ribbon__dot { width: 6px; height: 6px; border-radius: 999px; background: var(--accent); }
.regime-ribbon__meta { display: flex; gap: 20px; color: var(--muted-ink); }
.regime-ribbon__meta b { color: var(--ink-2); font-weight: 600; }
.regime-ribbon__crisis { display: inline-flex; align-items: center; gap: 6px; padding: 2px 8px; border-radius: 999px; background: var(--surface-2); color: var(--muted-ink); font-size: 12px; font-weight: 600; }
.regime-ribbon__crisis.is-on { background: var(--neg-soft); color: var(--neg); }
.regime-ribbon__transition { margin-left: auto; color: var(--muted-ink); font-size: 12px; }
.regime-ribbon__transition b { color: var(--ink-2); }
"""


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
    ]
    if report_data.regime_view_model is not None:
        sections.append(
            ReportSection(
                key="regime",
                title="Regime",
                summary="Regime Engine context: growth/inflation axes, layer detail, independent risk overlay, disagreement, and history.",
                body_html=render_regime_section_body(
                    report_data.regime_view_model,
                    parent_as_of=report_data.as_of,
                ),
            )
        )
    sections.append(
        ReportSection(
            key="artifacts",
            title="Artifacts",
            summary="Source artifact references used to build this report.",
            body_html=_render_artifact_section(report_data.artifact_metadata),
        )
    )
    head_html_pieces = [
        f"<style>{render_risk_report_styles()}</style>",
        render_performance_assets(),
    ]
    if report_data.regime_view_model is not None:
        head_html_pieces.append(
            f"<style>{regime_section_styles()}{_REGIME_RIBBON_STYLES}</style>"
        )
    return ReportDocument(
        title="Portfolio Monitor",
        subtitle="HTML-first portfolio report for export, embedding, and future report-type expansion.",
        as_of=report_data.as_of,
        sections=sections,
        warning_messages=tuple(report_data.warnings),
        head_html="".join(head_html_pieces),
        body_end_html=render_risk_report_script(),
        topline_html=build_topline_html(report_data),
        ribbon_html=build_regime_ribbon_html(report_data.regime_view_model),
        as_of_freshness_note=report_data.as_of_freshness_note,
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
    # `render_html_table` escapes the cell value (column has no `allow_html`),
    # so we return plain text — the previous wrapping `<span>` markup leaked
    # through the escape and rendered as literal entities (B1).
    if value is None:
        return "n/a"
    if key.endswith("as_of"):
        return format_local_datetime(str(value))
    return str(value)
