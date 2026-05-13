from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

from market_helper.application.portfolio_monitor import (
    EtfSectorSyncInputs,
    GenerateCombinedReportInputs,
    InMemoryUiProgressSink,
    LivePortfolioRefreshInputs,
    PortfolioMonitorActionService,
    PortfolioMonitorQueryService,
    PortfolioReportInputs,
    RegimeReportRefreshInputs,
    RegimeReportRunInputs,
)
from market_helper.application.portfolio_monitor import services as app_services


@dataclass(frozen=True)
class _FakeRiskViewModel:
    as_of: str


def test_query_service_load_report_data_resolves_expected_artifacts(tmp_path: Path) -> None:
    positions_csv = _write_positions_csv(tmp_path / "positions.csv")
    returns_json = _write_returns_json(tmp_path / "returns.json")
    proxy_json = _write_proxy_json(tmp_path / "proxy.json")
    performance_output_dir = tmp_path / "flex"
    performance_output_dir.mkdir()
    _demo_history_frame().to_feather(performance_output_dir / "nav_cashflow_history.feather")
    (performance_output_dir / "performance_report_20260408.csv").write_text(
        "\n".join(
            [
                "as_of,source_version,horizon,weighting,currency,dollar_pnl,return_pct",
                "2026-04-08,DailyNavRebuilt,YTD,time_weighted,USD,10,0.10",
            ]
        ),
        encoding="utf-8",
    )

    service = PortfolioMonitorQueryService()
    report_data = service.load_report_data(
        PortfolioReportInputs(
            positions_csv_path=positions_csv,
            performance_output_dir=performance_output_dir,
            returns_path=returns_json,
            proxy_path=proxy_json,
        )
    )

    assert report_data.as_of == "2026-04-08T00:00:00+00:00"
    assert report_data.artifact_metadata.positions_csv_path == positions_csv
    assert report_data.artifact_metadata.performance_output_dir == performance_output_dir
    assert report_data.artifact_metadata.performance_report_csv_path == performance_output_dir / "performance_report_20260408.csv"
    assert report_data.performance_usd_view_model.as_of == "2026-04-08"
    assert report_data.performance_sgd_view_model.as_of == "2026-04-08"
    assert report_data.warnings == []

    artifact = service.resolve_report_artifact(
        inputs=PortfolioReportInputs(
            positions_csv_path=positions_csv,
            performance_output_dir=performance_output_dir,
            returns_path=returns_json,
            proxy_path=proxy_json,
        ),
        report_data=report_data,
    )
    assert artifact.output_path == app_services.DEFAULT_COMBINED_REPORT_PATH
    assert artifact.exists is artifact.output_path.exists()


def test_query_service_warns_when_performance_artifacts_are_missing(tmp_path: Path) -> None:
    positions_csv = _write_positions_csv(tmp_path / "positions.csv")
    returns_json = _write_returns_json(tmp_path / "returns.json")
    proxy_json = _write_proxy_json(tmp_path / "proxy.json")

    service = PortfolioMonitorQueryService()
    report_data = service.load_report_data(
        PortfolioReportInputs(
            positions_csv_path=positions_csv,
            performance_output_dir=tmp_path / "missing_flex",
            returns_path=returns_json,
            proxy_path=proxy_json,
        )
    )

    assert report_data.as_of == "2026-04-08T00:00:00+00:00"
    assert any("Performance history file not found" in warning for warning in report_data.warnings)
    assert any("Dated performance report CSV is missing" in warning for warning in report_data.warnings)
    assert report_data.performance_usd_view_model.as_of == "n/a"


def test_generate_combined_inputs_default_to_existing_regime_artifact(
    monkeypatch,
    tmp_path: Path,
) -> None:
    regime_path = tmp_path / "regime_snapshots.json"
    regime_path.write_text("[]", encoding="utf-8")
    monkeypatch.setattr(app_services, "DEFAULT_REGIME_ARTIFACT_PATH", regime_path)

    service = PortfolioMonitorQueryService()

    resolved = service.resolve_inputs(
        GenerateCombinedReportInputs(positions_csv_path=tmp_path / "positions.csv")
    )

    assert resolved.regime_path == regime_path


