from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import csv
import html
import json
import os

import pandas as pd

from market_helper.domain.portfolio_monitor.services.performance_analytics import (
    BenchmarkComparisonRow,
    PerformanceMetricRow,
    build_window_benchmark_row,
    build_window_metric_row,
    build_yearly_metric_rows,
    dollar_cumulative_plot_frame,
    dollar_drawdown_plot_frame,
    load_nav_cashflow_history_frame,
    percent_cumulative_plot_frame,
    percent_drawdown_plot_frame,
    slice_history_for_window,
)
from market_helper.reporting.html_tables import HtmlTableColumn, HtmlTableRow, render_html_table

try:
    from plotly.offline.offline import get_plotlyjs
except ImportError:  # pragma: no cover - exercised only when plotly is absent
    def get_plotlyjs() -> str:
        return ""


_DISPLAY_WINDOW_LABELS = {
    "MTD": "MTD",
    "YTD": "YTD",
    "1Y": "1Y",
    "FULL": "Full History",
}


@dataclass(frozen=True)
class PerformanceSummaryCard:
    label: str
    primary_value: float | str | None
    secondary_value: float | str | None = None
    secondary_label: str | None = None
    value_kind: str = "text"


@dataclass(frozen=True)
class PerformanceReportViewModel:
    as_of: str
    primary_currency: str
    secondary_currency: str | None
    primary_basis: str
    summary_cards: list[PerformanceSummaryCard]
    chart_specs: dict[str, dict[str, dict[str, object]]]
    horizon_rows: list[PerformanceMetricRow]
    yearly_rows: list[PerformanceMetricRow]
    benchmark_rows: list[BenchmarkComparisonRow]


def build_performance_report_view_model(
    history: pd.DataFrame,
    *,
    report_csv_path: str | Path | None = None,
    primary_currency: str = "USD",
    secondary_currency: str | None = "SGD",
    primary_basis: str = "TWR",
) -> PerformanceReportViewModel:
    frame = history.copy()
    as_of = "n/a" if frame.empty else pd.Timestamp(frame["date"].max()).date().isoformat()

    _ = _load_report_rows(report_csv_path)
    horizon_rows = [
        build_window_metric_row(
            frame,
            window=window,
            primary_currency=primary_currency,
            secondary_currency=secondary_currency,
            include_provisional=True,
        )
        for window in ("MTD", "YTD", "1Y", "FULL")
    ]
    summary_cards = _build_overview_summary_cards(horizon_rows, primary_currency=primary_currency)
    yearly_rows = build_yearly_metric_rows(
        frame,
        primary_currency=primary_currency,
        secondary_currency=secondary_currency,
    )
    benchmark_rows = [
        build_window_benchmark_row(frame, window=window, currency=primary_currency, include_provisional=True)
        for window in ("MTD", "YTD", "1Y")
    ]
    return PerformanceReportViewModel(
        as_of=as_of,
        primary_currency=primary_currency,
        secondary_currency=secondary_currency,
        primary_basis=primary_basis,
        summary_cards=summary_cards,
        chart_specs=build_performance_chart_specs(frame, primary_currency),
        horizon_rows=horizon_rows,
        yearly_rows=yearly_rows,
        benchmark_rows=benchmark_rows,
    )


def _build_overview_summary_cards(
    horizon_rows: list[PerformanceMetricRow],
    *,
    primary_currency: str,
) -> list[PerformanceSummaryCard]:
    """Performance Overview KPI cards, all in `primary_currency`.

    Excess Return / Vol / Sharpe are the 1Y excess-over-BIL-cash stats; vol and
    Sharpe share the same daily excess-return series.
    """
    by_label = {row.label: row for row in horizon_rows}
    one_year = by_label.get("1Y")
    return [
        PerformanceSummaryCard(
            label="Total Return MTD",
            primary_value=by_label["MTD"].twr_return if "MTD" in by_label else None,
            value_kind="percent",
        ),
        PerformanceSummaryCard(
            label="Total Return YTD",
            primary_value=by_label["YTD"].twr_return if "YTD" in by_label else None,
            value_kind="percent",
        ),
        PerformanceSummaryCard(
            label="Total Return 1Y",
            primary_value=one_year.twr_return if one_year else None,
            value_kind="percent",
        ),
        PerformanceSummaryCard(
            label="Excess Return 1Y (over BIL cash)",
            primary_value=one_year.annualized_excess_return if one_year else None,
            value_kind="percent",
        ),
        PerformanceSummaryCard(
            label="Vol 1Y (excess return)",
            primary_value=one_year.annualized_excess_vol if one_year else None,
            value_kind="percent",
        ),
        PerformanceSummaryCard(
            label="Sharpe 1Y (excess return)",
            primary_value=one_year.sharpe_ratio if one_year else None,
            value_kind="ratio",
        ),
    ]


