"""Treasury par-yield-curve fallback — real published data, FRED's own formulas.

Fixture CSVs mirror the live treasury.gov response shape (verified 2026-06-11):
MM/DD/YYYY dates, quoted tenor headers, descending date order.
"""

from __future__ import annotations

import pytest

from market_helper.data_library.loader import DownloadError
from market_helper.data_sources.treasury.yield_curve import (
    TREASURY_DERIVABLE_SERIES,
    download_treasury_derived_series,
)

_NOMINAL_CSV = (
    'Date,"1 Mo","1.5 Month","2 Mo","3 Mo","4 Mo","6 Mo","1 Yr","2 Yr","3 Yr","5 Yr","7 Yr","10 Yr","20 Yr","30 Yr"\n'
    "06/10/2026,3.69,3.70,3.72,3.79,3.80,3.82,3.90,4.13,4.17,4.27,4.40,4.55,5.04,5.03\n"
    "06/09/2026,3.69,3.69,3.71,3.79,3.78,3.81,3.89,4.11,4.15,4.25,4.38,4.53,5.02,5.01\n"
)
_REAL_CSV = (
    'Date,"5 YR","7 YR","10 YR","20 YR","30 YR"\n'
    "06/10/2026,1.83,2.02,2.21,2.58,2.78\n"
    "06/09/2026,1.82,2.00,2.20,2.56,2.75\n"
)


def _fetcher(url: str) -> str:
    if "daily_treasury_real_yield_curve" in url:
        return _REAL_CSV
    return _NOMINAL_CSV


def test_t10y2y_is_ten_minus_two_year_nominal() -> None:
    series = download_treasury_derived_series(
        "T10Y2Y", observation_start="2026-06-09", observation_end="2026-06-10", fetcher=_fetcher
    )
    by_date = {obs.date: obs.value for obs in series.observations}
    assert by_date["2026-06-10"] == pytest.approx(4.55 - 4.13)
    assert by_date["2026-06-09"] == pytest.approx(4.53 - 4.11)
    assert series.metadata["source"] == "treasury_par_yield_curve"


def test_t10y3m_and_direct_columns() -> None:
    t10y3m = download_treasury_derived_series(
        "T10Y3M", observation_start="2026-06-10", observation_end="2026-06-10", fetcher=_fetcher
    )
    assert t10y3m.observations[0].value == pytest.approx(4.55 - 3.79)

    dfii10 = download_treasury_derived_series(
        "DFII10", observation_start="2026-06-10", observation_end="2026-06-10", fetcher=_fetcher
    )
    assert dfii10.observations[0].value == pytest.approx(2.21)


def test_t5yie_is_nominal_minus_real() -> None:
    series = download_treasury_derived_series(
        "T5YIE", observation_start="2026-06-10", observation_end="2026-06-10", fetcher=_fetcher
    )
    assert series.observations[0].value == pytest.approx(4.27 - 1.83)


def test_t5yifr_uses_fred_documented_compounding() -> None:
    series = download_treasury_derived_series(
        "T5YIFR", observation_start="2026-06-10", observation_end="2026-06-10", fetcher=_fetcher
    )
    bc10 = 4.55 - 2.21
    bc5 = 4.27 - 1.83
    expected = (((1 + bc10 / 200.0) ** 20 / (1 + bc5 / 200.0) ** 10) ** 0.1 - 1.0) * 200.0
    assert series.observations[0].value == pytest.approx(expected, abs=1e-4)


def test_window_filters_observations() -> None:
    series = download_treasury_derived_series(
        "T10Y2Y", observation_start="2026-06-10", observation_end="2026-06-10", fetcher=_fetcher
    )
    assert [obs.date for obs in series.observations] == ["2026-06-10"]


def test_underivable_series_raises_download_error() -> None:
    assert "UNRATE" not in TREASURY_DERIVABLE_SERIES
    with pytest.raises(DownloadError):
        download_treasury_derived_series("UNRATE", fetcher=_fetcher)


def test_malformed_body_raises_download_error() -> None:
    with pytest.raises(DownloadError):
        download_treasury_derived_series(
            "T10Y2Y",
            observation_start="2026-06-10",
            fetcher=lambda url: "<html>maintenance</html>",
        )