def test_plain_report_inputs_do_not_implicitly_load_default_regime(
    monkeypatch,
    tmp_path: Path,
) -> None:
    regime_path = tmp_path / "regime_snapshots.json"
    regime_path.write_text("[]", encoding="utf-8")
    monkeypatch.setattr(app_services, "DEFAULT_REGIME_ARTIFACT_PATH", regime_path)

    service = PortfolioMonitorQueryService()

    resolved = service.resolve_inputs(
        PortfolioReportInputs(positions_csv_path=tmp_path / "positions.csv")
    )

    assert resolved.regime_path is None


def test_report_data_passes_regime_into_risk_view_model(
    monkeypatch,
    tmp_path: Path,
) -> None:
    positions_csv = _write_positions_csv(tmp_path / "positions.csv")
    regime_path = tmp_path / "regime.json"
    regime_path.write_text("[]", encoding="utf-8")
    captured: dict[str, object] = {}

    def fake_build_risk_report_view_model(**kwargs):
        captured.update(kwargs)
        return _FakeRiskViewModel(as_of="2026-04-08")

    def fake_load_regime_view_model(**kwargs):
        captured["loaded_regime_path"] = kwargs["regime_path"]
        return SimpleNamespace(regime="Goldilocks")

    fake_perf_entry = app_services._PerformanceCacheEntry(
        date=app_services.datetime.date.today(),
        history_path=None,
        report_csv_path=None,
        history_mtime=None,
        usd_view_model=SimpleNamespace(as_of="2026-04-08"),
        sgd_view_model=SimpleNamespace(as_of="2026-04-08"),
        perf_warnings=[],
    )

    monkeypatch.setattr(app_services, "build_risk_report_view_model", fake_build_risk_report_view_model)
    monkeypatch.setattr(PortfolioMonitorQueryService, "_load_perf_cached", lambda *args, **kwargs: fake_perf_entry)
    monkeypatch.setattr(PortfolioMonitorQueryService, "_load_regime_view_model", staticmethod(fake_load_regime_view_model))

    report_data = PortfolioMonitorQueryService().load_report_data(
        PortfolioReportInputs(
            positions_csv_path=positions_csv,
            performance_output_dir=tmp_path / "flex",
            regime_path=regime_path,
        )
    )

    assert captured["regime_path"] == regime_path
    assert captured["loaded_regime_path"] == regime_path
    assert report_data.risk_view_model.as_of == "2026-04-08T00:00:00+00:00"
    assert report_data.regime_view_model.regime == "Goldilocks"


def test_query_service_fills_missing_spy_benchmark_from_cached_returns(
    monkeypatch,
    tmp_path: Path,
) -> None:
    positions_csv = _write_positions_csv(tmp_path / "positions.csv")
    returns_json = _write_returns_json(tmp_path / "returns.json")
    proxy_json = _write_proxy_json(tmp_path / "proxy.json")
    performance_output_dir = tmp_path / "flex"
    performance_output_dir.mkdir()
    history = _demo_history_frame()
    history["bench_spy_return_usd"] = [pd.NA] * len(history)
    history["bench_spy_return_sgd"] = [pd.NA] * len(history)
    history["bench_bil_return_usd"] = [pd.NA] * len(history)
    history["bench_bil_return_sgd"] = [pd.NA] * len(history)
    history.to_feather(performance_output_dir / "nav_cashflow_history.feather")

    def fake_attach_cached_benchmark_returns(loaded):
        enriched = loaded.copy()
        enriched["bench_spy_return_usd"] = [pd.NA, 0.01, 0.01, 0.01, 0.01]
        enriched["bench_spy_return_sgd"] = [pd.NA, 0.01, 0.01, 0.01, 0.01]
        enriched["bench_bil_return_usd"] = [pd.NA, 0.0001, 0.0001, 0.0001, 0.0001]
        enriched["bench_bil_return_sgd"] = [pd.NA, 0.0001, 0.0001, 0.0001, 0.0001]
        return enriched

    monkeypatch.setattr(app_services, "attach_cached_benchmark_returns", fake_attach_cached_benchmark_returns)

    service = PortfolioMonitorQueryService()
    report_data = service.load_report_data(
        PortfolioReportInputs(
            positions_csv_path=positions_csv,
            performance_output_dir=performance_output_dir,
            returns_path=returns_json,
            proxy_path=proxy_json,
        )
    )

    figure = report_data.performance_usd_view_model.chart_specs["percent"]["FULL"]
    assert any(trace.get("name") == "SPY (benchmark)" for trace in figure["data"])


