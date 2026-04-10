from __future__ import annotations

import json
from datetime import date

from market_helper.data_sources.alpha_vantage import AlphaVantageEtfSectorWeight
import market_helper.domain.portfolio_monitor.services.etf_sector_lookthrough as etf_sector_lookthrough
from market_helper.domain.portfolio_monitor.services.etf_sector_lookthrough import (
    load_us_sector_weight_table,
    refresh_us_sector_lookthrough_for_report,
    sync_us_sector_lookthrough_from_alpha_vantage,
)


def test_load_us_sector_weight_table_reads_json_store(tmp_path) -> None:
    path = tmp_path / "us_sector_lookthrough.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "provider": "alpha_vantage",
                "daily_call_limit": 25,
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
                "daily_call_limit": 25,
                "api_usage": {"date": "2026-04-08", "count": 24},
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
            return [
                AlphaVantageEtfSectorWeight(
                    symbol="SOXX",
                    sector="INFORMATION TECHNOLOGY",
                    weight=1.0,
                )
            ]

    written_path = sync_us_sector_lookthrough_from_alpha_vantage(
        symbols=["QQQ", "SOXX"],
        output_path=path,
        client=FakeClient(),
        force_refresh=False,
        today=date(2026, 4, 8),
    )

    payload = json.loads(written_path.read_text(encoding="utf-8"))

    assert payload["api_usage"] == {"date": "2026-04-08", "count": 25}
    assert payload["symbols"]["SOXX"]["sectors"] == [{"sector": "Technology", "weight": 1.0}]
    assert payload["symbols"]["SOXX"]["updated_at"] == "2026-04-08"
    assert payload["symbols"]["QQQ"]["updated_at"] == "2026-04-01"


