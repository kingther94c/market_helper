from __future__ import annotations

from dataclasses import asdict
import html
from pathlib import Path
from typing import TYPE_CHECKING

from market_helper.common.datetime_display import format_local_datetime
from market_helper.domain.regime_detection.services.regime_report_provider import (
    RegimeArtifactState,
)
from market_helper.reporting.html_tables import HtmlTableColumn, HtmlTableRow, render_html_table
from market_helper.domain.portfolio_monitor.services.performance_analytics import (
    BenchmarkComparisonRow,
)
from market_helper.reporting.performance_html import (
    PerformanceMetricRow,
    PerformanceReportViewModel,
    render_performance_assets,
    render_performance_tab,
)
from market_helper.reporting.regime_html import (
    regime_section_styles,
    render_regime_section_body,
)
from market_helper.reporting.report_document import ReportDocument, ReportSection, render_report_document
from market_helper.reporting.risk_html import (
    VOL_METHOD_DISPLAY_LABELS,
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


def _benchmark_row(
    view_model: PerformanceReportViewModel | None, label: str
) -> BenchmarkComparisonRow | None:
    """Look up the benchmark-comparison row for a window (MTD / YTD / 1Y).

    The SGD performance view-model carries `BenchmarkComparisonRow.twr_pnl` —
    the absolute dollar PnL for the window — which the Overview uses to expose
    YTD $ PNL (SGD) alongside the percentage returns. Returns None when the
    window isn't present.
    """
    if view_model is None:
        return None
    for row in view_model.benchmark_rows:
        if row.label == label:
            return row
    return None


def _ex_ante_vol_value(view_model: RiskReportViewModel | None) -> float | None:
    """Read the portfolio's ex-ante vol at the report's correlation snapshot
    using the report's *actual* vol method, not a hard-coded one. Mirrors the
    cell the user picked in the Risk tab's vol-method segmented control."""
    if view_model is None:
        return None
    matrix_row = view_model.portfolio_vol_matrix.get(view_model.inter_asset_corr, {})
    return matrix_row.get(view_model.vol_method)


def _ex_ante_vol_label(view_model: RiskReportViewModel | None) -> str:
    """Resolve the displayed vol-method name (e.g. 'Fast' for 'geomean_1m_3m')."""
    if view_model is None:
        return ""
    return VOL_METHOD_DISPLAY_LABELS.get(view_model.vol_method, view_model.vol_method)


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


def _regime_kpi_cell(state: RegimeArtifactState) -> str:
    """Regime summary cell: regime label with an agreement + risk-overlay sub-line.

    Renders parallel ‟unavailable" presentations for missing / engine_error
    states so the KPI strip always has six cells instead of going blank.
    """
    view_model = state.view_model
    if view_model is None:
        sub = (
            "engine error — see Regime section"
            if state.state == "engine_error"
            else "no regime artifact — click Refresh Regime"
        )
        return _kpi_cell(
            "Regime",
            "<span class='kpi__regime'><span class='kpi__regime-dot' aria-hidden='true'></span>Unavailable</span>",
            html.escape(sub),
            value_class=" is-warn",
        )
    sub_parts: list[str] = []
    if view_model.method_agreement is not None:
        sub_parts.append(f"Agreement {view_model.method_agreement:.0%}")
    if view_model.crisis_flag is not None:
        if view_model.schema == "regime-engine-v2":
            sub_parts.append("Risk overlay on" if view_model.crisis_flag else "Risk overlay off")
        else:
            sub_parts.append("Crisis on" if view_model.crisis_flag else "Crisis off")
    if state.state == "stale":
        sub_parts.append("stale vs trading day T-1")
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

    # Ex-ante Vol: the portfolio's forward-looking vol under the *user's
    # currently-selected* vol method (Fast / Long-Term / Forward-Looking) at
    # the report's correlation snapshot. The displayed method name follows
    # `risk.vol_method` so the topline matches the Risk tab's segmented control
    # rather than hard-coding "Fast".
    ex_ante_vol = _ex_ante_vol_value(risk)
    ex_ante_label = _ex_ante_vol_label(risk)
    ex_ante_sub = (
        f"{risk.vol_method} · {risk.inter_asset_corr} corr"
        if risk is not None and ex_ante_vol is not None
        else ""
    )

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
            f"Ex-ante Vol ({ex_ante_label})" if ex_ante_label else "Ex-ante Vol",
            html.escape(_format_pct(ex_ante_vol)),
            html.escape(ex_ante_sub),
        ),
        _regime_kpi_cell(report_data.regime_state),
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


