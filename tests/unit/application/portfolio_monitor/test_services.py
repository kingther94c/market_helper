from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from market_helper.application.portfolio_monitor import (
    EtfSectorSyncInputs,
    GenerateCombinedReportInputs,
    InMemoryUiProgressSink,
    LivePortfolioRefreshInputs,
    PortfolioMonitorActionService,
    PortfolioMonitorQueryService,
    PortfolioReportInputs,
)
from market_helper.application.portfolio_monitor import services as app_services


def test_query_service_load_snapshot_resolves_expected_artifacts(tmp_path: Path) -> None:
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
    snapshot = service.load_snapshot(
        PortfolioReportInputs(
            positions_csv_path=positions_csv,
            performance_output_dir=performance_output_dir,
            returns_path=returns_json,
            proxy_path=proxy_json,
        )
    )

    assert snapshot.as_of == "2026-04-08T00:00:00+00:00"
    assert snapshot.artifact_metadata.positions_csv_path == positions_csv
    assert snapshot.artifact_metadata.performance_output_dir == performance_output_dir
    assert snapshot.artifact_metadata.performance_report_csv_path == performance_output_dir / "performance_report_20260408.csv"
    assert snapshot.performance_usd_view_model.as_of == "2026-04-08"
    assert snapshot.performance_sgd_view_model.as_of == "2026-04-08"
    assert snapshot.warnings == []


def test_query_service_warns_when_performance_artifacts_are_missing(tmp_path: Path) -> None:
    positions_csv = _write_positions_csv(tmp_path / "positions.csv")
    returns_json = _write_returns_json(tmp_path / "returns.json")
    proxy_json = _write_proxy_json(tmp_path / "proxy.json")

    service = PortfolioMonitorQueryService()
    snapshot = service.load_snapshot(
        PortfolioReportInputs(
            positions_csv_path=positions_csv,
            performance_output_dir=tmp_path / "missing_flex",
            returns_path=returns_json,
            proxy_path=proxy_json,
        )
    )

    assert snapshot.as_of == "2026-04-08T00:00:00+00:00"
    assert any("Performance history file not found" in warning for warning in snapshot.warnings)
    assert any("Dated performance report CSV is missing" in warning for warning in snapshot.warnings)
    assert snapshot.performance_usd_view_model.as_of == "n/a"


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


def test_action_service_normalizes_combined_and_etf_calls(monkeypatch, tmp_path: Path) -> None:
    combined_calls: dict[str, object] = {}
    etf_calls: dict[str, object] = {}

    def fake_generate_combined_html_report(**kwargs):
        combined_calls.update(kwargs)
        return Path(kwargs["output_path"])

    def fake_generate_etf_sector_sync(**kwargs):
        etf_calls.update(kwargs)
        progress = kwargs["progress"]
        progress.stage("ETF sector sync", current=0, total=1)
        progress.done("ETF sector sync", detail="done")
        return tmp_path / "sector.json"

    monkeypatch.setattr(app_services.report_workflows, "generate_combined_html_report", fake_generate_combined_html_report)
    monkeypatch.setattr(app_services.report_workflows, "generate_etf_sector_sync", fake_generate_etf_sector_sync)

    service = PortfolioMonitorActionService()
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

    assert combined_written == tmp_path / "combined.html"
    assert combined_calls["output_path"] == tmp_path / "combined.html"
    assert combined_calls["positions_csv_path"] == tmp_path / "positions.csv"
    assert etf_written == tmp_path / "sector.json"
    assert etf_calls["symbols"] == ["DBMF", "QQQ"]
    assert etf_calls["api_key"] == "demo"
    assert any(event.label == "Combined HTML" for event in sink.events)
    assert any(event.label == "ETF sector sync" for event in sink.events)


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
            "is_final": [True, True, True, True, False],
            "source_kind": ["full", "full", "full", "latest", "latest"],
            "source_file": ["demo.xml"] * 5,
            "source_as_of": pd.to_datetime(["2026-04-08"] * 5),
        }
    )

