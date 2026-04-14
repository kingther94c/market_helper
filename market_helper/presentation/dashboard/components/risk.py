from __future__ import annotations

from typing import Any

from nicegui import ui

from market_helper.reporting.risk_html import BreakdownRow, PolicyDriftRow

from .common import render_table


def build_policy_drift_figure(rows: list[PolicyDriftRow]) -> dict[str, Any]:
    if not rows:
        return _empty_figure("No data")
    return {
        "data": [
            {
                "type": "bar",
                "x": [row.bucket for row in rows],
                "y": [row.active_weight for row in rows],
                "marker": {
                    "color": ["#16a34a" if row.active_weight >= 0 else "#dc2626" for row in rows],
                },
                "hovertemplate": "%{x}<br>%{y:.2%}<extra></extra>",
            }
        ],
        "layout": {
            "template": "plotly_white",
            "height": 320,
            "margin": {"l": 48, "r": 16, "t": 24, "b": 56},
            "yaxis": {"tickformat": ".0%", "title": "Active Weight"},
            "xaxis": {"tickangle": -25},
        },
        "config": {"displayModeBar": False, "responsive": True},
    }


def build_breakdown_figure(rows: list[BreakdownRow], *, title: str) -> dict[str, Any]:
    if not rows:
        return _empty_figure("No data")
    return {
        "data": [
            {
                "type": "bar",
                "x": [row.bucket for row in rows],
                "y": [row.dollar_weight for row in rows],
                "marker": {"color": "#2563eb"},
                "hovertemplate": "%{x}<br>%{y:.2%}<extra></extra>",
            }
        ],
        "layout": {
            "template": "plotly_white",
            "height": 320,
            "margin": {"l": 48, "r": 16, "t": 24, "b": 56},
            "title": {"text": title},
            "yaxis": {"tickformat": ".0%", "title": "Dollar Weight"},
            "xaxis": {"tickangle": -25},
        },
        "config": {"displayModeBar": False, "responsive": True},
    }


def render_risk_chart_block(
    *,
    title: str,
    figure: dict[str, Any],
    columns: list[dict[str, str]],
    rows: list[dict[str, str]],
    row_key: str,
    empty_message: str = "No data",
) -> None:
    with ui.card().classes("grow basis-[520px] pm-card p-4"):
        ui.label(title).classes("text-h6")
        if rows:
            ui.plotly(figure).classes("w-full h-[360px]")
        else:
            ui.label(empty_message).classes("text-body2 pm-muted")
        render_table(columns=columns, rows=rows, row_key=row_key)


def _empty_figure(message: str) -> dict[str, Any]:
    return {
        "data": [],
        "layout": {
            "template": "plotly_white",
            "annotations": [{"text": message, "xref": "paper", "yref": "paper", "x": 0.5, "y": 0.5, "showarrow": False}],
            "margin": {"l": 32, "r": 16, "t": 24, "b": 24},
        },
        "config": {"displayModeBar": False, "responsive": True},
    }
