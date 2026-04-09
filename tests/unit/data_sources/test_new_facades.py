from urllib.error import HTTPError

import pandas as pd
import pytest

from market_helper.data_sources.alpha_vantage import (
    AlphaVantageClient,
    AlphaVantageEtfSectorWeight,
)
from market_helper.data_sources.fred import download_fred_series_batch
from market_helper.data_sources.ibkr.tws import choose_tws_account
from market_helper.data_sources.yahoo_finance import YahooFinanceClient


def test_ibkr_tws_facade_preserves_choose_account_behavior() -> None:
    assert choose_tws_account(["U1", "U2"], "U2") == "U2"


def test_fred_facade_exports_batch_loader() -> None:
    assert callable(download_fred_series_batch)


def test_yahoo_finance_facade_is_explicit_scaffold() -> None:
    client = YahooFinanceClient(
        downloader=lambda _url: {
            "chart": {
                "result": [
                    {
                        "meta": {"currency": "USD"},
                        "timestamp": [1, 2, 3],
                        "indicators": {
                            "quote": [{"close": [100.0, 101.0, 103.0]}],
                            "adjclose": [{"adjclose": [100.0, 101.0, 103.0]}],
                        },
                    }
                ]
            }
        }
    )
    payload = client.fetch_price_history("SPY")
    assert payload["symbol"] == "SPY"
    assert len(payload["prices"]) == 3


def test_yahoo_finance_client_retries_rate_limit_errors() -> None:
    calls = {"count": 0}

    def fake_download(_url: str) -> dict[str, object]:
        calls["count"] += 1
        if calls["count"] < 3:
            raise HTTPError(
                url="https://query1.finance.yahoo.com",
                code=429,
                msg="Too Many Requests",
                hdrs={"Retry-After": "0"},
                fp=None,
            )
        return {
            "chart": {
                "result": [
                    {
                        "meta": {"currency": "USD"},
                        "timestamp": [1, 2, 3],
                        "indicators": {
                            "quote": [{"close": [100.0, 101.0, 103.0]}],
                            "adjclose": [{"adjclose": [100.0, 101.0, 103.0]}],
                        },
                    }
                ]
            }
        }

    client = YahooFinanceClient(
        downloader=fake_download,
        max_attempts=3,
        sleep=lambda _seconds: None,
    )

    payload = client.fetch_price_history("SPY")

    assert payload["symbol"] == "SPY"
    assert calls["count"] == 3


def test_yahoo_finance_client_uses_yfinance_for_runtime_fetch(monkeypatch) -> None:
    class FakeTicker:
        def __init__(self, ticker: str, session=None) -> None:
            assert ticker == "SPY"
            self.history_metadata = {"currency": "USD"}

        def history(self, *, period: str, interval: str, auto_adjust: bool, actions: bool):
            assert period == "5y"
            assert interval == "1d"
            assert auto_adjust is False
            assert actions is False
            return pd.DataFrame(
                {
                    "Close": [100.0, 101.0],
                    "Adj Close": [99.5, 100.5],
                },
                index=pd.to_datetime(["2024-01-02", "2024-01-03"], utc=True),
            )

    monkeypatch.setattr("market_helper.data_sources.yahoo_finance.client.yf.Ticker", FakeTicker)

    payload = YahooFinanceClient().fetch_price_history("SPY")

    assert payload["symbol"] == "SPY"
    assert payload["currency"] == "USD"
    assert payload["prices"] == [
        {"timestamp": 1704153600, "close": 100.0, "adjclose": 99.5},
        {"timestamp": 1704240000, "close": 101.0, "adjclose": 100.5},
    ]


def test_alpha_vantage_facade_fetches_sector_weights() -> None:
    client = AlphaVantageClient(
        api_key="demo",
        downloader=lambda _url: {
            "sectors": [
                {"sector": "INFORMATION TECHNOLOGY", "weight": "0.8"},
                {"sector": "FINANCIALS", "weight": "0.2"},
            ]
        },
    )

    payload = client.fetch_etf_sector_weightings("SOXX")

    assert payload == [
        AlphaVantageEtfSectorWeight(
            symbol="SOXX",
            sector="INFORMATION TECHNOLOGY",
            weight=0.8,
        ),
        AlphaVantageEtfSectorWeight(symbol="SOXX", sector="FINANCIALS", weight=0.2),
    ]
