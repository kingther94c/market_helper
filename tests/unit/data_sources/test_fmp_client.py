from __future__ import annotations

import pytest

from market_helper.data_sources.fmp import FmpClient, FmpClientError


def test_fmp_client_accepts_list_payload_and_normalizes_percent_weights() -> None:
    client = FmpClient(
        api_key="demo",
        downloader=lambda _url: [
            {"sector": "Technology", "weightPercentage": 80},
            {"sector": "Financial Services", "weightPercentage": "20%"},
        ],
    )

    rows = client.fetch_etf_sector_weightings("SOXX")

    assert [(row.sector, row.weight) for row in rows] == [
        ("Technology", 0.8),
        ("Financial Services", 0.2),
    ]


def test_fmp_client_accepts_direct_sector_mapping_payload() -> None:
    client = FmpClient(
        api_key="demo",
        downloader=lambda _url: {
            "Technology": 0.6,
            "Healthcare": 0.4,
        },
    )

    rows = client.fetch_etf_sector_weightings("XLV")

    assert [(row.sector, row.weight) for row in rows] == [
        ("Technology", 0.6),
        ("Healthcare", 0.4),
    ]


def test_fmp_client_surfaces_error_payloads() -> None:
    client = FmpClient(
        api_key="demo",
        downloader=lambda _url: {"Error Message": "Invalid API key"},
    )

    with pytest.raises(FmpClientError, match="Invalid API key"):
        client.fetch_etf_sector_weightings("SOXX")
