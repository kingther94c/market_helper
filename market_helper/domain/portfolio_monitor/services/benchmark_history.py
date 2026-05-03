from __future__ import annotations

from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd

from market_helper.data_sources.yahoo_finance import YahooFinanceClient

from .nav_cashflow_history import (
    NAV_CASHFLOW_HISTORY_COLUMNS,
    load_nav_cashflow_history,
)
from .yahoo_returns import (
    DEFAULT_YAHOO_RETURNS_CACHE_DIR,
    ensure_symbol_return_cache,
)


# The benchmark layer keeps a single SPY column today; structured as a dict so
# adding (e.g.) AGG or 60/40 later only touches `BENCHMARK_RETURN_SOURCES` and
# the schema additions in `nav_cashflow_history.py`.
BENCHMARK_RETURN_SOURCES: dict[str, str] = {
    "SPY": "bench_spy_return_usd",
}
BENCHMARK_SGD_COLUMNS: dict[str, str] = {
    "SPY": "bench_spy_return_sgd",
}
DEFAULT_BENCHMARK_PERIOD = "max"


def attach_benchmark_returns(
    history: pd.DataFrame,
    *,
    yahoo_client: YahooFinanceClient,
    cache_dir: str | Path = DEFAULT_YAHOO_RETURNS_CACHE_DIR,
    symbols: Iterable[str] = ("SPY",),
    force_refresh: bool = False,
) -> pd.DataFrame:
    """Fill the `bench_*_return_{usd,sgd}` columns on a NAV/cashflow history frame.

    USD return = simple daily return of the symbol's adjusted close (derived
    from the existing log-return Yahoo cache). SGD return uses the frame's own
    `fx_usdsgd_eod` column to compound the FX move on top of the USD return:

        r_sgd_t = (1 + r_usd_t) * (fx_t / fx_{t-1}) - 1
    """
    if history.empty:
        return history.copy()

    enriched = history.copy()
    enriched["date"] = pd.to_datetime(enriched["date"], errors="coerce")

    for symbol in symbols:
        usd_column = BENCHMARK_RETURN_SOURCES.get(symbol)
        sgd_column = BENCHMARK_SGD_COLUMNS.get(symbol)
        if usd_column is None or sgd_column is None:
            raise ValueError(f"Benchmark symbol {symbol!r} not registered in BENCHMARK_RETURN_SOURCES")

        cache = ensure_symbol_return_cache(
            symbol,
            yahoo_client=yahoo_client,
            cache_dir=cache_dir,
            period=DEFAULT_BENCHMARK_PERIOD,
            force_refresh=force_refresh,
        )
        usd_returns_simple = _log_returns_to_simple(cache.series)
        usd_returns_simple = usd_returns_simple.rename(usd_column)
        usd_returns_simple.index = pd.to_datetime(usd_returns_simple.index).normalize()
        usd_returns_aligned = usd_returns_simple.reindex(enriched["date"].dt.normalize().to_numpy())
        enriched[usd_column] = usd_returns_aligned.to_numpy(dtype=float)

        enriched[sgd_column] = compound_returns_with_fx(
            returns_usd=enriched[usd_column],
            fx_sgd_per_usd=enriched["fx_usdsgd_eod"],
        ).to_numpy(dtype=float)

    return enriched


def refresh_benchmark_returns_in_history_feather(
    path: str | Path,
    *,
    yahoo_client: YahooFinanceClient,
    cache_dir: str | Path = DEFAULT_YAHOO_RETURNS_CACHE_DIR,
    symbols: Iterable[str] = ("SPY",),
    force_refresh: bool = False,
) -> Path:
    """Load `nav_cashflow_history.feather`, fill benchmark columns, write back.

    Idempotent: the Yahoo cache is reused across calls (incremental thanks to
    `ensure_symbol_return_cache`'s staleness check). Overwrites the same
    feather path so downstream readers see the new columns immediately.
    """
    target_path = Path(path)
    history = load_nav_cashflow_history(target_path)
    enriched = attach_benchmark_returns(
        history,
        yahoo_client=yahoo_client,
        cache_dir=cache_dir,
        symbols=symbols,
        force_refresh=force_refresh,
    )
    enriched.loc[:, NAV_CASHFLOW_HISTORY_COLUMNS].reset_index(drop=True).to_feather(target_path)
    return target_path


def compound_returns_with_fx(
    *,
    returns_usd: pd.Series,
    fx_sgd_per_usd: pd.Series,
) -> pd.Series:
    """Convert a USD-denominated daily return series into the SGD equivalent.

    `fx_sgd_per_usd` is the same `fx_usdsgd_eod` column used elsewhere in the
    feather (units: SGD per 1 USD). Daily FX return is `fx_t / fx_{t-1} - 1`;
    the SGD-base return is `(1 + r_usd) * (1 + r_fx) - 1`. NaN inputs propagate
    so missing benchmark/FX days stay NaN downstream rather than silently
    becoming zero.
    """
    fx_numeric = pd.to_numeric(fx_sgd_per_usd, errors="coerce")
    # `fill_method=None` keeps NaN FX days as NaN-returns rather than padding
    # forward; otherwise a missing FX would silently get last-observed values.
    fx_return = fx_numeric.pct_change(fill_method=None)
    usd_numeric = pd.to_numeric(returns_usd, errors="coerce")
    return (1.0 + usd_numeric) * (1.0 + fx_return) - 1.0


def benchmark_return_column(symbol: str, currency: str) -> str:
    normalized_currency = currency.strip().upper()
    if normalized_currency == "USD":
        column = BENCHMARK_RETURN_SOURCES.get(symbol)
    elif normalized_currency == "SGD":
        column = BENCHMARK_SGD_COLUMNS.get(symbol)
    else:
        raise ValueError(f"Unsupported currency for benchmark column lookup: {currency}")
    if column is None:
        raise ValueError(f"Benchmark symbol {symbol!r} not registered")
    return column


def _log_returns_to_simple(log_returns: pd.Series) -> pd.Series:
    if log_returns.empty:
        return pd.Series(dtype=float)
    return pd.Series(np.expm1(log_returns.to_numpy(dtype=float)), index=log_returns.index, dtype=float)


__all__ = [
    "BENCHMARK_RETURN_SOURCES",
    "BENCHMARK_SGD_COLUMNS",
    "DEFAULT_BENCHMARK_PERIOD",
    "attach_benchmark_returns",
    "benchmark_return_column",
    "compound_returns_with_fx",
    "refresh_benchmark_returns_in_history_feather",
]
