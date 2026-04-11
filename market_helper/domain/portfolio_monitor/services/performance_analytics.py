from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pandas as pd

from market_helper.data_sources.ibkr.flex.performance import FlexNavPoint, _calculate_period_irr_return
from market_helper.domain.portfolio_monitor.services.performance_history import load_performance_history
from market_helper.domain.portfolio_monitor.services.volatility import historical_vol


@dataclass(frozen=True)
class PerformanceMetricRow:
    label: str
    twr_return: float | None
    mwr_return: float | None
    annualized_return: float | None
    annualized_vol: float | None
    sharpe_ratio: float | None
    max_drawdown: float | None
    secondary_twr_return: float | None = None
    secondary_mwr_return: float | None = None


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
    metrics = calculate_window_metrics(
        history,
        currency,
        include_provisional=include_provisional,
    )
    return float(metrics.twr_return or 0.0) if metrics.annualized_return is None else float(metrics.annualized_return)


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
    metrics = calculate_window_metrics(
        history,
        currency,
        include_provisional=include_provisional,
        risk_free_rate_annual=risk_free_rate_annual,
    )
    return float(metrics.sharpe_ratio or 0.0)


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


def slice_history_for_window(
    history: pd.DataFrame,
    *,
    window: str,
    include_provisional: bool = False,
    calendar_year: int | None = None,
) -> pd.DataFrame:
    frame = _select_history(history, include_provisional=include_provisional)
    if frame.empty:
        return frame

    end_ts = pd.Timestamp(frame["date"].max())
    normalized_window = window.strip().upper()
    if normalized_window == "FULL":
        return frame
    if normalized_window == "MTD":
        start_ts = pd.Timestamp(date(end_ts.year, end_ts.month, 1))
        return _window_with_opening(frame, start_ts=start_ts, end_ts=end_ts)
    if normalized_window == "YTD":
        start_ts = pd.Timestamp(date(end_ts.year, 1, 1))
        return _window_with_opening(frame, start_ts=start_ts, end_ts=end_ts)
    if normalized_window in {"1Y", "3Y", "5Y"}:
        years = int(normalized_window[:-1])
        start_ts = end_ts - pd.DateOffset(years=years)
        return _window_with_opening(frame, start_ts=start_ts, end_ts=end_ts)
    if normalized_window == "YEAR":
        if calendar_year is None:
            raise ValueError("calendar_year is required when window='YEAR'")
        year_rows = frame.loc[frame["date"].dt.year == int(calendar_year)].copy()
        if year_rows.empty:
            return year_rows
        start_ts = pd.Timestamp(date(int(calendar_year), 1, 1))
        end_year_ts = pd.Timestamp(year_rows["date"].max())
        if not bool(year_rows.iloc[-1]["is_final"]):
            return frame.iloc[0:0].copy()
        return _window_with_opening(frame, start_ts=start_ts, end_ts=end_year_ts)
    raise ValueError(f"Unsupported performance window: {window}")


def calculate_window_metrics(
    history: pd.DataFrame,
    currency: str,
    *,
    include_provisional: bool = False,
    risk_free_rate_annual: float = 0.0,
) -> PerformanceMetricRow:
    frame = _select_history(history, include_provisional=include_provisional)
    metrics = _calculate_metrics_from_frame(
        frame,
        currency,
        risk_free_rate_annual=risk_free_rate_annual,
    )
    return PerformanceMetricRow(
        label="FULL",
        twr_return=metrics["twr_return"],
        mwr_return=metrics["mwr_return"],
        annualized_return=metrics["annualized_return"],
        annualized_vol=metrics["annualized_vol"],
        sharpe_ratio=metrics["sharpe_ratio"],
        max_drawdown=metrics["max_drawdown"],
    )