_PLOTLY_CDN_TAG = "<script src='https://cdn.plot.ly/plotly-2.35.2.min.js'></script>"


def _resolve_plotly_loader() -> str:
    """Return the `<script>` tag that loads Plotly into the report.

    Mode is chosen by the `MARKET_HELPER_PLOTLY_MODE` env var:
      * `inline` (default) — embed the bundled `get_plotlyjs()` payload,
        producing a self-contained ~3 MB HTML report that opens with no
        network access. Falls back to the CDN tag if the bundle is missing
        (e.g. plotly extra not installed in the environment).
      * `cdn` — always emit the CDN `<script src=...>` tag instead of
        bundling. Drops the report size by ~3 MB at the cost of needing
        an internet connection to view charts.
    """
    mode = os.environ.get("MARKET_HELPER_PLOTLY_MODE", "inline").strip().lower()
    if mode == "cdn":
        return _PLOTLY_CDN_TAG
    plotly_js = get_plotlyjs()
    if plotly_js.strip():
        return f"<script>{plotly_js}</script>"
    return _PLOTLY_CDN_TAG


def render_performance_assets() -> str:
    plotly_loader = _resolve_plotly_loader()
    return (
        "<style>"
        ".perf-summary-grid { display:grid; gap:12px; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); }"
        ".perf-summary-card { padding:16px 18px; border-radius:var(--r-2); border:1px solid var(--border-soft); background:linear-gradient(180deg, var(--surface), var(--surface-2)); box-shadow:var(--shadow-1); transition:box-shadow 0.15s ease, transform 0.15s ease; }"
        ".perf-summary-card:hover { box-shadow:var(--shadow-2); transform:translateY(-1px); }"
        ".perf-summary-label { display:block; margin-bottom:8px; font-size:11px; font-weight:600; letter-spacing:0.04em; text-transform:uppercase; color:var(--muted-ink); }"
        ".perf-summary-value { display:block; font-family:var(--font-sans); font-size:24px; font-weight:700; line-height:1.1; color:var(--ink); font-variant-numeric:tabular-nums; }"
        ".perf-summary-value.tone-positive { color:var(--pos); }"
        ".perf-summary-value.tone-negative { color:var(--neg); }"
        ".perf-summary-secondary { display:block; margin-top:8px; padding-top:8px; border-top:1px solid var(--border-soft); color:var(--muted-ink); font-size:12px; font-weight:600; font-variant-numeric:tabular-nums; }"
        ".perf-chart-shell { display:grid; gap:18px; }"
        ".perf-chart-toolbar { display:grid; grid-template-columns: minmax(0, 1.2fr) minmax(320px, 0.9fr); gap:18px; align-items:start; }"
        ".perf-controls { display:grid; gap:12px; justify-items:end; margin:0; }"
        ".perf-control-row { display:flex; flex-wrap:wrap; align-items:center; justify-content:flex-end; gap:10px; }"
        ".perf-control-label { font-size:12px; font-weight:800; letter-spacing:0.08em; text-transform:uppercase; color:#475569; min-width:120px; }"
        # `.segmented-control` and variants are provided by `_design_tokens.design_tokens_css()`
        # injected into the `report_document` shell. The `@media` rule below overrides width
        # for narrow viewports.
        ".perf-card-header { display:grid; gap:6px; }"
        ".perf-card-header p { margin:0; }"
        ".perf-card-kicker { margin:0; font-size:12px; font-weight:800; letter-spacing:0.08em; text-transform:uppercase; color:#0f766e; }"
        ".perf-plot-frame { padding:16px 16px 8px; border-radius:20px; background:linear-gradient(180deg, rgba(248,250,252,0.96), rgba(255,255,255,0.98)); border:1px solid rgba(148,163,184,0.18); }"
        ".perf-plot { min-height: 520px; }"
        "@media (max-width: 720px) {"
        ".perf-chart-toolbar { grid-template-columns: 1fr; }"
        ".perf-control-row { align-items:flex-start; flex-direction:column; }"
        ".perf-controls { justify-items:start; }"
        ".perf-control-row { justify-content:flex-start; }"
        ".perf-control-label { min-width:0; }"
        ".segmented-control { width:100%; }"
        "}"
        "</style>"
        f"{plotly_loader}"
        "<script>"
        "if (!window.__marketHelperPerfAssetsLoaded) {"
        "window.__marketHelperPerfAssetsLoaded = true;"
        "window.__marketHelperInitPerformanceTab = function(targetId, figures, defaultMode, defaultWindow) {"
        "const container = document.getElementById(targetId);"
        "if (!container) { return; }"
        "container.dataset.perfTargetId = targetId;"
        "const scope = container.closest('.perf-tab');"
        "if (!scope) { return; }"
        "const modeButtons = scope.querySelectorAll('[data-perf-group=\"mode\"][data-perf-target=\"' + targetId + '\"]');"
        "const windowButtons = scope.querySelectorAll('[data-perf-group=\"window\"][data-perf-target=\"' + targetId + '\"]');"
        "const state = { mode: defaultMode, window: defaultWindow, attempts: 0 };"
        "const updateButtons = function(groupButtons, activeValue) {"
        "groupButtons.forEach((button) => {"
        "const isActive = button.getAttribute('data-perf-value') === activeValue;"
        "button.classList.toggle('is-active', isActive);"
        "button.setAttribute('aria-selected', isActive ? 'true' : 'false');"
        "});"
        "};"
        "const renderFigure = function() {"
        "if (typeof Plotly === 'undefined') {"
        "if (state.attempts >= 40) { return; }"
        "state.attempts += 1;"
        "window.setTimeout(renderFigure, 125);"
        "return;"
        "}"
        "const figure = figures?.[state.mode]?.[state.window];"
        "if (!figure) { return; }"
        "const config = {displayModeBar: false, responsive: true};"
        "if (container.dataset.perfRendered === 'true') {"
        "Plotly.react(targetId, figure.data, figure.layout, config);"
        "} else {"
        "Plotly.newPlot(targetId, figure.data, figure.layout, config);"
        "container.dataset.perfRendered = 'true';"
        "}"
        "updateButtons(modeButtons, state.mode);"
        "updateButtons(windowButtons, state.window);"
        "};"
        "modeButtons.forEach((button) => {"
        "button.addEventListener('click', () => { state.mode = button.getAttribute('data-perf-value'); renderFigure(); });"
        "});"
        "windowButtons.forEach((button) => {"
        "button.addEventListener('click', () => { state.window = button.getAttribute('data-perf-value'); renderFigure(); });"
        "});"
        "renderFigure();"
        "};"
        "window.__marketHelperResizePerformancePlots = function(root) {"
        "if (typeof Plotly === 'undefined') { return; }"
        "const scope = root || document;"
        "scope.querySelectorAll('.perf-plot').forEach((container) => {"
        "if (container.dataset.perfRendered === 'true') {"
        "Plotly.Plots.resize(container);"
        "}"
        "});"
        "};"
        "}"
        "</script>"
    )


