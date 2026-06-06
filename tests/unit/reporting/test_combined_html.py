from __future__ import annotations

from pathlib import Path

import pandas as pd

from market_helper.application.portfolio_monitor.contracts import ArtifactMetadata, PortfolioReportData
from market_helper.domain.regime_detection.services.regime_report_provider import (
    RegimeArtifactState,
)
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


def test_performance_section_merges_usd_sgd_with_currency_toggle(tmp_path: Path) -> None:
    """The two Performance USD / SGD sections collapse into one section whose
    segmented control flips currency. Both currency bodies render (with their
    unique plot ids) and the SGD pane starts hidden."""
    from market_helper.reporting.portfolio_html import build_performance_section_body

    usd_vm = build_performance_report_view_model(
        _demo_history_frame(), primary_currency="USD", secondary_currency=None
    )
    sgd_vm = build_performance_report_view_model(
        _demo_history_frame(), primary_currency="SGD", secondary_currency=None
    )
    body = build_performance_section_body(usd_vm, sgd_vm)

    assert "perf-currency-switch" in body
    assert "data-perf-currency-btn='usd'" in body
    assert "data-perf-currency-btn='sgd'" in body
    assert "data-perf-currency='usd'" in body
    # SGD pane starts hidden; the toggle resizes it when first shown.
    assert "data-perf-currency='sgd' hidden" in body
    assert "__marketHelperResizePerformancePlots" in body
    # Both charts init (unique plot ids), so neither currency collides.
    assert "perf-plot-usd" in body
    assert "perf-plot-sgd" in body


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
        performance_report_csv_path=tmp_path / "flex" / "performance_report.csv",
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
    assert captured["inputs"].performance_report_csv_path == tmp_path / "flex" / "performance_report.csv"
    assert captured["inputs"].returns_path == tmp_path / "returns.json"
    assert captured["inputs"].proxy_path == tmp_path / "proxy.json"
    assert captured["inputs"].regime_path == tmp_path / "regime.json"
    assert captured["inputs"].risk_config_path == tmp_path / "report_config.yaml"
    assert captured["inputs"].allocation_policy_path == tmp_path / "allocation_policy.yaml"
    assert captured["inputs"].vol_method == "forward_looking"
    assert captured["inputs"].inter_asset_corr == "corr_0"
    mirrored_path = mirror_dir / "portfolio_dashboard_report.html"
    assert mirrored_path.exists()
    assert mirrored_path.read_text(encoding="utf-8") == "<html><body>report</body></html>"


def test_load_artifact_mirror_dir_joins_gdrive_root_with_portfolio_report(
    monkeypatch, tmp_path: Path
) -> None:
    """ROOT-based resolution: mirror dir is always <ROOT>/Portfolio_Report."""
    root = tmp_path / "005 Portfolio"
    monkeypatch.setenv(pipeline.MARKET_HELPER_GDRIVE_ROOT_ENV_VAR, str(root))

    resolved = pipeline._load_artifact_mirror_dir()
    assert resolved == root / pipeline.REPORT_SUBDIR
    assert resolved == root / "Portfolio_Report"


def test_load_artifact_mirror_dir_returns_none_when_root_unset(
    monkeypatch, tmp_path: Path
) -> None:
    """Without GDRIVE_ROOT, mirroring is silently skipped.

    The unit-test conftest already clears the env var + neutralizes the
    registry and OS-aware probe fallbacks for hermetic runs, so this test
    just confirms the resolver collapses to None when no source supplies a
    value.
    """
    monkeypatch.delenv(pipeline.MARKET_HELPER_GDRIVE_ROOT_ENV_VAR, raising=False)

    assert pipeline._load_artifact_mirror_dir() is None


