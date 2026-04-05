from __future__ import annotations

import math
from pathlib import Path

import pandas as pd
import pytest

from market_helper.data_sources.yahoo_finance import YahooFinanceClient
from market_helper.domain.portfolio_monitor.services.yahoo_returns import (
    YahooReturnCache,
    ensure_symbol_return_cache,
    load_internal_id_return_series_override,
    load_symbol_return_cache,
    write_symbol_return_cache,
    yahoo_symbol_cache_path,
)


def test_ensure_symbol_return_cache_writes_and_reuses_log_returns(tmp_path: Path) -> None:
    calls = {"count": 0}

    def fake_download(_url: str) -> dict[str, object]:
        calls["count"] += 1
        return {
            "chart": {
                "result": [
                    {
                        "meta": {"currency": "USD"},
                        "timestamp": [1704067200, 1704153600, 1704240000],
                        "indicators": {
                            "quote": [{"close": [100.0, 101.0, 103.0]}],
                            "adjclose": [{"adjclose": [100.0, 101.0, 103.0]}],
                        },
                    }
                ]
            }
        }

    client = YahooFinanceClient(downloader=fake_download)
    first = ensure_symbol_return_cache(
        "SPY",
        yahoo_client=client,
        cache_dir=tmp_path,
        now=pd.Timestamp("2024-01-04"),
    )
    second = ensure_symbol_return_cache(
        "SPY",
        yahoo_client=client,
        cache_dir=tmp_path,
        now=pd.Timestamp("2024-01-04"),
    )

    assert calls["count"] == 1
    assert len(first.series) == 2
    assert float(first.series.iloc[0]) == pytest.approx(math.log(101.0 / 100.0))
    assert second.series.equals(first.series)
    assert yahoo_symbol_cache_path("SPY", cache_dir=tmp_path).exists()


def test_ensure_symbol_return_cache_refreshes_stale_cache(tmp_path: Path) -> None:
    stale_cache = YahooReturnCache(
        symbol="SPY",
        currency="USD",
        source="yahoo_finance",
        price_field="adjclose",
        return_method="log",
        interval="1d",
        period="5y",
        generated_at="2024-01-03T00:00:00",
        series=pd.Series(
            [0.01],
            index=pd.DatetimeIndex([pd.Timestamp("2024-01-03")]),
            dtype=float,
        ),
    )
    write_symbol_return_cache(stale_cache, cache_dir=tmp_path)

    calls = {"count": 0}

    def fake_download(_url: str) -> dict[str, object]:
        calls["count"] += 1
        return {
            "chart": {
                "result": [
                    {
                        "meta": {"currency": "USD"},
                        "timestamp": [1704326400, 1704412800, 1704499200],
                        "indicators": {
                            "quote": [{"close": [103.0, 104.0, 105.0]}],
                            "adjclose": [{"adjclose": [103.0, 104.0, 105.0]}],
                        },
                    }
                ]
            }
        }

    refreshed = ensure_symbol_return_cache(
        "SPY",
        yahoo_client=YahooFinanceClient(downloader=fake_download),
        cache_dir=tmp_path,
        now=pd.Timestamp("2024-01-08"),
    )

    assert calls["count"] == 1
    assert refreshed.series.index.max() == pd.Timestamp("2024-01-06")


def test_yahoo_symbol_cache_path_quotes_symbols_safely(tmp_path: Path) -> None:
    path = yahoo_symbol_cache_path("ZN=F", cache_dir=tmp_path)
    assert path.name == "ZN%3DF.json"


def test_load_internal_id_return_series_override_supports_legacy_and_dated_shapes(tmp_path: Path) -> None:
    override_path = tmp_path / "returns.json"
    override_path.write_text(
        '{"STK:SPY:SMART":[0.01,-0.02],"FUT:ZN:CBOT":{"2024-01-02":0.001,"2024-01-03":-0.002}}',
        encoding="utf-8",
    )

    loaded = load_internal_id_return_series_override(override_path)

    assert list(loaded["STK:SPY:SMART"].index) == [-2, -1]
    assert list(loaded["FUT:ZN:CBOT"].index) == [pd.Timestamp("2024-01-02"), pd.Timestamp("2024-01-03")]


def test_load_symbol_return_cache_round_trips_written_payload(tmp_path: Path) -> None:
    cache = YahooReturnCache(
        symbol="SPYL.L",
        currency="USD",
        source="yahoo_finance",
        price_field="adjclose",
        return_method="log",
        interval="1d",
        period="5y",
        generated_at="2024-01-04T00:00:00",
        series=pd.Series(
            [0.01, -0.02],
            index=pd.DatetimeIndex([pd.Timestamp("2024-01-02"), pd.Timestamp("2024-01-03")]),
            dtype=float,
        ),
    )

    written = write_symbol_return_cache(cache, cache_dir=tmp_path)
    loaded = load_symbol_return_cache(written)

    assert loaded is not None
    assert loaded.symbol == "SPYL.L"
    assert loaded.series.equals(cache.series)