def render_performance_tab(view_model: PerformanceReportViewModel) -> str:
    summary_cards = "\n".join(_render_summary_card(card) for card in view_model.summary_cards)
    horizon_table = render_html_table(
        columns=_metric_table_columns(include_annualized_return=True),
        rows=_metric_table_rows(view_model.horizon_rows, include_annualized_return=True),
        empty_message="No horizon data",
    )
    yearly_table = render_html_table(
        columns=_metric_table_columns(include_annualized_return=False),
        rows=_metric_table_rows(view_model.yearly_rows, include_annualized_return=False),
        empty_message="No yearly data",
    )
    benchmark_table = render_html_table(
        columns=_benchmark_table_columns(view_model.primary_currency),
        rows=_benchmark_table_rows(view_model.benchmark_rows),
        empty_message="No benchmark comparison data",
    )
    instance_id = f"perf-plot-{view_model.primary_currency.lower()}"
    overview_text = (
        f"All figures in <strong>{html.escape(view_model.primary_currency)}</strong>, "
        f"{html.escape(view_model.primary_basis)} basis. "
        "Excess Return, Vol, and Sharpe are 1Y excess-over-BIL-cash; "
        "Vol and Sharpe share the same daily excess-return series."
    )
    chart_specs = json.dumps(view_model.chart_specs, separators=(",", ":"))
    return (
        "<section class='perf-tab'>"
        "<div class='card'>"
        "<h2>Performance Overview</h2>"
        f"<p>{overview_text}</p>"
        f"<div class='perf-summary-grid'>{summary_cards}</div>"
        "</div>"
        "<div class='card'>"
        "<div class='perf-chart-shell'>"
        "<div class='perf-chart-toolbar'>"
        "<div class='perf-card-header'>"
        "<p class='perf-card-kicker'>Interactive Chart</p>"
        "<h2>Cumulative Performance And Drawdown</h2>"
        "<p>Shared x-axis, stacked for easier reading. Switch between return and PnL without losing the selected window.</p>"
        "</div>"
        f"{_render_chart_tabs(instance_id)}"
        "</div>"
        f"<div class='perf-plot-frame'><div id='{instance_id}' class='perf-plot'></div></div>"
        "</div>"
        "<script>"
        f"window.__marketHelperInitPerformanceTab('{instance_id}', {chart_specs}, 'percent', 'MTD');"
        "</script>"
        "</div>"
        "<div class='card'>"
        "<h2>Horizon Metrics</h2>"
        f"{horizon_table}"
        "</div>"
        "<div class='card'>"
        "<h2>Benchmark Comparison</h2>"
        f"<p>Portfolio TWR / MWR against Cash (BIL) and SPY per window, in returns and "
        f"{html.escape(view_model.primary_currency)} PnL. Benchmark PnL is hypothetical: "
        "the window's opening NAV compounded at the benchmark return.</p>"
        f"{benchmark_table}"
        "</div>"
        "<div class='card'>"
        "<h2>Historical Years</h2>"
        f"{yearly_table}"
        "</div>"
        "</section>"
    )


