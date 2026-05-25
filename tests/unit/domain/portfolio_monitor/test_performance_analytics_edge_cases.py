from __future__ import annotations

"""Edge-case unit tests for `performance_analytics` helpers.

`test_performance_history_services.py` covers happy-path window metrics, TWR/MWR,
yearly rollups, BIL Sharpe, and sparse-history fallbacks. These tests focus on
the narrower helper functions that handle missing/sparse benchmark data — they
are easy to silently break and the gotcha (BIL holidays / SGD/USD calendar
misalignment treated as 0% rather than dropping the row) is load-bearing for the
chart-vs-table reconciliation.
"""

import pandas as pd
import pytest

from market_helper.domain.portfolio_monitor.services.performance_analytics import (
    _benchmark_return_column_if_present,
    _cash_return_column_if_present,
    _compound_window_benchmark,
    _excess_return_series_from_history,
)


# ---------------------------------------------------------------------------
# Currency → benchmark column mapping (USD → bench_spy_return_usd; SGD →
# bench_spy_return_sgd). Returns None when the column is missing entirely or
# the currency is unsupported.
# ---------------------------------------------------------------------------


def test_benchmark_column_usd_when_present() -> None:
    frame = pd.DataFrame({"bench_spy_return_usd": [0.0]})
    assert _benchmark_return_column_if_present(frame, "USD") == "bench_spy_return_usd"


def test_benchmark_column_sgd_when_present() -> None:
    frame = pd.DataFrame({"bench_spy_return_sgd": [0.0]})
    assert _benchmark_return_column_if_present(frame, "SGD") == "bench_spy_return_sgd"


def test_benchmark_column_returns_none_when_absent() -> None:
    frame = pd.DataFrame({"other_col": [0.0]})
    assert _benchmark_return_column_if_present(frame, "USD") is None
    assert _benchmark_return_column_if_present(frame, "SGD") is None


def test_benchmark_column_returns_none_for_unsupported_currency() -> None:
    frame = pd.DataFrame({"bench_spy_return_usd": [0.0], "bench_spy_return_sgd": [0.0]})
    assert _benchmark_return_column_if_present(frame, "EUR") is None


def test_cash_column_usd_and_sgd_and_unsupported() -> None:
    frame = pd.DataFrame({"bench_bil_return_usd": [0.0], "bench_bil_return_sgd": [0.0]})
    assert _cash_return_column_if_present(frame, "USD") == "bench_bil_return_usd"
    assert _cash_return_column_if_present(frame, "SGD") == "bench_bil_return_sgd"
    assert _cash_return_column_if_present(frame, "EUR") is None
    assert _cash_return_column_if_present(pd.DataFrame({"x": [0.0]}), "USD") is None


# ---------------------------------------------------------------------------
# _compound_window_benchmark: NaN-treated-as-zero behavior. The opening row
# is skipped (cumprod starts from index 1). Mixed NaN → zero-fill. All-NaN →
# returns None so the caller can drop a missing-data benchmark instead of
# rendering a flat zero line.
# ---------------------------------------------------------------------------


def test_compound_window_benchmark_happy_path() -> None:
    frame = pd.DataFrame({"bench": [0.0, 0.01, 0.02, -0.01]})
    # Skips iloc[0]; compounds 1.01 * 1.02 * 0.99 - 1 ≈ 0.020098
    assert _compound_window_benchmark(frame, "bench") == pytest.approx(
        (1.01 * 1.02 * 0.99) - 1.0
    )


def test_compound_window_benchmark_treats_nan_as_zero() -> None:
    frame = pd.DataFrame({"bench": [0.0, 0.01, float("nan"), 0.02]})
    # NaN → 0%; 1.01 * 1.00 * 1.02 - 1 ≈ 0.0302
    assert _compound_window_benchmark(frame, "bench") == pytest.approx(
        (1.01 * 1.00 * 1.02) - 1.0
    )


def test_compound_window_benchmark_returns_none_when_all_nan() -> None:
    frame = pd.DataFrame({"bench": [0.0, float("nan"), float("nan")]})
    assert _compound_window_benchmark(frame, "bench") is None


def test_compound_window_benchmark_returns_none_for_missing_column() -> None:
    frame = pd.DataFrame({"other": [0.0, 0.01, 0.02]})
    assert _compound_window_benchmark(frame, "bench") is None
    assert _compound_window_benchmark(frame, None) is None


def test_compound_window_benchmark_returns_none_for_too_few_rows() -> None:
    frame = pd.DataFrame({"bench": [0.05]})
    assert _compound_window_benchmark(frame, "bench") is None


# ---------------------------------------------------------------------------
# _excess_return_series_from_history: when no cash column is available, the
# function returns an empty series (Sharpe will fall back to the rate-based
# computation). When cash data exists but has gaps within the window, missing
# observations are filled with 0% (excess-vol stays computable).
# ---------------------------------------------------------------------------


def test_excess_return_series_empty_when_no_cash_column() -> None:
    portfolio_returns = pd.Series(
        [0.01, 0.02, -0.01],
        index=pd.to_datetime(["2026-01-02", "2026-01-03", "2026-01-04"]),
        dtype=float,
    )
    history = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-01-02", "2026-01-03", "2026-01-04"]),
            "nav_eod_usd": [100.0, 101.0, 100.0],
        }
    )

    excess = _excess_return_series_from_history(
        history=history,
        currency="USD",
        portfolio_daily_returns=portfolio_returns,
    )

    assert excess.empty


def test_excess_return_series_fills_missing_cash_with_zero() -> None:
    dates = pd.to_datetime(["2026-01-02", "2026-01-03", "2026-01-04"])
    portfolio_returns = pd.Series([0.01, 0.02, -0.01], index=dates, dtype=float)
    history = pd.DataFrame(
        {
            "date": dates,
            "bench_bil_return_usd": [0.0001, float("nan"), 0.0002],
        }
    )

    excess = _excess_return_series_from_history(
        history=history,
        currency="USD",
        portfolio_daily_returns=portfolio_returns,
    )

    # NaN on day 2 → 0 cash → excess = portfolio return unchanged.
    assert excess.iloc[0] == pytest.approx(0.01 - 0.0001)
    assert excess.iloc[1] == pytest.approx(0.02 - 0.0)
    assert excess.iloc[2] == pytest.approx(-0.01 - 0.0002)


def test_excess_return_series_empty_when_portfolio_returns_empty() -> None:
    history = pd.DataFrame({"date": [], "bench_bil_return_usd": []})
    excess = _excess_return_series_from_history(
        history=history,
        currency="USD",
        portfolio_daily_returns=pd.Series(dtype=float),
    )
    assert excess.empty
