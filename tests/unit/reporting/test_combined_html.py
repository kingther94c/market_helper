from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from market_helper.reporting.combined_html import build_combined_html_report
from market_helper.reporting.performance_html import (
    build_performance_report_view_model,
    render_performance_assets,
    render_performance_tab,
)


def test_render_performance_tab_contains_plots_and_tables() -> None:
    history = _demo_history_frame()

    view_model = build_performance_report_view_model(history, primary_currency="USD", secondary_currency=None)
    assets = render_performance_assets()
    rendered = assets + render_performance_tab(view_model)

    assert "Performance Overview" in rendered
    assert "Cumulative Performance And Drawdown" in rendered
    assert "Horizon Metrics" in rendered
    assert "Historical Years" in rendered
    assert "USD" in rendered
    assert "Full History" in rendered
    assert "Plotly.newPlot" in rendered
    assert "data-perf-group='mode'" in rendered
    assert "data-perf-group='window'" in rendered
    assert "Secondary Return" not in rendered
    assert "__marketHelperInitPerformanceTab" in assets
    assert ("cdn.plot.ly/plotly" in assets) or ("plotly.js v" in assets)


def test_build_combined_html_report_renders_both_tabs(tmp_path: Path) -> None:
    positions_csv = tmp_path / "positions.csv"
    positions_csv.write_text(
        "\n".join(
            [
                "as_of,account,internal_id,con_id,symbol,local_symbol,exchange,currency,source,quantity,avg_cost,latest_price,market_value,cost_basis,unrealized_pnl,weight",
                "2026-03-26T00:00:00+00:00,U1,STK:SPY:SMART,756733,SPY,SPY,ARCA,USD,ibkr,10,500,510,5100,5000,100,0.6",
                "2026-03-26T00:00:00+00:00,U1,FUT:ZN:CBOT,815824229,ZN,ZNM6,CBOT,USD,ibkr,1,110,111,111000,110000,1000,0.4",
            ]
        ),
        encoding="utf-8",
    )
    returns_json = tmp_path / "returns.json"
    returns_json.write_text(
        json.dumps(
            {
                "STK:SPY:SMART": [0.001 * ((idx % 7) - 3) for idx in range(90)],
                "FUT:ZN:CBOT": [0.0007 * ((idx % 5) - 2) for idx in range(90)],
            }
        ),
        encoding="utf-8",
    )
    proxy_json = tmp_path / "proxy.json"
    proxy_json.write_text(json.dumps({"VIX": 20.0, "MOVE": 120.0}), encoding="utf-8")
    regime_json = tmp_path / "regime.json"
    regime_json.write_text(
        json.dumps(
            [
                {
                    "as_of": "2026-03-26",
                    "regime": "Goldilocks Expansion",
                    "scores": {"VOL": 0.2, "CREDIT": 0.2, "RATES": -0.1, "GROWTH": 0.6, "TREND": 0.7, "STRESS": 0.2},
                    "inputs": {},
                    "flags": {},
                }
            ]
        ),
        encoding="utf-8",
    )
    performance_output_dir = tmp_path / "flex"
    performance_output_dir.mkdir()
    history_path = performance_output_dir / "nav_cashflow_history.feather"
    _demo_history_frame().to_feather(history_path)
    (performance_output_dir / "performance_report_20260331.csv").write_text(
        "\n".join(
            [
                "as_of,source_version,horizon,weighting,currency,dollar_pnl,return_pct",
                "2026-03-31,DailyNavRebuilt,YTD,time_weighted,USD,10,0.10",
            ]
        ),
        encoding="utf-8",
    )

    output_path = tmp_path / "combined_report.html"
    written = build_combined_html_report(
        positions_csv_path=positions_csv,
        output_path=output_path,
        performance_output_dir=performance_output_dir,
        returns_path=returns_json,
        proxy_path=proxy_json,
        regime_path=regime_json,
    )

    assert written == output_path
    rendered = output_path.read_text(encoding="utf-8")
    assert "Combined Portfolio Report" in rendered
    assert "data-tab-target='risk-tab'" in rendered
    assert "data-tab-target='performance-usd-tab'" in rendered
    assert "data-tab-target='performance-sgd-tab'" in rendered
    assert "Portfolio Risk Report" not in rendered
    assert "Performance Report (USD)" in rendered
    assert "Performance Report (SGD)" in rendered
    assert "Performance Overview" in rendered
    assert "Portfolio Summary" in rendered
    assert "Historical Years" in rendered
    assert "Goldilocks Expansion" in rendered
    assert "n/a" in rendered
    assert "Primary view uses <strong>TWR</strong> in USD." in rendered
    assert "Primary view uses <strong>TWR</strong> in SGD." in rendered
    assert "Plotly.newPlot" in rendered
    assert "data-perf-value='MTD'" in rendered
    assert "data-perf-value='FULL'" in rendered
    assert "Secondary Return" not in rendered


def _demo_history_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": pd.to_datetime(
                [
                    "2023-12-31",
                    "2024-12-31",
                    "2025-12-31",
                    "2026-01-31",
                    "2026-03-31",
                ]
            ),
            "nav_eod_usd": [90.0, 100.0, 120.0, 126.0, 132.3],
            "nav_eod_sgd": [117.0, 130.0, 156.0, 163.8, 171.99],
            "cashflow_usd": [0.0, 0.0, 0.0, 0.0, 0.0],
            "cashflow_sgd": [0.0, 0.0, 0.0, 0.0, 0.0],
            "fx_usdsgd_eod": [1.30, 1.30, 1.30, 1.30, 1.30],
            "pnl_amt_usd": [pd.NA, 10.0, 20.0, 6.0, 6.3],
            "pnl_amt_sgd": [pd.NA, 13.0, 26.0, 7.8, 8.19],
            "pnl_usd": [pd.NA, 0.1111111111, 0.20, 0.05, 0.05],
            "pnl_sgd": [pd.NA, 0.1111111111, 0.20, 0.05, 0.05],
            "is_final": [True, True, True, True, False],
            "source_kind": ["full", "full", "full", "latest", "latest"],
            "source_file": ["demo.xml"] * 5,
            "source_as_of": pd.to_datetime(["2026-03-31"] * 5),
        }
    )