def test_mirror_artifact_swallows_permission_error_when_path_unreachable(
    monkeypatch, tmp_path: Path, caplog
) -> None:
    """Stale per-user GDrive path (e.g. macOS path resolved on Windows) must
    not crash the report — the mirror step is best-effort."""
    unreachable_dir = tmp_path / "no-such-root"
    monkeypatch.setattr(
        pipeline, "_load_artifact_mirror_dir", lambda config_path=None: unreachable_dir
    )

    def _raise(*_args, **_kwargs):
        raise PermissionError(5, "Access is denied")

    monkeypatch.setattr(pipeline.Path, "mkdir", _raise)

    source = tmp_path / "report.html"
    source.write_text("<html>x</html>", encoding="utf-8")

    with caplog.at_level("WARNING"):
        result = pipeline._mirror_artifact_if_configured(
            source, target_name="portfolio_dashboard_report.html"
        )

    assert result is None
    assert any("Skipping artifact mirror" in rec.message for rec in caplog.records)


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
    # Overview is the new landing tab and renders first in the nav.
    assert "href='#overview'" in rendered or 'href="#overview"' in rendered
    assert ">Overview<" in rendered
    assert "overview-kpis" in rendered
    # YTD $ PNL (SGD) is exclusive to the Overview KPI grid (the sticky
    # topline strip keeps its 6-cell layout).
    assert "YTD $ PNL (SGD)" in rendered
    # The vol KPI was renamed Target Vol → Ex-ante Vol; the display name in
    # parens follows the resolved vol method (default ‟Fast" for the
    # geomean_1m_3m key).
    assert "Ex-ante Vol" in rendered
    assert "Target Vol" not in rendered
    # Performance USD / SGD are merged into one nav tab with a currency toggle.
    assert "href='#performance'" in rendered or 'href="#performance"' in rendered
    assert ">Performance<" in rendered
    assert "data-perf-currency-btn='usd'" in rendered
    assert "data-perf-currency-btn='sgd'" in rendered
    assert "Performance USD" not in rendered
    assert "Performance SGD" not in rendered
    assert "Risk" in rendered
    assert "Artifacts" in rendered
    assert "report-table" in rendered
    assert "/_nicegui/" not in rendered
    # With no FX hedge artifact (default sentinel), the Risk → FX section still
    # renders an actionable ‟not yet computed" card rather than vanishing.
    assert "id='fx-hedge'" in rendered
    assert "FX Hedging Advisor" in rendered
    assert "not yet computed" in rendered
    # When no regime artifact is available, the combined report still renders
    # the Regime section (now always present) with an actionable
    # ‟unavailable" card and a fallback ribbon pill — no silent omission.
    assert "regime-ribbon" in rendered
    assert "regime-ribbon__pill--unavailable" in rendered
    assert "Regime unavailable" in rendered
    # Regime now has its own top-level tab; the Overview shows only a compact
    # summary that deep-links to it. The full actionable unavailable explainer
    # card lives in the Regime tab (this fixture has no regime artifact).
    assert "href='#overview'" in rendered or 'href="#overview"' in rendered
    assert "href='#regime'" in rendered or 'href="#regime"' in rendered
    assert ">Regime<" in rendered
    assert "regime-unavailable" in rendered
    assert "Refresh Regime" in rendered
    # B1 — the Artifacts table no longer leaks raw `<span class='tone-muted'>`
    # markup that was getting double-escaped through `render_html_table`.
    assert "&lt;span class=&#x27;tone-muted&#x27;&gt;n/a&lt;/span&gt;" not in rendered
    assert "&lt;span class='tone-muted'&gt;" not in rendered
    # P1 — section-nav buttons get a visible focus ring.
    assert ".section-nav__button:focus-visible" in rendered


