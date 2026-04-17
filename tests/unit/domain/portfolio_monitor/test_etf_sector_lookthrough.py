from __future__ import annotations

import json
from datetime import date

from market_helper.data_sources.alpha_vantage import AlphaVantageEtfSectorWeight
import market_helper.domain.portfolio_monitor.services.etf_sector_lookthrough as etf_sector_lookthrough
from market_helper.domain.portfolio_monitor.services.etf_sector_lookthrough import (
    load_us_sector_weight_table,
    refresh_us_sector_lookthrough_for_report,
    sync_us_sector_lookthrough,
)


def test_load_us_sector_weight_table_reads_json_store(tmp_path) -> None:
    path = tmp_path / "us_sector_lookthrough.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "provider": "alpha_vantage",
                "daily_call_limit": 20,
                "api_usage": {"date": "", "count": 0},
                "symbols": {
                    "SOXX": {
                        "updated_at": "2000-01-01",
                        "status": "ok",
                        "error_message": "",
                        "sectors": [{"sector": "Technology", "weight": 1.0}],
                    },
                    "TSLA": {
                        "updated_at": "2000-01-01",
                        "status": "pending",
                        "error_message": "",
                        "sectors": [],
                    },
                },
            }
        ),
        encoding="utf-8",
    )

    weights = load_us_sector_weight_table(path)

    assert weights == {"SOXX": [("Technology", 1.0)]}


def test_refresh_us_sector_lookthrough_for_report_adds_pending_symbol_without_api_key(
    tmp_path,
    monkeypatch,
) -> None:
    path = tmp_path / "us_sector_lookthrough.json"
    monkeypatch.delenv("ALPHA_VANTAGE_API_KEY", raising=False)
    monkeypatch.setattr(etf_sector_lookthrough, "DEFAULT_CANONICAL_LOCAL_ENV_PATH", tmp_path / "missing-local.env")

    written_path = refresh_us_sector_lookthrough_for_report(
        symbols=["SOXX"],
        output_path=path,
        today=date(2026, 4, 8),
    )

    payload = json.loads(written_path.read_text(encoding="utf-8"))

    assert payload["symbols"]["SOXX"]["updated_at"] == "2000-01-01"
    assert payload["symbols"]["SOXX"]["status"] == "pending"
    assert payload["symbols"]["SOXX"]["sectors"] == []


def test_sync_us_sector_lookthrough_respects_daily_budget(tmp_path) -> None:
    path = tmp_path / "us_sector_lookthrough.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "provider": "alpha_vantage",
                "daily_call_limit": 20,
                "api_usage": {"date": "2026-04-08", "count": 19},
                "symbols": {
                    "QQQ": {
                        "updated_at": "2026-04-01",
                        "status": "ok",
                        "error_message": "",
                        "sectors": [{"sector": "Technology", "weight": 0.6}],
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    class FakeClient:
        def fetch_etf_sector_weightings(self, symbol: str):
            assert symbol == "SOXX"
            return [AlphaVantageEtfSectorWeight(symbol="SOXX", sector="Technology", weight=1.0)]

    written_path = sync_us_sector_lookthrough(
        symbols=["QQQ", "SOXX"],
        output_path=path,
        client=FakeClient(),
        force_refresh=False,
        today=date(2026, 4, 8),
    )

    payload = json.loads(written_path.read_text(encoding="utf-8"))

    assert payload["api_usage"] == {"date": "2026-04-08", "count": 20}
    assert payload["symbols"]["SOXX"]["sectors"] == [{"sector": "Technology", "weight": 1.0}]
    assert payload["symbols"]["SOXX"]["updated_at"] == "2026-04-08"
    assert payload["symbols"]["QQQ"]["updated_at"] == "2026-04-01"


def test_refresh_us_sector_lookthrough_reads_fmp_api_key_from_local_env(
    tmp_path,
    monkeypatch,
) -> None:
    path = tmp_path / "us_sector_lookthrough.json"
    local_env = tmp_path / "local.env"
    local_env.write_text('ALPHA_VANTAGE_API_KEY="local-file-key"\n', encoding="utf-8")

    monkeypatch.delenv("ALPHA_VANTAGE_API_KEY", raising=False)
    monkeypatch.setattr(etf_sector_lookthrough, "DEFAULT_CANONICAL_LOCAL_ENV_PATH", local_env)

    captured: dict[str, object] = {}

    class FakeClient:
        def __init__(self, api_key: str) -> None:
            captured["api_key"] = api_key

        def fetch_etf_sector_weightings(self, symbol: str):
            captured["symbol"] = symbol
            return [AlphaVantageEtfSectorWeight(symbol=symbol, sector="Technology", weight=1.0)]

    monkeypatch.setattr(etf_sector_lookthrough, "AlphaVantageClient", FakeClient)

    written_path = refresh_us_sector_lookthrough_for_report(
        symbols=["SOXX"],
        output_path=path,
        today=date(2026, 4, 8),
    )

    payload = json.loads(written_path.read_text(encoding="utf-8"))

    assert captured == {"api_key": "local-file-key", "symbol": "SOXX"}
    assert payload["symbols"]["SOXX"]["status"] == "ok"
    assert payload["symbols"]["SOXX"]["updated_at"] == "2026-04-08"