def test_action_service_bridges_workflow_progress(monkeypatch, tmp_path: Path) -> None:
    recorded: dict[str, object] = {}

    def fake_generate_live_ibkr_position_report(**kwargs):
        progress = kwargs["progress"]
        progress.stage("IBKR live report", current=0, total=1)
        progress.done("IBKR live report", detail="wrote live.csv")
        recorded.update(kwargs)
        return tmp_path / "live.csv"

    monkeypatch.setattr(app_services.report_workflows, "generate_live_ibkr_position_report", fake_generate_live_ibkr_position_report)

    sink = InMemoryUiProgressSink()
    service = PortfolioMonitorActionService()
    written = service.refresh_live_positions(
        LivePortfolioRefreshInputs(output_path=tmp_path / "live.csv", client_id=7, account_id="U123"),
        sink=sink,
    )

    assert written == tmp_path / "live.csv"
    assert recorded["client_id"] == 7
    assert recorded["account_id"] == "U123"
    assert [event.kind for event in sink.events] == ["stage", "done"]
    assert sink.events[-1].detail == "wrote live.csv"


def test_action_service_runs_regime_report_from_cached_inputs(monkeypatch, tmp_path: Path) -> None:
    recorded: dict[str, object] = {}
    regime_json = tmp_path / "regime.json"
    regime_html = tmp_path / "regime.html"
    regime_html.write_text("<html>regime</html>", encoding="utf-8")

    def fake_run_regime_report_from_existing_data(**kwargs):
        recorded.update(kwargs)
        return app_services.regime_report_workflows.RegimeReportRunResult(
            regime_path=regime_json,
            html_path=regime_html,
            macro_panel_path=tmp_path / "macro.feather",
            market_panel_path=tmp_path / "market.feather",
            market_config_path=tmp_path / "market.yml",
        )

    monkeypatch.setattr(
        app_services.regime_report_workflows,
        "run_regime_report_from_existing_data",
        fake_run_regime_report_from_existing_data,
    )

    sink = InMemoryUiProgressSink()
    artifact = PortfolioMonitorActionService().run_regime_report(
        RegimeReportRunInputs(output_regime_path=regime_json, output_html_path=regime_html),
        sink=sink,
    )

    assert recorded["output_regime_path"] == regime_json
    assert recorded["output_html_path"] == regime_html
    assert artifact.report_type == "regime_engine_v2"
    assert artifact.output_path == regime_html
    assert artifact.exists is True
    assert [event.label for event in sink.events] == ["Regime Engine v2", "Regime Engine v2"]


def test_action_service_refreshes_regime_report(monkeypatch, tmp_path: Path) -> None:
    recorded: dict[str, object] = {}
    regime_json = tmp_path / "regime.json"
    regime_html = tmp_path / "regime.html"
    regime_html.write_text("<html>regime</html>", encoding="utf-8")

    def fake_refresh_data_and_run_regime_report(**kwargs):
        recorded.update(kwargs)
        return app_services.regime_report_workflows.RegimeReportRunResult(
            regime_path=regime_json,
            html_path=regime_html,
            macro_panel_path=tmp_path / "macro.feather",
            market_panel_path=tmp_path / "market.feather",
            market_config_path=tmp_path / "market.yml",
            refreshed_market_panel=True,
        )

    monkeypatch.setattr(
        app_services.regime_report_workflows,
        "refresh_data_and_run_regime_report",
        fake_refresh_data_and_run_regime_report,
    )

    artifact = PortfolioMonitorActionService().refresh_regime_report(
        RegimeReportRefreshInputs(
            output_regime_path=regime_json,
            output_html_path=regime_html,
            max_age_days=3,
            force_refresh=True,
        )
    )

    assert recorded["max_age_days"] == 3
    assert recorded["force_refresh"] is True
    assert artifact.output_path == regime_html