def test_refresh_us_sector_lookthrough_reads_alpha_vantage_api_key_from_local_env(
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
            return [
                AlphaVantageEtfSectorWeight(
                    symbol=symbol,
                    sector="INFORMATION TECHNOLOGY",
                    weight=1.0,
                )
            ]

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


def test_refresh_us_sector_lookthrough_normalizes_cached_error_entries_without_network(
    tmp_path,
    monkeypatch,
) -> None:
    path = tmp_path / "us_sector_lookthrough.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "provider": "fmp",
                "daily_call_limit": 250,
                "api_usage": {"date": "", "count": 0},
                "symbols": {
                    "QQQ": {
                        "updated_at": "2026-04-01",
                        "status": "error",
                        "error_message": "Network error while requesting https://financialmodelingprep.com/stable/etf/sector-weightings?symbol=QQQ&apikey=secret-key: [Errno 8] nodename nor servname provided, or not known",
                        "sectors": [{"sector": "Technology", "weight": 0.6}],
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.delenv("ALPHA_VANTAGE_API_KEY", raising=False)
    monkeypatch.setattr(etf_sector_lookthrough, "DEFAULT_CANONICAL_LOCAL_ENV_PATH", tmp_path / "missing-local.env")

    written_path = refresh_us_sector_lookthrough_for_report(
        symbols=["QQQ"],
        output_path=path,
        today=date(2026, 4, 8),
    )

    payload = json.loads(written_path.read_text(encoding="utf-8"))

    assert payload["provider"] == "alpha_vantage"
    assert payload["daily_call_limit"] == 25
    assert payload["api_usage"] == {"date": "", "count": 0}
    assert payload["symbols"]["QQQ"]["status"] == "stale"
    assert payload["symbols"]["QQQ"]["updated_at"] == "2000-01-01"
    assert payload["symbols"]["QQQ"]["error_message"] == ""


def test_sync_us_sector_lookthrough_preserves_cached_data_on_refresh_error(tmp_path) -> None:
    path = tmp_path / "us_sector_lookthrough.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "provider": "alpha_vantage",
                "daily_call_limit": 25,
                "api_usage": {"date": "", "count": 0},
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
            assert symbol == "QQQ"
            raise RuntimeError(
                "Network error while requesting "
                "https://www.alphavantage.co/query?function=ETF_PROFILE&symbol=QQQ&apikey=secret-key: "
                "[Errno 8] nodename nor servname provided, or not known"
            )

    written_path = sync_us_sector_lookthrough_from_alpha_vantage(
        symbols=["QQQ"],
        output_path=path,
        client=FakeClient(),
        today=date(2026, 4, 8),
    )

    payload = json.loads(written_path.read_text(encoding="utf-8"))

    assert payload["symbols"]["QQQ"]["status"] == "stale"
    assert payload["symbols"]["QQQ"]["updated_at"] == "2026-04-01"
    assert payload["symbols"]["QQQ"]["last_attempted_at"] == "2026-04-08"
    assert payload["symbols"]["QQQ"]["sectors"] == [{"sector": "Technology", "weight": 0.6}]
    assert "secret-key" not in payload["symbols"]["QQQ"]["error_message"]


def test_sync_us_sector_lookthrough_stops_querying_after_two_consecutive_failures_in_same_day(tmp_path) -> None:
    path = tmp_path / "us_sector_lookthrough.json"
    attempted_symbols: list[str] = []

    class FailingClient:
        def fetch_etf_sector_weightings(self, symbol: str):
            attempted_symbols.append(symbol)
            raise RuntimeError(f"temporary failure for {symbol}")

    sync_us_sector_lookthrough_from_alpha_vantage(
        symbols=["QQQ", "SOXX", "SPY"],
        output_path=path,
        client=FailingClient(),
        today=date(2026, 4, 8),
    )

    payload = json.loads(path.read_text(encoding="utf-8"))

    assert attempted_symbols == ["QQQ", "SOXX"]
    assert payload["api_usage"] == {"date": "2026-04-08", "count": 2}
    assert payload["failure_streak"] == {"date": "2026-04-08", "count": 2}
    assert payload["symbols"]["SPY"]["last_attempted_at"] == ""
    assert payload["symbols"]["SPY"]["status"] == "pending"

    class UnexpectedRetryClient:
        def fetch_etf_sector_weightings(self, symbol: str):
            raise AssertionError(f"Did not expect another Alpha Vantage retry for {symbol}")

    sync_us_sector_lookthrough_from_alpha_vantage(
        symbols=["QQQ", "SOXX", "SPY"],
        output_path=path,
        client=UnexpectedRetryClient(),
        today=date(2026, 4, 8),
    )

    payload = json.loads(path.read_text(encoding="utf-8"))

    assert payload["api_usage"] == {"date": "2026-04-08", "count": 2}
    assert payload["failure_streak"] == {"date": "2026-04-08", "count": 2}


def test_sync_us_sector_lookthrough_only_counts_consecutive_failures(tmp_path) -> None:
    path = tmp_path / "us_sector_lookthrough.json"
    attempted_symbols: list[str] = []

    class MixedClient:
        def fetch_etf_sector_weightings(self, symbol: str):
            attempted_symbols.append(symbol)
            if symbol in {"QQQ", "SPY"}:
                raise RuntimeError(f"temporary failure for {symbol}")
            return [
                AlphaVantageEtfSectorWeight(
                    symbol=symbol,
                    sector="INFORMATION TECHNOLOGY",
                    weight=1.0,
                )
            ]

    sync_us_sector_lookthrough_from_alpha_vantage(
        symbols=["QQQ", "SOXX", "SPY", "TQQQ"],
        output_path=path,
        client=MixedClient(),
        today=date(2026, 4, 8),
    )

    payload = json.loads(path.read_text(encoding="utf-8"))

    assert attempted_symbols == ["QQQ", "SOXX", "SPY", "TQQQ"]
    assert payload["api_usage"] == {"date": "2026-04-08", "count": 4}
    assert payload["failure_streak"] == {"date": "2026-04-08", "count": 0}
    assert payload["symbols"]["SOXX"]["status"] == "ok"
    assert payload["symbols"]["TQQQ"]["status"] == "ok"


def test_refresh_us_sector_lookthrough_skips_symbol_already_attempted_today(tmp_path) -> None:
    path = tmp_path / "us_sector_lookthrough.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "provider": "alpha_vantage",
                "daily_call_limit": 25,
                "api_usage": {"date": "2026-04-08", "count": 1},
                "symbols": {
                    "QQQ": {
                        "updated_at": "2000-01-01",
                        "last_attempted_at": "2026-04-08",
                        "status": "error",
                        "error_message": "temporary failure",
                        "sectors": [],
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    class FakeClient:
        def fetch_etf_sector_weightings(self, symbol: str):
            raise AssertionError(f"Did not expect a refresh attempt for {symbol}")

    written_path = refresh_us_sector_lookthrough_for_report(
        symbols=["QQQ"],
        output_path=path,
        client=FakeClient(),
        today=date(2026, 4, 8),
    )

    payload = json.loads(written_path.read_text(encoding="utf-8"))

    assert payload["api_usage"] == {"date": "2026-04-08", "count": 1}
    assert payload["symbols"]["QQQ"]["last_attempted_at"] == "2026-04-08"
    assert payload["symbols"]["QQQ"]["status"] == "error"