def build_window_metric_row(
    history: pd.DataFrame,
    *,
    window: str,
    primary_currency: str,
    secondary_currency: str | None = None,
    include_provisional: bool = False,
    risk_free_rate_annual: float = 0.0,
) -> PerformanceMetricRow:
    normalized_window = window.upper()
    source_frame = _select_history(history, include_provisional=include_provisional)
    frame = slice_history_for_window(
        history,
        window=normalized_window,
        include_provisional=include_provisional,
    )
    if _window_requires_full_coverage(normalized_window) and not _window_has_full_coverage(source_frame, normalized_window):
        primary_metrics = _empty_metrics()
    else:
        primary_metrics = _calculate_metrics_from_frame(
            frame,
            primary_currency,
            risk_free_rate_annual=risk_free_rate_annual,
        )
    secondary_twr = None
    secondary_mwr = None
    if secondary_currency is not None:
        secondary_metrics = (
            _empty_metrics()
            if _window_requires_full_coverage(normalized_window) and not _window_has_full_coverage(source_frame, normalized_window)
            else _calculate_metrics_from_frame(
                frame,
                secondary_currency,
                risk_free_rate_annual=risk_free_rate_annual,
            )
        )
        secondary_twr = secondary_metrics["twr_return"]
        secondary_mwr = secondary_metrics["mwr_return"]
    return PerformanceMetricRow(
        label=normalized_window,
        twr_return=primary_metrics["twr_return"],
        mwr_return=primary_metrics["mwr_return"],
        annualized_return=primary_metrics["annualized_return"],
        annualized_vol=primary_metrics["annualized_vol"],
        sharpe_ratio=primary_metrics["sharpe_ratio"],
        max_drawdown=primary_metrics["max_drawdown"],
        secondary_twr_return=secondary_twr,
        secondary_mwr_return=secondary_mwr,
    )


def build_yearly_metric_rows(
    history: pd.DataFrame,
    *,
    primary_currency: str,
    secondary_currency: str | None = None,
    risk_free_rate_annual: float = 0.0,
) -> list[PerformanceMetricRow]:
    frame = finalized_history(history)
    if frame.empty:
        return []
    as_of = pd.Timestamp(frame["date"].max())
    rows: list[PerformanceMetricRow] = []
    for year in sorted(int(value) for value in frame["date"].dt.year.unique() if int(value) < int(as_of.year)):
        year_frame = slice_history_for_window(
            frame,
            window="YEAR",
            calendar_year=year,
        )
        if year_frame.empty:
            continue
        primary_metrics = _calculate_metrics_from_frame(
            year_frame,
            primary_currency,
            risk_free_rate_annual=risk_free_rate_annual,
        )
        if primary_metrics["twr_return"] is None:
            continue
        secondary_twr = None
        secondary_mwr = None
        if secondary_currency is not None:
            secondary_metrics = _calculate_metrics_from_frame(
                year_frame,
                secondary_currency,
                risk_free_rate_annual=risk_free_rate_annual,
            )
            secondary_twr = secondary_metrics["twr_return"]
            secondary_mwr = secondary_metrics["mwr_return"]
        rows.append(
            PerformanceMetricRow(
                label=str(year),
                twr_return=primary_metrics["twr_return"],
                mwr_return=primary_metrics["mwr_return"],
                annualized_return=primary_metrics["annualized_return"],
                annualized_vol=primary_metrics["annualized_vol"],
                sharpe_ratio=primary_metrics["sharpe_ratio"],
                max_drawdown=primary_metrics["max_drawdown"],
                secondary_twr_return=secondary_twr,
                secondary_mwr_return=secondary_mwr,
            )
        )
    return rows


def _select_history(history: pd.DataFrame, *, include_provisional: bool) -> pd.DataFrame:
    if include_provisional:
        frame = latest_history(history)
    else:
        frame = finalized_history(history)
    frame = frame.sort_values("date", kind="stable").reset_index(drop=True)
    return frame


def _window_with_opening(history: pd.DataFrame, *, start_ts: pd.Timestamp, end_ts: pd.Timestamp) -> pd.DataFrame:
    eligible = history.loc[history["date"] <= end_ts].copy()
    if eligible.empty:
        return eligible
    opening = eligible.loc[eligible["date"] < start_ts].tail(1)
    in_window = eligible.loc[eligible["date"] >= start_ts]
    if opening.empty:
        return in_window.reset_index(drop=True)
    return pd.concat([opening, in_window], ignore_index=True)


def _window_requires_full_coverage(window: str) -> bool:
    return window in {"1Y", "3Y", "5Y"}