def test_action_service_normalizes_combined_and_etf_calls(monkeypatch, tmp_path: Path) -> None:
    write_calls: dict[str, object] = {}
    etf_calls: dict[str, object] = {}
    load_calls = 0

    def fake_write_portfolio_report(report_data, output_path):
        write_calls["report_data"] = report_data
        write_calls["output_path"] = output_path
        output_path = Path(output_path)
        output_path.write_text("<html>combined</html>", encoding="utf-8")
        return output_path

    def fake_ensure_google_drive_artifact_mirror(**kwargs):
        assert kwargs["source_path"] == tmp_path / "combined.html"
        assert kwargs["target_name"] == "portfolio_combined_report.html"
        return tmp_path / "google-drive" / "portfolio_combined_report.html"

    def fake_generate_etf_sector_sync(**kwargs):
        etf_calls.update(kwargs)
        progress = kwargs["progress"]
        progress.stage("ETF sector sync", current=0, total=1)
        progress.done("ETF sector sync", detail="done")
        return tmp_path / "sector.json"

    monkeypatch.setattr(app_services, "write_portfolio_report", fake_write_portfolio_report)
    monkeypatch.setattr(app_services.report_workflows, "ensure_google_drive_artifact_mirror", fake_ensure_google_drive_artifact_mirror)
    monkeypatch.setattr(app_services.report_workflows, "generate_etf_sector_sync", fake_generate_etf_sector_sync)
    query_service = app_services.PortfolioMonitorQueryService()
    fake_report_data = app_services.PortfolioReportData(
            as_of="2026-04-08T00:00:00+00:00",
            artifact_metadata=app_services.ArtifactMetadata(
                positions_csv_path=tmp_path / "positions.csv",
                performance_output_dir=tmp_path / "flex",
                performance_history_path=None,
                performance_report_csv_path=None,
                returns_path=None,
                proxy_path=None,
                regime_path=None,
                security_reference_path=None,
                risk_config_path=None,
                allocation_policy_path=None,
                positions_as_of="2026-04-08T00:00:00+00:00",
            ),
            performance_usd_view_model=object(),  # type: ignore[arg-type]
            performance_sgd_view_model=object(),  # type: ignore[arg-type]
            risk_view_model=object(),  # type: ignore[arg-type]
            warnings=[],
    )

    def fake_load_report_data(inputs=None):
        nonlocal load_calls
        load_calls += 1
        return fake_report_data

    monkeypatch.setattr(query_service, "load_report_data", fake_load_report_data)

    service = PortfolioMonitorActionService(query_service=query_service)
    sink = InMemoryUiProgressSink()
    combined_written = service.generate_combined_report(
        GenerateCombinedReportInputs(
            positions_csv_path=tmp_path / "positions.csv",
            performance_output_dir=tmp_path / "flex",
            output_path=tmp_path / "combined.html",
        ),
        sink=sink,
    )
    etf_written = service.sync_etf_sector(
        EtfSectorSyncInputs(symbols=["DBMF", "QQQ"], output_path=tmp_path / "sector.json", api_key="demo"),
        sink=sink,
    )

    assert combined_written.output_path == tmp_path / "combined.html"
    assert combined_written.mirrored_output_path == tmp_path / "google-drive" / "portfolio_combined_report.html"
    assert combined_written.report_type == "portfolio_monitor"
    assert write_calls["output_path"] == tmp_path / "combined.html"
    assert write_calls["report_data"] == fake_report_data
    assert load_calls == 1
    assert etf_written == tmp_path / "sector.json"
    assert etf_calls["symbols"] == ["DBMF", "QQQ"]
    assert etf_calls["api_key"] == "demo"
    assert any(event.label == "Combined HTML" for event in sink.events)
    assert any(event.label == "ETF sector sync" for event in sink.events)