def build_regime_ribbon_html(state: RegimeArtifactState) -> str:
    """Single-line sticky regime ribbon rendered under the app-bar.

    Always renders something so the chrome layout stays stable. For
    missing / engine_error states the ribbon shows an unavailable pill
    plus a one-line action hint that mirrors the in-body card.
    """
    view_model = state.view_model
    if view_model is None:
        action = (
            "regime engine failed — see Regime section"
            if state.state == "engine_error"
            else "no regime data — click Refresh Regime"
        )
        return (
            "<div class='regime-ribbon'>"
            "<div class='regime-ribbon__row'>"
            "<span class='regime-ribbon__pill regime-ribbon__pill--unavailable'>"
            "<span class='regime-ribbon__dot'></span>Regime unavailable"
            "</span>"
            f"<span class='regime-ribbon__crisis is-on'>{html.escape(action)}</span>"
            "</div>"
            "</div>"
        )
    pieces: list[str] = [
        f"<span class='regime-ribbon__pill'><span class='regime-ribbon__dot'></span>{html.escape(view_model.regime)}</span>"
    ]
    meta_pieces: list[str] = []
    if view_model.method_agreement is not None:
        meta_pieces.append(f"Agreement <b>{view_model.method_agreement:.0%}</b>")
    if view_model.duration_days is not None:
        meta_pieces.append(f"Duration <b class='num'>{view_model.duration_days}d</b>")
    if state.state == "stale":
        meta_pieces.append("<b>stale vs T-1</b>")
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


def _render_regime_unavailable_card(state: RegimeArtifactState) -> str:
    """Body content for the regime section when no view-model could be built.

    Spells out exactly which state the regime is in, when the engine last ran,
    which mode we tried, the error message (for engine_error), and the precise
    user action that fixes it. This is the *single* place where ‟regime missing"
    is explained to the user — KPI cell + ribbon link to it via the section
    anchor.
    """
    title = (
        "Regime engine failed"
        if state.state == "engine_error"
        else "Regime artifact not available"
    )
    detail_rows: list[tuple[str, str]] = []
    detail_rows.append(("State", state.state.replace("_", " ")))
    detail_rows.append(("Mode tried", state.mode_used))
    detail_rows.append(("Freshness rule", "regime.as_of must reach T-1 trading day"))
    if state.last_run_at is not None:
        detail_rows.append(("Last engine run", format_local_datetime(state.last_run_at.isoformat())))
    if state.regime_as_of:
        detail_rows.append(("Regime data as of", format_local_datetime(state.regime_as_of)))
    if state.error_message:
        detail_rows.append(("Error", state.error_message))
    detail_html = "".join(
        f"<dt>{html.escape(label)}</dt><dd>{html.escape(value)}</dd>"
        for label, value in detail_rows
    )
    fix_html = (
        "<p class='regime-unavailable__fix'><strong>How to fix:</strong> "
        "click <b>Refresh Regime</b> in the dashboard's Regime card, "
        "or run <code>scripts/run_regime_detection.bat</code> from the project root. "
        "The combined report's daily cron auto-refreshes regime whenever "
        "the snapshot lags the latest trading day (same T-1 rule as the "
        "report's overall freshness note).</p>"
    )
    return (
        "<div class='regime-unavailable'>"
        f"<h3 class='regime-unavailable__title'>{html.escape(title)}</h3>"
        "<p class='regime-unavailable__lede'>"
        "The combined report needs a regime snapshot to populate the growth / inflation "
        "axes, layer detail, and risk overlay. None is currently available."
        "</p>"
        f"<dl class='regime-unavailable__grid'>{detail_html}</dl>"
        f"{fix_html}"
        "</div>"
    )


