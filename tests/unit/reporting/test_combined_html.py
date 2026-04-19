from __future__ import annotations

from pathlib import Path

import pandas as pd

import market_helper.domain.portfolio_monitor.pipelines.generate_portfolio_report as pipeline
from market_helper.reporting.performance_html import (
    build_performance_chart_specs,
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


def test_generate_combined_html_report_builds_snapshot_request_with_performance_overrides(
    monkeypatch, tmp_path: Path
) -> None:
    captured: dict[str, object] = {}

    def fake_capture(request):
        captured["request"] = request
        request.output_path.write_text("<html>snapshot</html>", encoding="utf-8")
        return request.output_path

    monkeypatch.setattr(pipeline, "_capture_portfolio_snapshot", fake_capture)
    monkeypatch.setattr(pipeline, "sync_security_reference_csv", lambda reference_path: Path(reference_path))

    output_path = tmp_path / "combined_report.html"
    written = pipeline.generate_combined_html_report(
        positions_csv_path=tmp_path / "positions.csv",
        output_path=output_path,
        performance_output_dir=tmp_path / "flex",
        performance_history_path=tmp_path / "flex" / "nav_cashflow_history.feather",
        performance_report_csv_path=tmp_path / "flex" / "performance_report_20260331.csv",
        returns_path=tmp_path / "returns.json",
        proxy_path=tmp_path / "proxy.json",
        regime_path=tmp_path / "regime.json",
        security_reference_path=tmp_path / "security_reference.csv",
        risk_config_path=tmp_path / "report_config.yaml",
        allocation_policy_path=tmp_path / "allocation_policy.yaml",
        vol_method="forward_looking",
        inter_asset_corr="corr_0",
    )

    assert written == output_path
    request = captured["request"]
    assert request.query == "snapshot=1"
    assert request.output_path == output_path
    assert request.overrides == {
        "positions_csv_path": str(tmp_path / "positions.csv"),
        "security_reference_path": str(tmp_path / "security_reference.csv"),
        "vol_method": "forward_looking",
        "inter_asset_corr": "corr_0",
        "performance_history_path": str(tmp_path / "flex" / "nav_cashflow_history.feather"),
        "performance_output_dir": str(tmp_path / "flex"),
        "performance_report_csv_path": str(tmp_path / "flex" / "performance_report_20260331.csv"),
        "returns_path": str(tmp_path / "returns.json"),
        "proxy_path": str(tmp_path / "proxy.json"),
        "regime_path": str(tmp_path / "regime.json"),
        "risk_config_path": str(tmp_path / "report_config.yaml"),
        "allocation_policy_path": str(tmp_path / "allocation_policy.yaml"),
    }


def test_build_performance_chart_specs_uses_single_continuous_main_line_with_signed_shading() -> None:
    history = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-01-01", "2026-01-02", "2026-01-03", "2026-01-04"]),
            "nav_eod_usd": [100.0, 101.0, 99.0, 102.0],
            "nav_eod_sgd": [130.0, 131.3, 128.7, 132.6],
            "cashflow_usd": [0.0, 0.0, 0.0, 0.0],
            "cashflow_sgd": [0.0, 0.0, 0.0, 0.0],
            "fx_usdsgd_eod": [1.30, 1.30, 1.30, 1.30],
            "pnl_amt_usd": [0.0, 1.0, -2.0, 3.0],
            "pnl_amt_sgd": [0.0, 1.3, -2.6, 3.9],
            "pnl_usd": [0.0, 0.01, -0.0198019802, 0.0303030303],
            "pnl_sgd": [0.0, 0.01, -0.0198019802, 0.0303030303],
            "is_final": [True, True, True, True],
            "source_kind": ["latest"] * 4,
            "source_file": ["demo.xml"] * 4,
            "source_as_of": pd.to_datetime(["2026-01-04"] * 4),
        }
    )

    figure = build_performance_chart_specs(history, "USD")["percent"]["FULL"]
    traces = figure["data"]

    assert len(traces) == 4
    assert traces[0]["fillcolor"] == "rgba(22,163,74,0.18)"
    assert traces[1]["fillcolor"] == "rgba(220,38,38,0.18)"
    assert traces[2]["line"]["color"] == "#0f172a"
    assert all(value is not None for value in traces[2]["y"])


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