def _load_report_rows(report_csv_path: str | Path | None) -> list[dict[str, str]]:
    if report_csv_path is None:
        return []
    path = Path(report_csv_path)
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def build_performance_chart_specs(history: pd.DataFrame, currency: str) -> dict[str, dict[str, dict[str, object]]]:
    specs: dict[str, dict[str, dict[str, object]]] = {"percent": {}, "dollar": {}}
    for window in ("MTD", "YTD", "1Y", "FULL"):
        window_history = slice_history_for_window(history, window=window, include_provisional=True)
        percent_cum = percent_cumulative_plot_frame(window_history, currency, include_provisional=True)
        percent_dd = percent_drawdown_plot_frame(window_history, currency, include_provisional=True)
        dollar_cum = dollar_cumulative_plot_frame(window_history, currency, include_provisional=True)
        dollar_dd = dollar_drawdown_plot_frame(window_history, currency, include_provisional=True)
        specs["percent"][window] = _build_figure_spec(
            percent_cum,
            percent_dd,
            currency=currency,
            mode="percent",
            window=window,
        )
        specs["dollar"][window] = _build_figure_spec(
            dollar_cum,
            dollar_dd,
            currency=currency,
            mode="dollar",
            window=window,
        )
    return specs


def _build_figure_spec(
    cumulative_frame: pd.DataFrame,
    drawdown_frame: pd.DataFrame,
    *,
    currency: str,
    mode: str,
    window: str,
) -> dict[str, object]:
    if mode == "percent":
        cumulative_column = "cumulative_return"
        drawdown_title = "Drawdown (%)"
        cumulative_title = "Cumulative Performance (%)"
        hover_template = "%{x|%Y-%m-%d}<br>%{y:.2%}<extra></extra>"
    else:
        cumulative_column = "cumulative_pnl"
        drawdown_title = f"Drawdown ({currency})"
        cumulative_title = f"Cumulative PnL ({currency})"
        hover_template = "%{x|%Y-%m-%d}<br>%{y:,.2f}<extra></extra>"

    if cumulative_frame.empty or cumulative_column not in cumulative_frame.columns or drawdown_frame.empty:
        return {
            "data": [],
            "layout": {
                "template": "plotly_white",
                "annotations": [
                    {
                        "text": "No data",
                        "xref": "paper",
                        "yref": "paper",
                        "x": 0.5,
                        "y": 0.5,
                        "showarrow": False,
                        "font": {"size": 14, "color": "#64748b"},
                    }
                ],
                "height": 520,
                "margin": {"l": 72, "r": 24, "t": 48, "b": 56},
                "title": {"text": f"{_DISPLAY_WINDOW_LABELS[window]} • {currency}"},
            },
        }

    cumulative_series = pd.to_numeric(cumulative_frame[cumulative_column], errors="coerce")
    dates = pd.to_datetime(cumulative_frame["date"], errors="coerce").dt.strftime("%Y-%m-%d").tolist()
    positive_values = _series_to_plot_values(cumulative_series.where(cumulative_series >= 0))
    negative_values = _series_to_plot_values(cumulative_series.where(cumulative_series < 0))
    cumulative_values = _series_to_plot_values(cumulative_series)
    drawdown_values = _series_to_plot_values(pd.to_numeric(drawdown_frame["drawdown"], errors="coerce"))
    drawdown_dates = pd.to_datetime(drawdown_frame["date"], errors="coerce").dt.strftime("%Y-%m-%d").tolist()

    yaxis_tick_format = ".0%" if mode == "percent" else ",.0f"
    traces = [
        {
            "x": dates,
            "y": positive_values,
            "type": "scatter",
            "mode": "lines",
            "line": {"color": "rgba(0,0,0,0)", "width": 0},
            "fill": "tozeroy",
            "fillcolor": "rgba(22,163,74,0.18)",
            "hovertemplate": hover_template,
            "xaxis": "x",
            "yaxis": "y",
            "showlegend": False,
        },
        {
            "x": dates,
            "y": negative_values,
            "type": "scatter",
            "mode": "lines",
            "line": {"color": "rgba(0,0,0,0)", "width": 0},
            "fill": "tozeroy",
            "fillcolor": "rgba(220,38,38,0.18)",
            "hovertemplate": hover_template,
            "xaxis": "x",
            "yaxis": "y",
            "showlegend": False,
        },
        {
            "x": dates,
            "y": cumulative_values,
            "type": "scatter",
            "mode": "lines",
            "name": "Portfolio",
            "line": {"color": "#0f172a", "width": 3},
            "hovertemplate": hover_template,
            "xaxis": "x",
            "yaxis": "y",
            "showlegend": False,
        },
        {
            "x": drawdown_dates,
            "y": drawdown_values,
            "type": "scatter",
            "mode": "lines",
            "line": {"color": "#b91c1c", "width": 2.5},
            "fill": "tozeroy",
            "fillcolor": "rgba(185,28,28,0.18)",
            "hovertemplate": hover_template,
            "xaxis": "x2",
            "yaxis": "y2",
            "showlegend": False,
        },
    ]
    # Optional benchmark trace (dotted) — only on percent mode, only when the
    # cumulative frame already carries `bench_cumulative_return` (which means
    # `_percent_frame_from_history` saw the benchmark column on the input
    # history). PnL ($) mode stays portfolio-only since SPY has no $ analogue.
    if mode == "percent" and "bench_cumulative_return" in cumulative_frame.columns:
        bench_series = pd.to_numeric(cumulative_frame["bench_cumulative_return"], errors="coerce")
        if bench_series.notna().any():
            traces.append({
                "x": dates,
                "y": _series_to_plot_values(bench_series),
                "type": "scatter",
                "mode": "lines",
                "name": "SPY (benchmark)",
                "line": {"color": "#64748b", "width": 1.6, "dash": "dot"},
                "hovertemplate": "%{x|%Y-%m-%d}<br>SPY %{y:.2%}<extra></extra>",
                "xaxis": "x",
                "yaxis": "y",
                "showlegend": True,
            })
    layout = {
        "template": "plotly_white",
        "height": 520,
        "margin": {"l": 72, "r": 24, "t": 48, "b": 56},
        "paper_bgcolor": "#ffffff",
        "plot_bgcolor": "#ffffff",
        "title": {"text": f"{_DISPLAY_WINDOW_LABELS[window]} • {currency}"},
        "legend": {"orientation": "h", "x": 0, "y": 1.06, "xanchor": "left", "yanchor": "bottom", "bgcolor": "rgba(0,0,0,0)"},
        "grid": {"rows": 2, "columns": 1, "pattern": "independent", "roworder": "top to bottom"},
        "xaxis": {
            "matches": "x2",
            "showticklabels": False,
            "showgrid": True,
            "gridcolor": "#e2e8f0",
            "zeroline": False,
        },
        "xaxis2": {
            "title": "Date",
            "showgrid": True,
            "gridcolor": "#e2e8f0",
            "zeroline": False,
        },
        "yaxis": {
            "title": cumulative_title,
            "tickformat": yaxis_tick_format,
            "showgrid": True,
            "gridcolor": "#e2e8f0",
            "zeroline": True,
            "zerolinecolor": "#94a3b8",
        },
        "yaxis2": {
            "title": drawdown_title,
            "tickformat": yaxis_tick_format,
            "showgrid": True,
            "gridcolor": "#e2e8f0",
            "zeroline": True,
            "zerolinecolor": "#94a3b8",
        },
    }
    return {"data": traces, "layout": layout}


