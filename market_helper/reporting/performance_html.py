from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import csv
import html

import pandas as pd

from market_helper.domain.portfolio_monitor.services.performance_analytics import (
    PerformanceMetricRow,
    annualized_return,
    annualized_vol,
    build_window_metric_row,
    build_yearly_metric_rows,
    drawdown_plot_frame,
    load_performance_history_frame,
    performance_plot_frame,
    sharpe_ratio,
)


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
    cumulative_plot: pd.DataFrame
    drawdown_plot: pd.DataFrame
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
    if frame.empty:
        as_of = "n/a"
    else:
        as_of = pd.Timestamp(frame["date"].max()).date().isoformat()

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
        for window in ("MTD", "YTD", "1Y", "3Y", "5Y")
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
        cumulative_plot=performance_plot_frame(frame, primary_currency, include_provisional=True),
        drawdown_plot=drawdown_plot_frame(frame, primary_currency, include_provisional=True),
        horizon_rows=horizon_rows,
        yearly_rows=yearly_rows,
    )


def render_performance_tab(view_model: PerformanceReportViewModel) -> str:
    summary_cards = "\n".join(_render_summary_card(card) for card in view_model.summary_cards)
    horizon_rows = _render_metric_rows(
        view_model.horizon_rows,
        secondary_currency=view_model.secondary_currency,
    )
    yearly_rows = _render_metric_rows(
        view_model.yearly_rows,
        secondary_currency=view_model.secondary_currency,
    )
    cumulative_svg = _render_time_series_svg(
        view_model.cumulative_plot,
        value_column="level",
        css_class="perf-chart-svg perf-chart-svg-positive",
        label=f"{view_model.primary_currency} cumulative performance",
    )
    drawdown_svg = _render_time_series_svg(
        view_model.drawdown_plot,
        value_column="drawdown",
        css_class="perf-chart-svg perf-chart-svg-drawdown",
        label=f"{view_model.primary_currency} drawdown",
    )
    overview_text = (
        f"Primary view uses <strong>{html.escape(view_model.primary_basis)}</strong> in {html.escape(view_model.primary_currency)}."
        if view_model.secondary_currency is None
        else (
            f"Primary view uses <strong>{html.escape(view_model.primary_basis)}</strong> in {html.escape(view_model.primary_currency)}. "
            f"Auxiliary returns show {html.escape(view_model.secondary_currency)}."
        )
    )
    return (
        "<section class='perf-tab'>"
        "<div class='card'>"
        "<h2>Performance Overview</h2>"
        f"<p>{overview_text}</p>"
        f"<div class='metrics'>{summary_cards}</div>"
        "</div>"
        "<div class='card'>"
        "<h2>PnL / Cumulative Performance</h2>"
        f"{cumulative_svg}"
        "</div>"
        "<div class='card'>"
        "<h2>Drawdown</h2>"
        f"{drawdown_svg}"
        "</div>"
        "<div class='card'>"
        "<h2>Horizon Metrics</h2>"
        "<table>"
        "<thead><tr><th>Window</th><th class='num'>TWR Return</th><th class='num'>MWR Return</th><th class='num'>Ann Return</th><th class='num'>Ann Vol</th><th class='num'>Sharpe</th><th class='num'>Max Drawdown</th><th>Secondary Return</th></tr></thead>"
        f"<tbody>{horizon_rows}</tbody>"
        "</table>"
        "</div>"
        "<div class='card'>"
        "<h2>Historical Years</h2>"
        "<table>"
        "<thead><tr><th>Year</th><th class='num'>TWR Return</th><th class='num'>MWR Return</th><th class='num'>Ann Vol</th><th class='num'>Sharpe</th><th class='num'>Max Drawdown</th><th>Secondary Return</th></tr></thead>"
        f"<tbody>{yearly_rows}</tbody>"
        "</table>"
        "</div>"
        "</section>"
    )


def _safe_metric(history: pd.DataFrame, currency: str, func, **kwargs) -> float | None:
    try:
        return float(func(history, currency, **kwargs))
    except Exception:
        return None


def _load_report_rows(report_csv_path: str | Path | None) -> list[dict[str, str]]:
    if report_csv_path is None:
        return []
    path = Path(report_csv_path)
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


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


def _render_metric_rows(rows: list[PerformanceMetricRow], *, secondary_currency: str | None) -> str:
    if not rows:
        return "<tr><td colspan='8'>No data</td></tr>"
    return "\n".join(
        (
            "<tr>"
            f"<td>{html.escape(row.label)}</td>"
            f"<td class='num'>{_format_metric_value(row.twr_return, 'percent')}</td>"
            f"<td class='num'>{_format_metric_value(row.mwr_return, 'percent')}</td>"
            f"<td class='num'>{_format_metric_value(row.annualized_return, 'percent')}</td>"
            f"<td class='num'>{_format_metric_value(row.annualized_vol, 'percent')}</td>"
            f"<td class='num'>{_format_metric_value(row.sharpe_ratio, 'ratio')}</td>"
            f"<td class='num'>{_format_metric_value(row.max_drawdown, 'percent')}</td>"
            f"<td>{_render_secondary_return_cell(row, secondary_currency)}</td>"
            "</tr>"
        )
        for row in rows
    )


def _render_secondary_return_cell(row: PerformanceMetricRow, secondary_currency: str | None) -> str:
    if secondary_currency is None:
        return "n/a"
    return (
        f"{html.escape(secondary_currency)} TWR {_format_metric_value(row.secondary_twr_return, 'percent')} / "
        f"MWR {_format_metric_value(row.secondary_mwr_return, 'percent')}"
    )


def _render_time_series_svg(
    frame: pd.DataFrame,
    *,
    value_column: str,
    css_class: str,
    label: str,
) -> str:
    if frame.empty or value_column not in frame.columns:
        return "<p>No data</p>"
    values = pd.to_numeric(frame[value_column], errors="coerce").dropna()
    if values.empty:
        return "<p>No data</p>"
    width = 720.0
    height = 220.0
    min_value = float(values.min())
    max_value = float(values.max())
    if abs(max_value - min_value) <= 1e-12:
        min_value -= 1.0
        max_value += 1.0
    points: list[str] = []
    for idx, value in enumerate(values.tolist()):
        x = 0.0 if len(values) == 1 else (idx / (len(values) - 1)) * width
        y = height - (((float(value) - min_value) / (max_value - min_value)) * height)
        points.append(f"{x:.2f},{y:.2f}")
    return (
        f"<svg class='{css_class}' viewBox='0 0 {int(width)} {int(height)}' preserveAspectRatio='none' role='img' "
        f"aria-label='{html.escape(label)}'>"
        f"<polyline points='{' '.join(points)}'></polyline>"
        "</svg>"
    )


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
    "build_performance_report_view_model",
    "load_performance_history_frame",
    "render_performance_tab",
]