def test_render_portfolio_report_includes_fx_hedge_section_under_risk(tmp_path: Path) -> None:
    """A populated FX hedge state renders the Target FX Allocation block inside
    the Risk section, with the freshly-computed badge and conventions."""
    from dataclasses import replace as _replace
    from market_helper.domain.portfolio_monitor.services.fx_hedge_advisor import (
        FxHedgeAllocation,
        FxHedgeArtifactState,
        FxHedgeLeg,
    )

    leg = FxHedgeLeg(
        currency="EUR", instrument="EUR/USD (6E)", futures_root="6E",
        yahoo_symbol="EURUSD=X", beta=0.42, beta_std_error=0.05, t_stat=8.4,
        spot_usd_per_unit=1.08, target_notional_usd=4_200_000.0, contract_size=125_000,
        contract_size_currency="EUR", usd_notional_per_contract=135_000.0,
        target_contracts=31, realized_notional_usd=4_185_000.0,
        residual_notional_usd=15_000.0, on_rate=0.025,
        expected_annual_carry_usd=-75_330.0, expiry="2026-06-17",
    )
    allocation = FxHedgeAllocation(
        schema_version=1, run_date="2026-03-31", generated_at="2026-03-31T00:00:00+00:00",
        base_currency="SGD", hedge_target_pair="USD/SGD", hedge_target_yahoo="SGD=X",
        target_definition="r_tgt = Δln(USD per SGD); hedge long basket, short USD.",
        return_convention={"price_basis": "usd_per_unit", "frequency": "W-FRI",
                           "overlapping": False, "return_method": "log", "lookback_weeks": 156},
        data_source="yahoo_finance", hedge_notional_usd=10_000_000.0,
        hedge_notional_source="funded_aum_usd",
        data_window={"start": "2023-04-01", "end": "2026-03-27", "observations": 156},
        regression={"r_squared": 0.81, "adj_r_squared": 0.80, "alpha_weekly": 0.0,
                    "residual_vol_annualized": 0.028},
        legs=(leg,),
        totals={"target_notional_usd_gross": 4_200_000.0, "realized_notional_usd_gross": 4_185_000.0,
                "realized_notional_usd_net": 4_185_000.0, "rounding_residual_usd": 15_000.0,
                "hedge_quality_r_squared": 0.81, "statistical_unhedged_fraction": 0.19,
                "statistical_unhedged_notional_usd": 4_359_000.0,
                "expected_annual_carry_usd": -75_330.0, "expected_annual_carry_bps": -75.3},
        on_rates_as_of="2026-05-01", on_rates_source="configured", max_age_days=30,
    )
    state = FxHedgeArtifactState(
        state="ok", mode_used="refresh-if-stale", allocation=allocation,
        computed_fresh=True, age_days=0, last_run_at=None, error_message=None,
    )
    rendered = render_portfolio_report(_replace(_fake_report_data(tmp_path), fx_hedge_state=state))

    assert "id='fx-hedge'" in rendered
    assert "Target FX Allocation" in rendered
    assert "Freshly computed" in rendered
    assert "EUR/USD (6E)" in rendered
    assert "Long 31" in rendered
    assert "Conventions" in rendered
    # FX section CSS is injected into the document head.
    assert ".fx-badge--fresh" in rendered