def _series_to_plot_values(series: pd.Series) -> list[float | None]:
    return [None if pd.isna(value) else float(value) for value in series.tolist()]


def _render_chart_tabs(target_id: str) -> str:
    mode_buttons = [
        ("percent", "Return %"),
        ("dollar", "PnL $"),
    ]
    window_buttons = [
        ("MTD", "MTD"),
        ("YTD", "YTD"),
        ("1Y", "1Y"),
        ("FULL", "Full History"),
    ]
    return (
        "<div class='perf-controls'>"
        f"<div class='perf-control-row'><div class='perf-control-label'>Measure</div>{_render_button_row(target_id, 'mode', mode_buttons, 'percent')}</div>"
        f"<div class='perf-control-row'><div class='perf-control-label'>Window</div>{_render_button_row(target_id, 'window', window_buttons, 'MTD')}</div>"
        "</div>"
    )


def _render_button_row(
    target_id: str,
    group: str,
    buttons: list[tuple[str, str]],
    active_value: str,
) -> str:
    rendered: list[str] = []
    for value, label in buttons:
        is_active = value == active_value
        rendered.append(
            "<button "
            "type='button' "
            f"class='segmented-control__button{' is-active' if is_active else ''}' "
            f"data-perf-target='{target_id}' "
            f"data-perf-group='{group}' "
            f"data-perf-value='{value}' "
            f"aria-selected='{'true' if is_active else 'false'}'>"
            f"{html.escape(label)}"
            "</button>"
        )
    return f"<div class='segmented-control'>{''.join(rendered)}</div>"