def test_generate_combined_report_returns_local_artifact_when_mirror_fails(
    monkeypatch,
    tmp_path: Path,
) -> None:
    def fake_write_portfolio_report(report_data, output_path):
        output_path = Path(output_path)
        output_path.write_text("<html>combined</html>", encoding="utf-8")
        return output_path

    def fake_ensure_google_drive_artifact_mirror(**kwargs):
        raise PermissionError("mirror denied")

    monkeypatch.setattr(app_services, "write_portfolio_report", fake_write_portfolio_report)
    monkeypatch.setattr(
        app_services.report_workflows,
        "ensure_google_drive_artifact_mirror",
        fake_ensure_google_drive_artifact_mirror,
    )
    query_service = app_services.PortfolioMonitorQueryService()
    fake_report_data = app_services.PortfolioReportData(
        as_of="2026-04-08T00:00:00+00:00",
        artifact_metadata=app_services.ArtifactMetadata(
            positions_csv_path=tmp_path / "positions.csv",
            performance_output_dir=tmp_path / "flex",
            performance_history_path=None,
            performance_report_csv_path=None,
            returns_path=None,
            proxy_path=None,
            regime_path=None,
            security_reference_path=None,
            risk_config_path=None,
            allocation_policy_path=None,
            positions_as_of="2026-04-08T00:00:00+00:00",
        ),
        performance_usd_view_model=object(),  # type: ignore[arg-type]
        performance_sgd_view_model=object(),  # type: ignore[arg-type]
        risk_view_model=object(),  # type: ignore[arg-type]
        warnings=[],
    )

    monkeypatch.setattr(query_service, "load_report_data", lambda inputs=None: fake_report_data)

    service = PortfolioMonitorActionService(query_service=query_service)
    artifact = service.generate_combined_report(
        GenerateCombinedReportInputs(
            positions_csv_path=tmp_path / "positions.csv",
            performance_output_dir=tmp_path / "flex",
            output_path=tmp_path / "combined.html",
        )
    )

    assert artifact.output_path == tmp_path / "combined.html"
    assert artifact.exists is True
    assert artifact.mirrored_output_path is None
    assert any("Google Drive artifact mirror failed" in warning for warning in artifact.warnings)


def _write_positions_csv(path: Path) -> Path:
    path.write_text(
        "\n".join(
            [
                "as_of,account,internal_id,con_id,symbol,local_symbol,exchange,currency,source,quantity,avg_cost,latest_price,market_value,cost_basis,unrealized_pnl,weight",
                "2026-04-08T00:00:00+00:00,U1,STK:AAPL:SMART,265598,AAPL,AAPL,SMART,USD,ibkr,10,170,175,1750,1700,50,1.0",
            ]
        ),
        encoding="utf-8",
    )
    return path


def _write_returns_json(path: Path) -> Path:
    path.write_text(
        json.dumps({"STK:AAPL:SMART": [0.001 * ((idx % 5) - 2) for idx in range(90)]}),
        encoding="utf-8",
    )
    return path


def _write_proxy_json(path: Path) -> Path:
    path.write_text(json.dumps({"VIX": 20.0, "MOVE": 120.0}), encoding="utf-8")
    return path


def _demo_history_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": pd.to_datetime(
                [
                    "2023-12-31",
                    "2024-12-31",
                    "2025-12-31",
                    "2026-01-31",
                    "2026-04-08",
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
            "bench_spy_return_usd": [pd.NA, 0.08, 0.10, 0.02, 0.02],
            "bench_spy_return_sgd": [pd.NA, 0.08, 0.10, 0.02, 0.02],
            "bench_bil_return_usd": [pd.NA, 0.002, 0.002, 0.001, 0.001],
            "bench_bil_return_sgd": [pd.NA, 0.002, 0.002, 0.001, 0.001],
            "is_final": [True, True, True, True, False],
            "source_kind": ["full", "full", "full", "latest", "latest"],
            "source_file": ["demo.xml"] * 5,
            "source_as_of": pd.to_datetime(["2026-04-08"] * 5),
        }
    )
