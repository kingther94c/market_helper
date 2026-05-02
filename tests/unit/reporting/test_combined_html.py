from __future__ import annotations

from pathlib import Path

import pandas as pd

from market_helper.application.portfolio_monitor.contracts import ArtifactMetadata, PortfolioReportData
import market_helper.domain.portfolio_monitor.pipelines.generate_portfolio_report as pipeline
from market_helper.reporting.performance_html import (
    build_performance_chart_specs,
    build_performance_report_view_model,
    render_performance_assets,
    render_performance_tab,
)
from market_helper.reporting.portfolio_html import render_portfolio_report
from market_helper.reporting.risk_html import (
    PortfolioRiskSummary,
    RiskMetricsRow,
    RiskReportViewModel,
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


def test_generate_combined_html_report_writes_direct_html_and_mirrors_artifact(
    monkeypatch, tmp_path: Path
) -> None:
    mirror_dir = tmp_path / "google-drive"
    fake_report_data = _fake_report_data(tmp_path)
    captured: dict[str, object] = {}

    def fake_load_report_data(inputs):
        captured["inputs"] = inputs
        return fake_report_data

    def fake_write_report(report_data, output_path):
        captured["report_data"] = report_data
        output_path = Path(output_path)
        output_path.write_text("<html><body>report</body></html>", encoding="utf-8")
        return output_path

    monkeypatch.setattr(pipeline, "_load_portfolio_report_data", fake_load_report_data)
    monkeypatch.setattr(pipeline, "write_portfolio_report", fake_write_report)
    monkeypatch.setattr(pipeline, "sync_security_reference_csv", lambda reference_path: Path(reference_path))
    monkeypatch.setattr(pipeline, "_load_artifact_mirror_dir", lambda config_path=None: mirror_dir)

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
    assert captured["report_data"] == fake_report_data
    assert captured["inputs"].positions_csv_path == tmp_path / "positions.csv"
    assert captured["inputs"].performance_history_path == tmp_path / "flex" / "nav_cashflow_history.feather"
    assert captured["inputs"].performance_output_dir == tmp_path / "flex"
    assert captured["inputs"].performance_report_csv_path == tmp_path / "flex" / "performance_report_20260331.csv"
    assert captured["inputs"].returns_path == tmp_path / "returns.json"
    assert captured["inputs"].proxy_path == tmp_path / "proxy.json"
    assert captured["inputs"].regime_path == tmp_path / "regime.json"
    assert captured["inputs"].risk_config_path == tmp_path / "report_config.yaml"
    assert captured["inputs"].allocation_policy_path == tmp_path / "allocation_policy.yaml"
    assert captured["inputs"].vol_method == "forward_looking"
    assert captured["inputs"].inter_asset_corr == "corr_0"
    mirrored_path = mirror_dir / "portfolio_combined_report.html"
    assert mirrored_path.exists()
    assert mirrored_path.read_text(encoding="utf-8") == "<html><body>report</body></html>"


def test_generate_combined_html_report_uses_configured_google_drive_mirror_dir(
    monkeypatch, tmp_path: Path
) -> None:
    config_path = tmp_path / "report_config.yaml"
    config_path.write_text(
        "artifact_mirror:\n"
        f"  google_drive_dir: {str(tmp_path / 'google-drive')!r}\n",
        encoding="utf-8",
    )

    fake_report_data = _fake_report_data(tmp_path)

    monkeypatch.setattr(pipeline, "_load_portfolio_report_data", lambda inputs: fake_report_data)

    def fake_write(report_data, output_path):
        output_path = Path(output_path)
        output_path.write_text("<html>report</html>", encoding="utf-8")
        return output_path

    monkeypatch.setattr(pipeline, "write_portfolio_report", fake_write)
    monkeypatch.setattr(pipeline, "sync_security_reference_csv", lambda reference_path: Path(reference_path))

    pipeline.generate_combined_html_report(
        positions_csv_path=tmp_path / "positions.csv",
        output_path=tmp_path / "combined_report.html",
        security_reference_path=tmp_path / "security_reference.csv",
        risk_config_path=config_path,
    )

    mirrored_path = tmp_path / "google-drive" / "portfolio_combined_report.html"
    assert mirrored_path.exists()
    assert mirrored_path.read_text(encoding="utf-8") == "<html>report</html>"


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


def test_render_portfolio_report_builds_html_shell_without_nicegui_refs(tmp_path: Path) -> None:
    rendered = render_portfolio_report(_fake_report_data(tmp_path))

    assert "<!doctype html>" in rendered.lower()
    # P4 redesign: brand is rendered in the sticky `.app-bar`.
    assert "Market Helper" in rendered
    assert "app-bar" in rendered
    # Section nav uses hash-routed anchors, not the legacy `<button>` toggle.
    assert "section-nav" in rendered
    assert "href='#performance-usd'" in rendered or 'href="#performance-usd"' in rendered
    assert "Performance USD" in rendered
    assert "Risk" in rendered
    assert "Artifacts" in rendered
    assert "report-table" in rendered
    assert "/_nicegui/" not in rendered
    # When no regime artifact is provided, the combined report omits the Regime
    # section + ribbon entirely (no empty chrome).
    assert "regime-ribbon" not in rendered
    assert "href='#regime'" not in rendered and 'href="#regime"' not in rendered


def test_render_portfolio_report_includes_regime_section_when_view_model_present(tmp_path: Path) -> None:
    from dataclasses import replace as _replace
    from market_helper.reporting.regime_html import (
        RegimeHtmlAxisHistoryPoint,
        RegimeHtmlMethodRow,
        RegimeHtmlMethodVoteHistoryPoint,
        RegimeHtmlPolicySummary,
        RegimeHtmlTimelineRow,
        RegimeHtmlTransitionEvent,
        RegimeHtmlViewModel,
    )

    regime_vm = RegimeHtmlViewModel(
        schema="regime-multi-v1",
        as_of="2026-05-02",
        regime="Goldilocks",
        scores={"GROWTH": 0.62, "INFLATION": -0.18},
        method_agreement=0.83,
        crisis_flag=False,
        crisis_intensity=0.18,
        duration_days=42,
        methods=[RegimeHtmlMethodRow("vix_move_quadrant", "Goldilocks", "low-vol risk-on")],
        timeline=[
            RegimeHtmlTimelineRow(
                as_of="2026-05-02",
                regime="Goldilocks",
                method_agreement=0.83,
                crisis_flag=False,
                crisis_intensity=0.18,
                duration_days=42,
            )
        ],
        regime_counts={"Goldilocks": 42, "Slowdown": 9},
        policy=RegimeHtmlPolicySummary(
            vol_multiplier=0.95,
            asset_class_targets={"EQ": 0.55, "FI": 0.30},
            notes="Goldilocks tilt",
        ),
        axes_history=[
            RegimeHtmlAxisHistoryPoint(as_of="2026-04-01", growth=0.4, inflation=-0.1),
            RegimeHtmlAxisHistoryPoint(as_of="2026-05-02", growth=0.62, inflation=-0.18),
        ],
        method_vote_history=[
            RegimeHtmlMethodVoteHistoryPoint(
                as_of="2026-05-02",
                quadrants={"vix_move_quadrant": "Goldilocks"},
                crisis_flag=False,
            )
        ],
        transitions=[
            RegimeHtmlTransitionEvent(
                as_of="2026-03-20",
                from_regime="Slowdown",
                to_regime="Goldilocks",
                crisis_intensity=None,
                duration_days=42,
            )
        ],
        vol_multiplier=0.95,
    )
    base = _fake_report_data(tmp_path)
    rendered = render_portfolio_report(_replace(base, regime_view_model=regime_vm))

    # Ribbon is sticky directly under the app-bar.
    assert "regime-ribbon" in rendered
    assert "regime-ribbon__pill" in rendered
    assert "Goldilocks" in rendered
    assert "Crisis off" in rendered
    assert "0.95×" in rendered  # vol multiplier
    # Regime section is reachable via deep-link and renders all four new visuals.
    assert "href='#regime'" in rendered or 'href="#regime"' in rendered
    assert "Factor Scores" in rendered
    assert "Crisis Intensity" in rendered
    assert "Method-Vote Heat Strip" in rendered
    assert "Regime Transitions" in rendered


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


def _fake_report_data(tmp_path: Path) -> PortfolioReportData:
    performance = build_performance_report_view_model(
        _demo_history_frame(),
        primary_currency="USD",
        secondary_currency=None,
    )
    risk = RiskReportViewModel(
        as_of="2026-03-31",
        risk_rows=[
            RiskMetricsRow(
                internal_id="STK:AAPL:SMART",
                display_ticker="AAPL",
                display_name="Apple Inc.",
                symbol="AAPL",
                canonical_symbol="AAPL",
                account="U1",
                asset_class="EQ",
                category="EQ",
                instrument_type="Stock",
                quantity=10.0,
                multiplier=1.0,
                market_value=1750.0,
                exposure_usd=1750.0,
                gross_exposure_usd=1750.0,
                weight=1.0,
                dollar_weight=1.0,
                duration=None,
                vol_geomean_1m_3m=0.2,
                vol_5y_realized=0.18,
                vol_ewma=0.22,
                vol_forward_looking=0.24,
                sparkline_3m_svg="<svg></svg>",
                risk_contribution_historical=0.2,
                risk_contribution_estimated=0.2,
                risk_contribution_geomean_1m_3m=0.2,
                risk_contribution_5y_realized=0.18,
                risk_contribution_ewma=0.22,
                risk_contribution_forward_looking=0.24,
                mapping_status="mapped",
                report_scope="included",
                dir_exposure="L",
                eq_country="US",
                eq_sector_proxy="TECH",
                fi_tenor="",
            )
        ],
        summary=PortfolioRiskSummary(
            portfolio_vol_geomean_1m_3m=0.2,
            portfolio_vol_5y_realized=0.18,
            portfolio_vol_ewma=0.22,
            portfolio_vol_forward_looking=0.24,
            funded_aum_usd=1750.0,
            funded_aum_sgd=2275.0,
            gross_exposure=1750.0,
            net_exposure=1750.0,
            mapped_positions=1,
            total_positions=1,
        ),
        allocation_summary=[],
        country_breakdown=[],
        sector_breakdown=[],
        fi_tenor_breakdown=[],
        policy_drift_asset_class=[],
        policy_drift_country=[],
        policy_drift_sector=[],
        regime_summary=None,
        vol_method="geomean_1m_3m",
        inter_asset_corr="historical",
        portfolio_vol_matrix={
            "historical": {"geomean_1m_3m": 0.2, "5y_realized": 0.18, "forward_looking": 0.24},
            "corr_0": {"geomean_1m_3m": 0.15, "5y_realized": 0.14, "forward_looking": 0.2},
            "corr_1": {"geomean_1m_3m": 0.27, "5y_realized": 0.25, "forward_looking": 0.3},
        },
    )
    return PortfolioReportData(
        as_of="2026-03-31T00:00:00+00:00",
        risk_view_model=risk,
        performance_usd_view_model=performance,
        performance_sgd_view_model=performance,
        artifact_metadata=ArtifactMetadata(
            positions_csv_path=tmp_path / "positions.csv",
            performance_output_dir=tmp_path / "flex",
            performance_history_path=tmp_path / "flex" / "nav_cashflow_history.feather",
            performance_report_csv_path=tmp_path / "flex" / "performance_report_20260331.csv",
            returns_path=tmp_path / "returns.json",
            proxy_path=tmp_path / "proxy.json",
            regime_path=tmp_path / "regime.json",
            security_reference_path=tmp_path / "security_reference.csv",
            risk_config_path=tmp_path / "report_config.yaml",
            allocation_policy_path=tmp_path / "allocation_policy.yaml",
            positions_as_of="2026-03-31T00:00:00+00:00",
        ),
        warnings=[],
    )
