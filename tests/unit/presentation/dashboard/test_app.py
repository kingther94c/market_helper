from __future__ import annotations

from pathlib import Path

from market_helper.application.portfolio_monitor import (
    ArtifactMetadata,
    PortfolioMonitorActionService,
    PortfolioMonitorQueryService,
    PortfolioReportInputs,
    PortfolioReportSnapshot,
)
from market_helper.presentation.dashboard.app import (
    DEFAULT_PORTFOLIO_ROUTE,
    create_app,
    patch_nicegui_process_pool_setup,
    resolve_show_target,
)
from market_helper.reporting.performance_html import PerformanceReportViewModel, PerformanceSummaryCard
from market_helper.reporting.risk_html import (
    BreakdownRow,
    PolicyDriftRow,
    PortfolioRiskSummary,
    RiskMetricsRow,
    RiskReportViewModel,
)


class SlowQueryService(PortfolioMonitorQueryService):
    def resolve_inputs(self, inputs: PortfolioReportInputs | None = None) -> PortfolioReportInputs:
        return PortfolioReportInputs(positions_csv_path="positions.csv", performance_output_dir="flex")

    def load_snapshot(self, inputs: PortfolioReportInputs | None = None) -> PortfolioReportSnapshot:
        return _fake_snapshot()


def test_resolve_show_target_defaults_to_portfolio(monkeypatch) -> None:
    monkeypatch.delenv("MARKET_HELPER_UI_SHOW", raising=False)
    assert resolve_show_target() == DEFAULT_PORTFOLIO_ROUTE


def test_resolve_show_target_accepts_falsey_env(monkeypatch) -> None:
    monkeypatch.setenv("MARKET_HELPER_UI_SHOW", "0")
    assert resolve_show_target() is False


def test_create_app_registers_dashboard_routes() -> None:
    app = create_app(query_service=SlowQueryService(), action_service=PortfolioMonitorActionService())
    paths = {route.path for route in app.routes if hasattr(route, "path")}

    assert "/" in paths
    assert "/portfolio" in paths


def test_patch_nicegui_process_pool_setup_handles_permission_error(monkeypatch) -> None:
    import market_helper.presentation.dashboard.app as dashboard_app

    monkeypatch.setattr(dashboard_app, "_PROCESS_POOL_PATCHED", False)

    called = {"count": 0}

    def failing_setup() -> None:
        called["count"] += 1
        raise PermissionError("sandbox")

    monkeypatch.setattr(dashboard_app.nicegui_run, "setup", failing_setup)

    patch_nicegui_process_pool_setup()
    dashboard_app.nicegui_run.setup()

    assert called["count"] == 1


def _fake_snapshot() -> PortfolioReportSnapshot:
    performance = PerformanceReportViewModel(
        as_of="2026-04-08",
        primary_currency="USD",
        secondary_currency=None,
        primary_basis="TWR",
        summary_cards=[
            PerformanceSummaryCard(label="As of", primary_value="2026-04-08"),
            PerformanceSummaryCard(label="Since inception annualized return", primary_value=0.12, value_kind="percent"),
        ],
        chart_specs={
            "percent": {
                "MTD": {"data": [], "layout": {"title": {"text": "MTD"}}},
                "YTD": {"data": [], "layout": {"title": {"text": "YTD"}}},
                "1Y": {"data": [], "layout": {"title": {"text": "1Y"}}},
                "FULL": {"data": [], "layout": {"title": {"text": "FULL"}}},
            },
            "dollar": {
                "MTD": {"data": [], "layout": {"title": {"text": "MTD"}}},
                "YTD": {"data": [], "layout": {"title": {"text": "YTD"}}},
                "1Y": {"data": [], "layout": {"title": {"text": "1Y"}}},
                "FULL": {"data": [], "layout": {"title": {"text": "FULL"}}},
            },
        },
        horizon_rows=[],
        yearly_rows=[],
    )
    risk = RiskReportViewModel(
        as_of="2026-04-08",
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
                sparkline_3m_svg="",
                risk_contribution_historical=0.2,
                risk_contribution_estimated=0.2,
                mapping_status="mapped",
                report_scope="included",
                dir_exposure="L",
                eq_country="US",
                eq_sector="TECHNOLOGY",
                fi_tenor="",
                cm_sector="",
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
        country_breakdown=[BreakdownRow(bucket="US", bucket_label="", parent="EQ", exposure_usd=1750.0, gross_exposure_usd=1750.0, dollar_weight=1.0, risk_contribution_estimated=0.2)],
        sector_breakdown=[BreakdownRow(bucket="TECHNOLOGY", bucket_label="", parent="US_EQ", exposure_usd=1750.0, gross_exposure_usd=1750.0, dollar_weight=1.0, risk_contribution_estimated=0.2)],
        fi_tenor_breakdown=[],
        cm_sector_breakdown=[],
        policy_drift_asset_class=[PolicyDriftRow(bucket="EQ", scope="PORTFOLIO", current_weight=1.0, policy_weight=0.6, active_weight=0.4, current_risk_contribution=0.2)],
        policy_drift_country=[],
        policy_drift_sector=[],
        regime_summary=None,
        vol_method="geomean_1m_3m",
        inter_asset_corr="historical",
    )
    metadata = ArtifactMetadata(
        positions_csv_path=Path("positions.csv"),
        performance_output_dir=Path("flex"),
        performance_history_path=Path("flex/nav_cashflow_history.feather"),
        performance_report_csv_path=Path("flex/performance_report_20260408.csv"),
        returns_path=None,
        proxy_path=None,
        regime_path=None,
        security_reference_path=Path("data/artifacts/portfolio_monitor/security_reference.csv"),
        risk_config_path=Path("configs/portfolio_monitor/report_config.yaml"),
        allocation_policy_path=None,
        positions_as_of="2026-04-08T00:00:00+00:00",
    )
    return PortfolioReportSnapshot(
        as_of="2026-04-08T00:00:00+00:00",
        risk_view_model=risk,
        performance_usd_view_model=performance,
        performance_sgd_view_model=performance,
        artifact_metadata=metadata,
        warnings=[],
    )