def _render_summary_card(card: PerformanceSummaryCard) -> str:
    secondary = ""
    if card.secondary_label is not None:
        secondary = (
            f"<small class='perf-summary-secondary'>{html.escape(card.secondary_label)}: {_format_metric_value(card.secondary_value, card.value_kind)}</small>"
        )
    tone_class = ""
    if card.value_kind in {"percent", "ratio"} and isinstance(card.primary_value, (int, float)):
        if card.primary_value > 0:
            tone_class = " tone-positive"
        elif card.primary_value < 0:
            tone_class = " tone-negative"
    return (
        "<div class='perf-summary-card'>"
        f"<span class='perf-summary-label'>{html.escape(card.label)}</span>"
        f"<strong class='perf-summary-value{tone_class}'>{_format_metric_value(card.primary_value, card.value_kind)}</strong>"
        f"{secondary}"
        "</div>"
    )


def _metric_table_columns(*, include_annualized_return: bool) -> list[HtmlTableColumn]:
    columns = [
        HtmlTableColumn("label", "Window"),
        HtmlTableColumn("twr_return", "TWR Return", align="num"),
        HtmlTableColumn("mwr_return", "MWR Return", align="num"),
    ]
    if include_annualized_return:
        columns.append(HtmlTableColumn("annualized_return", "Ann Return", align="num"))
    columns.extend(
        [
            HtmlTableColumn("annualized_vol", "Ann Vol", align="num"),
            HtmlTableColumn("sharpe_ratio", "Sharpe", align="num"),
            HtmlTableColumn("max_drawdown", "Max Drawdown", align="num"),
        ]
    )
    return columns