def _window_has_full_coverage(history: pd.DataFrame, window: str) -> bool:
    if history.empty or not _window_requires_full_coverage(window):
        return True
    end_ts = pd.Timestamp(history["date"].max())
    years = int(window[:-1])
    target_start = end_ts - pd.DateOffset(years=years)
    first_ts = pd.Timestamp(history["date"].min())
    return bool(first_ts <= target_start)


def _calculate_metrics_from_frame(
    history: pd.DataFrame,
    currency: str,
    *,
    risk_free_rate_annual: float,
) -> dict[str, float | None]:
    if history.empty:
        return _empty_metrics()

    nav_col = _nav_column(currency)
    flow_col = _flow_column(currency)
    return_col = _return_column(currency)
    available = history.loc[history[nav_col].notna(), ["date", nav_col, flow_col, return_col]].copy()
    if len(available) < 2:
        return _empty_metrics()

    start_ts = pd.Timestamp(available.iloc[0]["date"])
    end_ts = pd.Timestamp(available.iloc[-1]["date"])
    total_days = max((end_ts.date() - start_ts.date()).days, 1)
    start_nav = float(available.iloc[0][nav_col])
    end_nav = float(available.iloc[-1][nav_col])
    if start_nav <= 0:
        return _empty_metrics()

    returns = pd.to_numeric(available.iloc[1:][return_col], errors="coerce")
    twr_return = None if returns.empty or returns.isna().all() else float((1.0 + returns.fillna(0.0)).prod() - 1.0)
    ann_return = None
    if twr_return is not None:
        ann_return = float((1.0 + twr_return) ** (365.25 / total_days) - 1.0)

    flow_schedule: dict[date, float] = {}
    cash_flows = pd.to_numeric(available.iloc[1:][flow_col], errors="coerce")
    for row_date, raw_amount in zip(available.iloc[1:]["date"], cash_flows, strict=False):
        if pd.isna(raw_amount) or abs(float(raw_amount)) <= 1e-12:
            continue
        flow_schedule[pd.Timestamp(row_date).date()] = float(raw_amount)

    nav_points = [
        FlexNavPoint(date=pd.Timestamp(row["date"]).date(), nav=float(row[nav_col]))
        for _, row in available.iterrows()
    ]
    mwr_return = _calculate_period_irr_return(nav_points, flow_schedule)

    window_history = history.loc[history["date"].isin(available["date"])].copy()
    ann_vol = _annualized_vol_from_frame(window_history, currency)
    drawdown = _max_drawdown_from_frame(window_history, currency)
    sharpe = None if ann_return is None or ann_vol is None or ann_vol <= 0 else float((ann_return - risk_free_rate_annual) / ann_vol)

    return {
        "twr_return": twr_return,
        "mwr_return": mwr_return,
        "annualized_return": ann_return,
        "annualized_vol": ann_vol,
        "sharpe_ratio": sharpe,
        "max_drawdown": drawdown,
    }


def _annualized_vol_from_frame(history: pd.DataFrame, currency: str) -> float | None:
    returns = build_daily_twr_returns(history, currency, include_provisional=True)
    if returns.empty:
        return None
    return float(historical_vol(returns=returns, return_method="simple"))


def _max_drawdown_from_frame(history: pd.DataFrame, currency: str) -> float | None:
    series = drawdown_series(history, currency, include_provisional=True)
    if series.empty:
        return None
    return float(series.min())


def _empty_metrics() -> dict[str, float | None]:
    return {
        "twr_return": None,
        "mwr_return": None,
        "annualized_return": None,
        "annualized_vol": None,
        "sharpe_ratio": None,
        "max_drawdown": None,
    }


def _nav_column(currency: str) -> str:
    normalized = currency.strip().upper()
    if normalized not in {"USD", "SGD"}:
        raise ValueError(f"Unsupported currency: {currency}")
    return f"nav_close_{normalized.lower()}"


def _flow_column(currency: str) -> str:
    normalized = currency.strip().upper()
    if normalized not in {"USD", "SGD"}:
        raise ValueError(f"Unsupported currency: {currency}")
    return f"cash_flow_{normalized.lower()}"


def _return_column(currency: str) -> str:
    normalized = currency.strip().upper()
    if normalized not in {"USD", "SGD"}:
        raise ValueError(f"Unsupported currency: {currency}")
    return f"twr_return_{normalized.lower()}"