def test_render_portfolio_report_includes_regime_section_when_view_model_present(tmp_path: Path) -> None:
    from dataclasses import replace as _replace
    from market_helper.reporting.regime_html import (
        RegimeHtmlAxisHistoryPoint,
        RegimeHtmlMethodRow,
        RegimeHtmlMethodVoteHistoryPoint,
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
        axes_history=[
            RegimeHtmlAxisHistoryPoint(as_of="2026-04-01", growth=0.4, inflation=-0.1),
            RegimeHtmlAxisHistoryPoint(as_of="2026-05-02", growth=0.62, inflation=-0.18),
        ],
        method_vote_history=[
            # Crisis-flagged session — under the old logic every method's cell
            # would be re-painted `regime-cell--crisis` while the title kept the
            # vote name (B2). After the fix the crisis flag does not override
            # the cell's per-method colour.
            RegimeHtmlMethodVoteHistoryPoint(
                as_of="2026-04-15",
                quadrants={"vix_move_quadrant": "Goldilocks"},
                crisis_flag=True,
            ),
            RegimeHtmlMethodVoteHistoryPoint(
                as_of="2026-05-02",
                quadrants={"vix_move_quadrant": "Goldilocks"},
                crisis_flag=False,
            ),
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
    )
    base = _fake_report_data(tmp_path)
    rendered = render_portfolio_report(_replace(base, regime_state=_ok_regime_state(regime_vm)))

    # Ribbon is sticky directly under the app-bar.
    assert "regime-ribbon" in rendered
    assert "regime-ribbon__pill" in rendered
    assert "Goldilocks" in rendered
    assert "Crisis off" in rendered
    assert "Vol mult" not in rendered
    # Regime now lives on its own tab; the deep visuals render there (not in
    # Overview), grouped under a chip sub-nav.
    assert "href='#overview'" in rendered or 'href="#overview"' in rendered
    assert "href='#regime'" in rendered or 'href="#regime"' in rendered
    assert "regime-subnav" in rendered
    assert "Factor Scores" in rendered
    assert "Crisis Intensity" in rendered
    assert "Method-Vote Heat Strip" in rendered
    assert "Regime Transitions" in rendered

    # B2 — crisis-flagged sessions no longer over-paint cells for unrelated
    # methods. The vix_move row's only crisis-flagged session voted Goldilocks,
    # so its cell must keep the goldilocks class with the matching title.
    assert (
        "<span class='method-strip__cell regime-cell--goldilocks' "
        "title='2026-04-15 · Goldilocks'></span>"
    ) in rendered

    # B3 — the Crisis Intensity chart pulls its `current` metadata from
    # `view_model.crisis_intensity` / `as_of`, not from the last filtered point.
    # With crisis_intensity=0.18 and as_of=2026-05-02, the chart strip should
    # mention 0.18 (and not the older 2026-03-20 transition date).
    assert "current 0.18" in rendered

    # P3 — when the regime view-model's as-of is fresh (same day as the report's
    # as-of), the `regime stale` tag must NOT appear.
    assert "regime stale" not in rendered


def test_regime_section_marks_stale_when_regime_as_of_lags_report(tmp_path: Path) -> None:
    """P3: regime view-model is more than a day older than the report → stale tag."""
    from dataclasses import replace as _replace
    from market_helper.application.portfolio_monitor.contracts import PortfolioReportData
    from market_helper.reporting.regime_html import (
        RegimeHtmlTimelineRow,
        RegimeHtmlViewModel,
    )

    regime_vm = RegimeHtmlViewModel(
        schema="regime-multi-v1",
        as_of="2026-04-20T00:00:00+00:00",  # ~12 days behind the report
        regime="Goldilocks",
        scores={"GROWTH": 0.4, "INFLATION": -0.1},
        method_agreement=0.8,
        crisis_flag=False,
        crisis_intensity=0.1,
        duration_days=14,
        methods=[],
        timeline=[
            RegimeHtmlTimelineRow(
                as_of="2026-04-20T00:00:00+00:00",
                regime="Goldilocks",
                method_agreement=0.8,
                crisis_flag=False,
                crisis_intensity=0.1,
                duration_days=14,
            )
        ],
        regime_counts={"Goldilocks": 5},
    )

    base = _fake_report_data(tmp_path)
    # The fixture uses `2026-03-31T00:00:00+00:00` — but for this test we want
    # the report `as_of` to be after the regime as-of. Replace it.
    fresh = _replace(
        base,
        as_of="2026-05-02T00:00:00+00:00",
        regime_state=_ok_regime_state(regime_vm),
    )
    rendered = render_portfolio_report(fresh)

    # Stale tag is present (regime as-of > 1d behind report).
    assert "regime stale" in rendered
    assert "regime-stale-tag" in rendered


def test_overview_section_renders_kpi_grid_and_regime_summary(tmp_path: Path) -> None:
    """Overview is the landing tab — headline KPIs (including the YTD $ PNL SGD
    that's exclusive to it) plus a *compact* regime summary that deep-links to
    the dedicated Regime tab (the deep panels live there, not here)."""
    from market_helper.reporting.portfolio_html import build_overview_section_body

    base = _fake_report_data(tmp_path)
    body = build_overview_section_body(base)

    # Overview-exclusive KPI: dollar-denominated YTD P&L in SGD.
    assert "overview-kpis" in body
    assert "YTD $ PNL (SGD)" in body
    # Vol KPI uses the Ex-ante naming and parameterises the method.
    assert "Ex-ante Vol" in body
    assert "Target Vol" not in body
    # The fixture sets `vol_method="geomean_1m_3m"` → display label "Fast".
    assert "Ex-ante Vol (Fast)" in body
    # Regime summary deep-links to the Regime tab. This fixture has no regime
    # artifact, so the compact unavailable summary is shown here — but the
    # *full* explainer card (regime-unavailable) lives on the Regime tab.
    assert "overview-regime" in body
    assert "regime-summary--unavailable" in body
    assert "Regime unavailable" in body
    assert "href='#regime'" in body
    assert "regime-unavailable" not in body


def test_overview_kpi_uses_dynamic_vol_method_label(tmp_path: Path) -> None:
    """The Overview Ex-ante Vol KPI label tracks the resolved vol_method on the
    risk view-model rather than hard-coding the geomean_1m_3m / Fast pairing.

    (The standalone topline strip was retired — its single KPI row duplicated
    the Overview grid, which now owns the headline KPIs.)"""
    from dataclasses import replace as _replace
    from market_helper.reporting.portfolio_html import build_overview_section_body

    base = _fake_report_data(tmp_path)
    long_term = _replace(base.risk_view_model, vol_method="5y_realized")
    swapped = _replace(base, risk_view_model=long_term)

    body = build_overview_section_body(swapped)

    assert "Ex-ante Vol (Long-Term)" in body
    assert "Ex-ante Vol (Fast)" not in body
    assert "Target Vol" not in body


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


def _ok_regime_state(view_model) -> RegimeArtifactState:
    """Wrap a fully-populated view-model in an ok-state for renderer tests."""
    return RegimeArtifactState(
        state="ok",
        mode_used="cached",
        view_model=view_model,
        regime_as_of=view_model.as_of,
        last_run_at=None,
        error_message=None,
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
            performance_report_csv_path=tmp_path / "flex" / "performance_report.csv",
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
