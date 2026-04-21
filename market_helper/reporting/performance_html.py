from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import csv
import html
import json

import pandas as pd

from market_helper.domain.portfolio_monitor.services.performance_analytics import (
    PerformanceMetricRow,
    annualized_return,
    annualized_vol,
    build_window_metric_row,
    build_yearly_metric_rows,
    dollar_cumulative_plot_frame,
    dollar_drawdown_plot_frame,
    load_nav_cashflow_history_frame,
    percent_cumulative_plot_frame,
    percent_drawdown_plot_frame,
    sharpe_ratio,
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
    summary_cards = [
        PerformanceSummaryCard(label="As of", primary_value=as_of),
        PerformanceSummaryCard(
            label="Since inception annualized return",
            primary_value=annualized_return(frame, primary_currency, include_provisional=True),
            secondary_value=(
                _safe_metric(frame, secondary_currency, annualized_return, include_provisional=True)
                if secondary_currency is not None
                else None
            ),
            secondary_label=secondary_currency,
            value_kind="percent",
        ),
        PerformanceSummaryCard(
            label="Since inception annualized vol",
            primary_value=annualized_vol(frame, primary_currency, include_provisional=True),
            secondary_value=(
                _safe_metric(frame, secondary_currency, annualized_vol, include_provisional=True)
                if secondary_currency is not None
                else None
            ),
            secondary_label=secondary_currency,
            value_kind="percent",
        ),
        PerformanceSummaryCard(
            label="Since inception Sharpe",
            primary_value=sharpe_ratio(frame, primary_currency, include_provisional=True),
            secondary_value=(
                _safe_metric(frame, secondary_currency, sharpe_ratio, include_provisional=True)
                if secondary_currency is not None
                else None
            ),
            secondary_label=secondary_currency,
            value_kind="ratio",
        ),
    ]
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
    yearly_rows = build_yearly_metric_rows(
        frame,
        primary_currency=primary_currency,
        secondary_currency=secondary_currency,
    )
    return PerformanceReportViewModel(
        as_of=as_of,
        primary_currency=primary_currency,
        secondary_currency=secondary_currency,
        primary_basis=primary_basis,
        summary_cards=summary_cards,
        chart_specs=build_performance_chart_specs(frame, primary_currency),
        horizon_rows=horizon_rows,
        yearly_rows=yearly_rows,
    )


def render_performance_assets() -> str:
    plotly_js = get_plotlyjs()
    plotly_loader = (
        "<script>"
        f"{plotly_js}"
        "</script>"
        if plotly_js.strip()
        else "<script src='https://cdn.plot.ly/plotly-2.35.2.min.js'></script>"
    )
    return (
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
    instance_id = f"perf-plot-{view_model.primary_currency.lower()}"
    overview_text = (
        f"Primary view uses <strong>{html.escape(view_model.primary_basis)}</strong> in {html.escape(view_model.primary_currency)}."
        if view_model.secondary_currency is None
        else (
            f"Primary view uses <strong>{html.escape(view_model.primary_basis)}</strong> in {html.escape(view_model.primary_currency)}. "
            f"Auxiliary returns show {html.escape(view_model.secondary_currency)}."
        )
    )
    chart_specs = json.dumps(view_model.chart_specs, separators=(",", ":"))
    return (
        "<section class='perf-tab'>"
        "<div class='card'>"
        "<h2>Performance Overview</h2>"
        f"<p>{overview_text}</p>"
        f"<div class='metrics'>{summary_cards}</div>"
        "</div>"
        "<div class='card'>"
        "<div class='perf-card-header'>"
        "<h2>Cumulative Performance And Drawdown</h2>"
        "<p>Shared x-axis, stacked for easier reading.</p>"
        "</div>"
        f"{_render_chart_tabs(instance_id)}"
        f"<div id='{instance_id}' class='perf-plot'></div>"
        "<script>"
        f"window.__marketHelperInitPerformanceTab('{instance_id}', {chart_specs}, 'percent', 'MTD');"
        "</script>"
        "</div>"
        "<div class='card'>"
        "<h2>Horizon Metrics</h2>"
        f"{horizon_table}"
        "</div>"
        "<div class='card'>"
        "<h2>Historical Years</h2>"
        f"{yearly_table}"
        "</div>"
        "</section>"
    )


def _safe_metric(history: pd.DataFrame, currency: str, func, **kwargs) -> float | None:
    try:
        value = func(history, currency, **kwargs)
    except Exception:
        return None
    if value is None:
        return None
    return float(value)


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
    layout = {
        "template": "plotly_white",
        "height": 520,
        "margin": {"l": 72, "r": 24, "t": 48, "b": 56},
        "paper_bgcolor": "#ffffff",
        "plot_bgcolor": "#ffffff",
        "title": {"text": f"{_DISPLAY_WINDOW_LABELS[window]} • {currency}"},
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
        ("percent", "%"),
        ("dollar", "$"),
    ]
    window_buttons = [
        ("MTD", "MTD"),
        ("YTD", "YTD"),
        ("1Y", "1Y"),
        ("FULL", "Full History"),
    ]
    return (
        "<div class='perf-controls'>"
        f"<div class='perf-control-row'>{_render_button_row(target_id, 'mode', mode_buttons, 'percent')}</div>"
        f"<div class='perf-control-row'>{_render_button_row(target_id, 'window', window_buttons, 'MTD')}</div>"
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
            f"class='perf-subtab{' is-active' if is_active else ''}' "
            f"data-perf-target='{target_id}' "
            f"data-perf-group='{group}' "
            f"data-perf-value='{value}' "
            f"aria-selected='{'true' if is_active else 'false'}'>"
            f"{html.escape(label)}"
            "</button>"
        )
    return "".join(rendered)


def _render_summary_card(card: PerformanceSummaryCard) -> str:
    secondary = ""
    if card.secondary_label is not None:
        secondary = (
            f"<small>{html.escape(card.secondary_label)}: {_format_metric_value(card.secondary_value, card.value_kind)}</small>"
        )
    return (
        "<div class='metric'>"
        f"<span>{html.escape(card.label)}</span>"
        f"<strong>{_format_metric_value(card.primary_value, card.value_kind)}</strong>"
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


def _format_metric_value(value: float | str | None, kind: str) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, str):
        return html.escape(value)
    if kind == "percent":
        return f"{float(value):.2%}"
    if kind == "ratio":
        return f"{float(value):.2f}"
    return f"{float(value):,.2f}"


__all__ = [
    "PerformanceReportViewModel",
    "build_performance_chart_specs",
    "build_performance_report_view_model",
    "load_nav_cashflow_history_frame",
    "render_performance_assets",
    "render_performance_tab",
]
