from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from market_helper.data_sources.yahoo_finance import YahooFinanceClient
from market_helper.domain.portfolio_monitor.services.benchmark_history import (
    attach_benchmark_returns,
    compound_returns_with_fx,
    refresh_benchmark_returns_in_history_feather,
)
from market_helper.domain.portfolio_monitor.services.nav_cashflow_history import (
    NAV_CASHFLOW_HISTORY_COLUMNS,
    load_nav_cashflow_history,
)
from market_helper.domain.portfolio_monitor.services.performance_analytics import (
    percent_cumulative_plot_frame,
)
from market_helper.domain.portfolio_monitor.services.yahoo_returns import (
    clear_session_yahoo_cache,
)


def test_compound_returns_with_fx_zero_fx_move_passes_usd_through() -> None:
    returns_usd = pd.Series([np.nan, 0.01, 0.02, -0.005])
    fx = pd.Series([1.30, 1.30, 1.30, 1.30])
    result = compound_returns_with_fx(returns_usd=returns_usd, fx_sgd_per_usd=fx)
    assert pd.isna(result.iloc[0])
    # First valid row: pct_change of FX is 0, so SGD == USD return.
    assert result.iloc[1] == pytest.approx(0.01, abs=1e-12)
    assert result.iloc[2] == pytest.approx(0.02, abs=1e-12)
    assert result.iloc[3] == pytest.approx(-0.005, abs=1e-12)


def test_compound_returns_with_fx_compounds_fx_appreciation_on_top_of_usd() -> None:
    # USD return +1.0%, FX moves 1.30 → 1.3130 (USD strengthens 1.0% vs SGD).
    # Combined SGD return for an SGD-base SPY holder ≈ 1.01 * 1.01 - 1 = 2.01%.
    returns_usd = pd.Series([np.nan, 0.01])
    fx = pd.Series([1.30, 1.3130])
    result = compound_returns_with_fx(returns_usd=returns_usd, fx_sgd_per_usd=fx)
    assert result.iloc[1] == pytest.approx(1.01 * 1.01 - 1.0, abs=1e-12)


def test_compound_returns_with_fx_propagates_nan_for_missing_inputs() -> None:
    returns_usd = pd.Series([np.nan, 0.01, np.nan, 0.02])
    fx = pd.Series([1.30, 1.31, 1.31, np.nan])
    result = compound_returns_with_fx(returns_usd=returns_usd, fx_sgd_per_usd=fx)
    assert pd.isna(result.iloc[0])
    assert not pd.isna(result.iloc[1])
    assert pd.isna(result.iloc[2])  # missing USD return
    assert pd.isna(result.iloc[3])  # missing FX → pct_change NaN


def test_attach_benchmark_returns_aligns_to_history_dates_and_fills_sgd(tmp_path: Path) -> None:
    history = _build_minimal_history(
        rows=[
            # date, nav_usd, fx
            ("2025-01-02", 100.0, 1.30),
            ("2025-01-03", 101.0, 1.31),
            ("2025-01-06", 103.0, 1.32),
        ],
    )
    spy_prices = [
        ("2025-01-02", 600.0),
        ("2025-01-03", 606.0),  # +1.0%
        ("2025-01-06", 612.06),  # +1.0%
    ]
    yahoo = _fake_yahoo_spy_client(spy_prices)

    enriched = attach_benchmark_returns(
        history,
        yahoo_client=yahoo,
        cache_dir=tmp_path / "yahoo_cache",
    )

    # USD column: first row NaN (no prior price), then ~+1% twice.
    assert pd.isna(enriched.iloc[0]["bench_spy_return_usd"])
    assert enriched.iloc[1]["bench_spy_return_usd"] == pytest.approx(0.01, abs=1e-9)
    assert enriched.iloc[2]["bench_spy_return_usd"] == pytest.approx(0.01, abs=1e-9)

    # SGD column compounds FX moves: 1.30 → 1.31 (+0.769%), 1.31 → 1.32 (+0.763%).
    expected_sgd_row1 = (1.0 + 0.01) * (1.31 / 1.30) - 1.0
    expected_sgd_row2 = (1.0 + 0.01) * (1.32 / 1.31) - 1.0
    assert enriched.iloc[1]["bench_spy_return_sgd"] == pytest.approx(expected_sgd_row1, abs=1e-9)
    assert enriched.iloc[2]["bench_spy_return_sgd"] == pytest.approx(expected_sgd_row2, abs=1e-9)


def test_attach_benchmark_returns_leaves_nan_when_yahoo_missing_dates(tmp_path: Path) -> None:
    history = _build_minimal_history(
        rows=[
            ("2025-01-02", 100.0, 1.30),
            ("2025-01-03", 101.0, 1.31),  # SPY missing for this date below
            ("2025-01-06", 103.0, 1.32),
        ],
    )
    spy_prices = [
        ("2025-01-02", 600.0),
        ("2025-01-06", 612.0),
    ]
    yahoo = _fake_yahoo_spy_client(spy_prices)
    enriched = attach_benchmark_returns(
        history,
        yahoo_client=yahoo,
        cache_dir=tmp_path / "yahoo_cache",
    )
    assert pd.isna(enriched.iloc[1]["bench_spy_return_usd"])
    assert pd.isna(enriched.iloc[1]["bench_spy_return_sgd"])


