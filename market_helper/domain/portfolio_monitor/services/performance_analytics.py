from __future__ import annotations

from pathlib import Path

import pandas as pd

from market_helper.domain.portfolio_monitor.services.performance_history import load_performance_history
from market_helper.domain.portfolio_monitor.services.volatility import historical_vol


def finalized_history(history: pd.DataFrame) -> pd.DataFrame:
    return history.loc[history["is_final"].fillna(False)].copy().reset_index(drop=True)


def latest_history(history: pd.DataFrame) -> pd.DataFrame:
    return history.copy().reset_index(drop=True)


def build_daily_twr_returns(
    history: pd.DataFrame,
    currency: str,
    *,
    include_provisional: bool = False,
) -> pd.Series:
    frame = _select_history(history, include_provisional=include_provisional)
    column = _return_column(currency)
    series = pd.to_numeric(frame[column], errors="coerce").dropna()
    series.index = pd.to_datetime(frame.loc[series.index, "date"], errors="coerce")
    return series


def build_twr_index(
    history: pd.DataFrame,
    currency: str,
    *,
    include_provisional: bool = False,
    base_level: float = 1.0,
) -> pd.Series:
    returns = build_daily_twr_returns(
        history,
        currency,
        include_provisional=include_provisional,
    )
    if returns.empty:
        return pd.Series(dtype=float)
    levels = (1.0 + returns).cumprod() * float(base_level)
    levels.name = f"twr_index_{currency.lower()}"
    return levels


def annualized_return(
    history: pd.DataFrame,
    currency: str,
    *,
    include_provisional: bool = False,
) -> float:
    frame = _select_history(history, include_provisional=include_provisional)
    nav_col = _nav_column(currency)
    available = frame.loc[frame[nav_col].notna(), ["date", nav_col]]
    if len(available) < 2:
        return 0.0
    start_date = pd.Timestamp(available.iloc[0]["date"]).date()
    end_date = pd.Timestamp(available.iloc[-1]["date"]).date()
    total_days = max((end_date - start_date).days, 1)
    start_nav = float(available.iloc[0][nav_col])
    end_nav = float(available.iloc[-1][nav_col])
    if start_nav <= 0 or end_nav <= 0:
        return 0.0
    total_return = end_nav / start_nav
    return float(total_return ** (365.25 / total_days) - 1.0)


def annualized_vol(
    history: pd.DataFrame,
    currency: str,
    *,
    include_provisional: bool = False,
) -> float:
    returns = build_daily_twr_returns(
        history,
        currency,
        include_provisional=include_provisional,
    )
    if returns.empty:
        return 0.0
    return float(historical_vol(returns=returns, return_method="simple"))


def sharpe_ratio(
    history: pd.DataFrame,
    currency: str,
    *,
    risk_free_rate_annual: float = 0.0,
    include_provisional: bool = False,
) -> float:
    ann_return = annualized_return(
        history,
        currency,
        include_provisional=include_provisional,
    )
    ann_vol = annualized_vol(
        history,
        currency,
        include_provisional=include_provisional,
    )
    if ann_vol <= 0:
        return 0.0
    return float((ann_return - float(risk_free_rate_annual)) / ann_vol)


def drawdown_series(
    history: pd.DataFrame,
    currency: str,
    *,
    include_provisional: bool = False,
) -> pd.Series:
    index = build_twr_index(
        history,
        currency,
        include_provisional=include_provisional,
    )
    if index.empty:
        return pd.Series(dtype=float)
    peaks = index.cummax()
    drawdown = index / peaks - 1.0
    drawdown.name = f"drawdown_{currency.lower()}"
    return drawdown


def performance_plot_frame(
    history: pd.DataFrame,
    currency: str,
    *,
    include_provisional: bool = False,
) -> pd.DataFrame:
    index = build_twr_index(
        history,
        currency,
        include_provisional=include_provisional,
    )
    if index.empty:
        return pd.DataFrame(columns=["date", "level"])
    return pd.DataFrame({"date": index.index, "level": index.to_numpy(dtype=float)})


def drawdown_plot_frame(
    history: pd.DataFrame,
    currency: str,
    *,
    include_provisional: bool = False,
) -> pd.DataFrame:
    series = drawdown_series(
        history,
        currency,
        include_provisional=include_provisional,
    )
    if series.empty:
        return pd.DataFrame(columns=["date", "drawdown"])
    return pd.DataFrame({"date": series.index, "drawdown": series.to_numpy(dtype=float)})


def load_performance_history_frame(path: str | Path) -> pd.DataFrame:
    return load_performance_history(path)


def _select_history(history: pd.DataFrame, *, include_provisional: bool) -> pd.DataFrame:
    if include_provisional:
        frame = latest_history(history)
    else:
        frame = finalized_history(history)
    frame = frame.sort_values("date", kind="stable").reset_index(drop=True)
    return frame


def _nav_column(currency: str) -> str:
    normalized = currency.strip().upper()
    if normalized not in {"USD", "SGD"}:
        raise ValueError(f"Unsupported currency: {currency}")
    return f"nav_close_{normalized.lower()}"


def _return_column(currency: str) -> str:
    normalized = currency.strip().upper()
    if normalized not in {"USD", "SGD"}:
        raise ValueError(f"Unsupported currency: {currency}")
    return f"twr_return_{normalized.lower()}"