_REGIME_RIBBON_STYLES = """
.regime-ribbon { position: sticky; top: 49px; z-index: 20; background: var(--surface); border-bottom: 1px solid var(--panel-border); }
.regime-ribbon__row { max-width: 1540px; margin: 0 auto; padding: 8px 24px; display: flex; align-items: center; gap: 20px; font-size: 13px; flex-wrap: wrap; }
.regime-ribbon__pill { display: inline-flex; align-items: center; gap: 8px; padding: 4px 10px; border-radius: 999px; background: var(--accent-soft); color: var(--accent-ink); font-weight: 700; font-size: 12px; letter-spacing: 0.02em; }
.regime-ribbon__pill--unavailable { background: var(--warning-bg); color: var(--warn); }
.regime-ribbon__pill--unavailable .regime-ribbon__dot { background: var(--warn); }
.regime-ribbon__dot { width: 6px; height: 6px; border-radius: 999px; background: var(--accent); }
.regime-ribbon__meta { display: flex; gap: 20px; color: var(--muted-ink); }
.regime-ribbon__meta b { color: var(--ink-2); font-weight: 600; }
.regime-ribbon__crisis { display: inline-flex; align-items: center; gap: 6px; padding: 2px 8px; border-radius: 999px; background: var(--surface-2); color: var(--muted-ink); font-size: 12px; font-weight: 600; }
.regime-ribbon__crisis.is-on { background: var(--neg-soft); color: var(--neg); }
.regime-ribbon__transition { margin-left: auto; color: var(--muted-ink); font-size: 12px; }
.regime-ribbon__transition b { color: var(--ink-2); }

.regime-unavailable { padding: 20px 22px; border-radius: var(--r-3); border: 1px dashed var(--warning-border); background: var(--warning-bg); color: var(--warn); }
.regime-unavailable__title { margin: 0 0 6px; font-size: 16px; font-weight: 700; }
.regime-unavailable__lede { margin: 0 0 12px; color: var(--ink-2); font-size: 13px; max-width: 720px; }
.regime-unavailable__grid { display: grid; grid-template-columns: max-content 1fr; column-gap: 16px; row-gap: 4px; margin: 0 0 12px; font-size: 12px; font-variant-numeric: tabular-nums; }
.regime-unavailable__grid dt { color: var(--muted-ink); font-weight: 600; text-transform: uppercase; letter-spacing: 0.04em; font-size: 11px; }
.regime-unavailable__grid dd { margin: 0; color: var(--ink); }
.regime-unavailable__fix { margin: 0; font-size: 13px; color: var(--ink-2); }
.regime-unavailable__fix code { background: var(--surface); padding: 1px 6px; border-radius: 4px; border: 1px solid var(--panel-border); font-family: var(--font-mono, monospace); font-size: 12px; }
"""


def build_overview_section_body(report_data: "PortfolioReportData") -> str:
    """Landing-tab body: headline KPIs (incl. YTD $ PNL SGD) + the regime body.

    Reuses the same KPI grid styles as the sticky topline strip but adds one
    cell — the dollar-denominated YTD P&L in SGD — that the topline strip
    doesn't carry, so a user opening the report can see both percentage and
    absolute YTD performance side-by-side without scrolling tabs. The regime
    section body is embedded inline (same renderer as the dedicated Regime
    tab) so the at-a-glance view is genuinely one-stop.
    """
    risk = report_data.risk_view_model
    summary = risk.summary if risk is not None else None
    perf_sgd = report_data.performance_sgd_view_model

    mtd_sgd_row = _horizon_row(perf_sgd, "MTD")
    ytd_sgd_row = _horizon_row(perf_sgd, "YTD")
    ytd_sgd_bench = _benchmark_row(perf_sgd, "YTD")
    ytd_dollar_pnl_sgd = ytd_sgd_bench.twr_pnl if ytd_sgd_bench is not None else None

    nav_usd = summary.funded_aum_usd if summary is not None else None
    nav_sgd = summary.funded_aum_sgd if summary is not None else None

    ex_ante_vol = _ex_ante_vol_value(risk)
    ex_ante_label = _ex_ante_vol_label(risk)
    ex_ante_sub = (
        f"{risk.vol_method} · {risk.inter_asset_corr} corr"
        if risk is not None and ex_ante_vol is not None
        else ""
    )

    cells = [
        _kpi_cell("NAV (USD)", html.escape(_format_money_usd(nav_usd))),
        _kpi_cell("NAV (SGD)", html.escape(_format_money_usd(nav_sgd))),
        _kpi_cell(
            "Return MTD (SGD)",
            html.escape(_format_pct(mtd_sgd_row.twr_return if mtd_sgd_row else None, signed=True)),
            value_class=_delta_class(mtd_sgd_row.twr_return if mtd_sgd_row else None),
        ),
        _kpi_cell(
            "Return YTD (SGD)",
            html.escape(_format_pct(ytd_sgd_row.twr_return if ytd_sgd_row else None, signed=True)),
            value_class=_delta_class(ytd_sgd_row.twr_return if ytd_sgd_row else None),
        ),
        _kpi_cell(
            "YTD $ PNL (SGD)",
            html.escape(_format_money_signed(ytd_dollar_pnl_sgd)),
            "absolute, TWR-windowed",
            value_class=_delta_class(ytd_dollar_pnl_sgd),
        ),
        _kpi_cell(
            f"Ex-ante Vol ({ex_ante_label})" if ex_ante_label else "Ex-ante Vol",
            html.escape(_format_pct(ex_ante_vol)),
            html.escape(ex_ante_sub),
        ),
        _regime_kpi_cell(report_data.regime_state),
    ]
    grid_style = f"grid-template-columns: repeat({len(cells)}, minmax(0, 1fr));"
    kpi_block = (
        "<div class='overview-kpis'>"
        f"<div class='kpi-strip' style='{grid_style}'>"
        + "".join(cells)
        + "</div>"
        "</div>"
    )
    regime_block = (
        "<div class='overview-regime'>"
        + _render_regime_section_body_for_state(
            report_data.regime_state,
            parent_as_of=report_data.as_of,
        )
        + "</div>"
    )
    return kpi_block + regime_block