def test_refresh_benchmark_returns_in_history_feather_round_trips(tmp_path: Path) -> None:
    history_path = tmp_path / "nav_cashflow_history.feather"
    history = _build_minimal_history(
        rows=[
            ("2025-01-02", 100.0, 1.30),
            ("2025-01-03", 101.0, 1.31),
            ("2025-01-06", 103.0, 1.32),
        ],
    )
    history.loc[:, NAV_CASHFLOW_HISTORY_COLUMNS].reset_index(drop=True).to_feather(history_path)

    yahoo = _fake_yahoo_spy_client(
        [
            ("2025-01-02", 600.0),
            ("2025-01-03", 606.0),
            ("2025-01-06", 612.06),
        ]
    )
    refresh_benchmark_returns_in_history_feather(
        history_path,
        yahoo_client=yahoo,
        cache_dir=tmp_path / "yahoo_cache",
    )

    reloaded = load_nav_cashflow_history(history_path)
    assert "bench_spy_return_usd" in reloaded.columns
    assert "bench_spy_return_sgd" in reloaded.columns
    assert reloaded.iloc[1]["bench_spy_return_usd"] == pytest.approx(0.01, abs=1e-9)


def test_percent_cumulative_plot_frame_includes_benchmark_when_column_present() -> None:
    # Synthetic history: portfolio +1% per day, SPY +0.5% per day. After 3
    # observations the benchmark cumulative curve should be ~1.005^2 - 1.
    history = pd.DataFrame(
        {
            "date": pd.to_datetime(["2025-01-02", "2025-01-03", "2025-01-06"]),
            "nav_eod_usd": [100.0, 101.0, 102.01],
            "pnl_usd": [None, 0.01, 0.01],
            "is_final": [True, True, True],
            "bench_spy_return_usd": [None, 0.005, 0.005],
        }
    )
    frame = percent_cumulative_plot_frame(history, "USD", include_provisional=True)
    assert "bench_cumulative_return" in frame.columns
    assert frame.iloc[0]["bench_cumulative_return"] == pytest.approx(0.0, abs=1e-12)
    assert frame.iloc[-1]["bench_cumulative_return"] == pytest.approx(1.005 * 1.005 - 1.0, abs=1e-9)


def test_percent_cumulative_plot_frame_omits_benchmark_when_column_absent() -> None:
    history = pd.DataFrame(
        {
            "date": pd.to_datetime(["2025-01-02", "2025-01-03", "2025-01-06"]),
            "nav_eod_usd": [100.0, 101.0, 102.01],
            "pnl_usd": [None, 0.01, 0.01],
            "is_final": [True, True, True],
        }
    )
    frame = percent_cumulative_plot_frame(history, "USD", include_provisional=True)
    assert "bench_cumulative_return" not in frame.columns


def _build_minimal_history(*, rows: list[tuple[str, float, float]]) -> pd.DataFrame:
    dates = [pd.Timestamp(row[0]) for row in rows]
    nav_usd = [row[1] for row in rows]
    fx = [row[2] for row in rows]
    nav_sgd = [usd * fx_rate for usd, fx_rate in zip(nav_usd, fx, strict=True)]
    return pd.DataFrame(
        {
            "date": dates,
            "nav_eod_usd": nav_usd,
            "cashflow_usd": [0.0] * len(rows),
            "fx_usdsgd_eod": fx,
            "nav_eod_sgd": nav_sgd,
            "cashflow_sgd": [0.0] * len(rows),
            "is_final": [True] * len(rows),
            "pnl_amt_usd": [0.0] * len(rows),
            "pnl_amt_sgd": [0.0] * len(rows),
            "pnl_usd": [0.0] * len(rows),
            "pnl_sgd": [0.0] * len(rows),
            "source_kind": ["test"] * len(rows),
            "source_file": ["test.xml"] * len(rows),
            "source_as_of": pd.to_datetime([row[0] for row in rows]),
            "bench_spy_return_usd": [None] * len(rows),
            "bench_spy_return_sgd": [None] * len(rows),
        }
    )


def _fake_yahoo_spy_client(prices: list[tuple[str, float]]) -> YahooFinanceClient:
    clear_session_yahoo_cache()
    return YahooFinanceClient(
        downloader=lambda _url: {
            "chart": {
                "result": [
                    {
                        "meta": {"currency": "USD"},
                        "timestamp": [
                            int(datetime.strptime(raw_date, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp())
                            for raw_date, _ in prices
                        ],
                        "indicators": {
                            "quote": [{"close": [price for _, price in prices]}],
                            "adjclose": [{"adjclose": [price for _, price in prices]}],
                        },
                    }
                ]
            }
        }
    )
