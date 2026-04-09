from __future__ import annotations

import pytest

from market_helper.data_sources.alpha_vantage import (
    AlphaVantageClient,
    AlphaVantageClientError,
)


def test_alpha_vantage_client_reads_top_level_sector_rows() -> None:
    client = AlphaVantageClient(
        api_key="demo",
        downloader=lambda _url: {
            "sectors": [
                {"sector": "INFORMATION TECHNOLOGY", "weight": "0.486"},
                {"sector": "COMMUNICATION SERVICES", "weight": "0.159"},
            ]
        },
    )

    rows = client.fetch_etf_sector_weightings("QQQ")

    assert [(row.sector, row.weight) for row in rows] == [
        ("INFORMATION TECHNOLOGY", 0.486),
        ("COMMUNICATION SERVICES", 0.159),
    ]


def test_alpha_vantage_client_normalizes_percent_style_weights() -> None:
    client = AlphaVantageClient(
        api_key="demo",
        downloader=lambda _url: {
            "sectors": [
                {"sector": "Technology", "weight": 80},
                {"sector": "Financials", "weight": "20%"},
            ]
        },
    )

    rows = client.fetch_etf_sector_weightings("SOXX")

    assert [(row.sector, row.weight) for row in rows] == [
        ("Technology", 0.8),
        ("Financials", 0.2),
    ]


def test_alpha_vantage_client_surfaces_error_payloads() -> None:
    client = AlphaVantageClient(
        api_key="demo",
        downloader=lambda _url: {"Information": "rate limit exceeded"},
    )

    with pytest.raises(AlphaVantageClientError, match="rate limit exceeded"):
        client.fetch_etf_sector_weightings("SOXX")


def test_alpha_vantage_client_respects_request_spacing() -> None:
    clock_values = iter([0.0, 0.0, 0.25, 1.25])
    sleep_calls: list[float] = []

    client = AlphaVantageClient(
        api_key="demo",
        downloader=lambda _url: {
            "sectors": [{"sector": "Technology", "weight": "1.0"}]
        },
        request_spacing_seconds=12.0,
        clock=lambda: next(clock_values),
        sleep=lambda seconds: sleep_calls.append(seconds),
    )

    client.fetch_etf_sector_weightings("SOXX")
    client.fetch_etf_sector_weightings("QQQ")

    assert sleep_calls == [12.0]