def _format_money_signed(value: float | None) -> str:
    """Money formatter that shows a leading sign for positive values (so $ PNL
    KPIs read like ‟+$12,345" / ‟-$1,234"). Mirrors the percent formatter's
    `signed=True` behaviour."""
    if value is None:
        return "—"
    if value > 0:
        return f"+${value:,.0f}"
    if value < 0:
        return f"-${abs(value):,.0f}"
    return "$0"


_OVERVIEW_STYLES = """
.overview-kpis { margin-bottom: 24px; }
.overview-kpis .kpi-strip {
  display: grid; gap: 1px; background: var(--panel-border);
  border: 1px solid var(--panel-border); border-radius: var(--r-3); overflow: hidden;
  box-shadow: var(--shadow-1);
}
.overview-kpis .kpi { background: var(--surface); padding: 14px 18px; display: flex; flex-direction: column; gap: 4px; }
.overview-kpis .kpi__label { font-size: 11px; letter-spacing: 0.04em; text-transform: uppercase; color: var(--muted-ink); font-weight: 600; }
.overview-kpis .kpi__value { font-size: 21px; font-weight: 700; line-height: 1.15; font-variant-numeric: tabular-nums; }
.overview-kpis .kpi__sub { font-size: 11px; color: var(--muted-ink); font-variant-numeric: tabular-nums; min-height: 14px; }
.overview-regime > .regime-v2-hero { margin-top: 0; }
"""


def build_portfolio_report_document(report_data: "PortfolioReportData") -> ReportDocument:
    sections = [
        ReportSection(
            key="overview",
            title="Overview",
            summary="Headline NAV, returns, ex-ante vol, and the regime section in one place — the report's landing view.",
            body_html=build_overview_section_body(report_data),
        ),
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
    # Regime body lives inside the Overview section (the report's landing
    # view); no separate Regime tab — the previous layout rendered the same
    # body twice (Overview AND a standalone Regime section), which was
    # visually noisy. Ribbon + KPI cell are the cross-tab summaries.
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
        # Regime CSS is always injected — the regime section is now always
        # present, even when the view-model is missing (renders an explainer
        # card instead of going blank).
        f"<style>{regime_section_styles()}{_REGIME_RIBBON_STYLES}{_OVERVIEW_STYLES}</style>",
    ]
    return ReportDocument(
        title="Portfolio Monitor",
        subtitle="HTML-first portfolio report for export, embedding, and future report-type expansion.",
        as_of=report_data.as_of,
        sections=sections,
        warning_messages=tuple(report_data.warnings),
        head_html="".join(head_html_pieces),
        body_end_html=render_risk_report_script(),
        topline_html=build_topline_html(report_data),
        ribbon_html=build_regime_ribbon_html(report_data.regime_state),
        as_of_freshness_note=report_data.as_of_freshness_note,
    )


def _render_regime_section_body_for_state(
    state: RegimeArtifactState,
    *,
    parent_as_of: str,
) -> str:
    """Dispatch the regime section body based on the provider's tagged state.

    Single switch instead of the previous five scattered ``view_model is None``
    branches. ``ok``/``stale`` get the full v2 body (with the existing
    parent-vs-regime stale tag); ``missing``/``engine_error`` get the
    actionable unavailable card.
    """
    if state.view_model is not None:
        return render_regime_section_body(
            state.view_model,
            parent_as_of=parent_as_of,
        )
    return _render_regime_unavailable_card(state)


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