def _metric_table_rows(
    rows: list[PerformanceMetricRow],
    *,
    include_annualized_return: bool,
) -> list[HtmlTableRow]:
    output: list[HtmlTableRow] = []
    for row in rows:
        cells = {
            "label": _DISPLAY_WINDOW_LABELS.get(row.label, row.label),
            "twr_return": _format_metric_value(row.twr_return, "percent"),
            "mwr_return": _format_metric_value(row.mwr_return, "percent"),
            "annualized_vol": _format_metric_value(row.annualized_vol, "percent"),
            "sharpe_ratio": _format_metric_value(row.sharpe_ratio, "ratio"),
            "max_drawdown": _format_metric_value(row.max_drawdown, "percent"),
        }
        if include_annualized_return:
            cells["annualized_return"] = _format_metric_value(row.annualized_return, "percent")
        output.append(HtmlTableRow(cells=cells))
    return output


def _benchmark_table_columns(currency: str) -> list[HtmlTableColumn]:
    money = f"$ ({html.escape(currency)})"
    return [
        HtmlTableColumn("label", "Window"),
        HtmlTableColumn("twr_return", "TWR Return", align="num"),
        HtmlTableColumn("twr_pnl", f"TWR {money}", align="num"),
        HtmlTableColumn("mwr_return", "MWR Return", align="num"),
        HtmlTableColumn("mwr_pnl", f"MWR {money}", align="num"),
        HtmlTableColumn("cash_return", "Cash Return", align="num"),
        HtmlTableColumn("cash_pnl", f"Cash {money}", align="num"),
        HtmlTableColumn("spy_return", "SPY Return", align="num"),
        HtmlTableColumn("spy_pnl", f"SPY {money}", align="num"),
    ]


def _benchmark_table_rows(rows: list[BenchmarkComparisonRow]) -> list[HtmlTableRow]:
    output: list[HtmlTableRow] = []
    for row in rows:
        output.append(
            HtmlTableRow(
                cells={
                    "label": _DISPLAY_WINDOW_LABELS.get(row.label, row.label),
                    "twr_return": _format_metric_value(row.twr_return, "percent"),
                    "twr_pnl": _format_metric_value(row.twr_pnl, "money"),
                    "mwr_return": _format_metric_value(row.mwr_return, "percent"),
                    "mwr_pnl": _format_metric_value(row.mwr_pnl, "money"),
                    "cash_return": _format_metric_value(row.cash_return, "percent"),
                    "cash_pnl": _format_metric_value(row.cash_pnl, "money"),
                    "spy_return": _format_metric_value(row.spy_return, "percent"),
                    "spy_pnl": _format_metric_value(row.spy_pnl, "money"),
                }
            )
        )
    return output


def _format_metric_value(value: float | str | None, kind: str) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, str):
        return html.escape(value)
    if kind == "percent":
        return f"{float(value):.2%}"
    if kind == "ratio":
        return f"{float(value):.2f}"
    if kind == "money":
        return f"{float(value):,.0f}"
    return f"{float(value):,.2f}"


__all__ = [
    "PerformanceReportViewModel",
    "build_performance_chart_specs",
    "build_performance_report_view_model",
    "load_nav_cashflow_history_frame",
    "render_performance_assets",
    "render_performance_tab",
]
