from urllib.error import HTTPError

import pytest

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
