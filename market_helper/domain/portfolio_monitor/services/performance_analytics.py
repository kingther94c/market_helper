from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pandas as pd

from market_helper.data_sources.ibkr.flex.performance import FlexNavPoint, _calculate_period_irr_return
from market_helper.domain.portfolio_monitor.services.performance_history import load_performance_history
from market_helper.domain.portfolio_monitor.services.volatility import (
    DEFAULT_ANNUALIZATION_FACTOR,
    historical_vol,
)

ANNUALIZATION_FACTOR = float(DEFAULT_ANNUALIZATION_FACTOR)
MAX_DAILY_GAP_DAYS = 10
MIN_DAILY_OBSERVATIONS = 5
MIN_DAILY_COVERAGE_RATIO = 0.6


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
    if series.empty:
        return pd.Series(dtype=float)
    series.index = pd.to_datetime(frame.loc[series.index, "date"], errors="coerce")
    return pd.Series(series.to_numpy(dtype=float), index=series.index, dtype=float)


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
) -> float | None:
    metrics = calculate_window_metrics(
        history,
        currency,
        include_provisional=include_provisional,
    )
    return metrics.annualized_return


def annualized_vol(
    history: pd.DataFrame,
    currency: str,
    *,
    include_provisional: bool = False,
) -> float | None:
    metrics = calculate_window_metrics(
        history,
        currency,
        include_provisional=include_provisional,
    )
    return metrics.annualized_vol


def sharpe_ratio(
    history: pd.DataFrame,
    currency: str,
    *,
    risk_free_rate_annual: float = 0.0,
    include_provisional: bool = False,
) -> float | None:
    metrics = calculate_window_metrics(
        history,
        currency,
        include_provisional=include_provisional,
        risk_free_rate_annual=risk_free_rate_annual,
    )
    return metrics.sharpe_ratio


def drawdown_series(
    history: pd.DataFrame,
    currency: str,
    *,
    include_provisional: bool = False,
) -> pd.Series:
    frame = percent_cumulative_plot_frame(
        history,
        currency,
        include_provisional=include_provisional,
    )
    if frame.empty:
        return pd.Series(dtype=float)
    return pd.Series(frame["drawdown"].to_numpy(dtype=float), index=pd.to_datetime(frame["date"]), dtype=float)


def percent_cumulative_plot_frame(
    history: pd.DataFrame,
    currency: str,
    *,
    include_provisional: bool = False,
) -> pd.DataFrame:
    frame = _select_history(history, include_provisional=include_provisional)
    return _percent_frame_from_history(frame, currency)


def percent_drawdown_plot_frame(
    history: pd.DataFrame,
    currency: str,
    *,
    include_provisional: bool = False,
) -> pd.DataFrame:
    frame = percent_cumulative_plot_frame(
        history,
        currency,
        include_provisional=include_provisional,
    )
    if frame.empty:
        return pd.DataFrame(columns=["date", "drawdown"])
    return frame.loc[:, ["date", "drawdown"]].copy()


def dollar_cumulative_plot_frame(
    history: pd.DataFrame,
    currency: str,
    *,
    include_provisional: bool = False,
) -> pd.DataFrame:
    frame = _select_history(history, include_provisional=include_provisional)
    return _dollar_frame_from_history(frame, currency)


def dollar_drawdown_plot_frame(
    history: pd.DataFrame,
    currency: str,
    *,
    include_provisional: bool = False,
) -> pd.DataFrame:
    frame = dollar_cumulative_plot_frame(
        history,
        currency,
        include_provisional=include_provisional,
    )
    if frame.empty:
        return pd.DataFrame(columns=["date", "drawdown"])
    return frame.loc[:, ["date", "drawdown"]].copy()


def performance_plot_frame(
    history: pd.DataFrame,
    currency: str,
    *,
    include_provisional: bool = False,
) -> pd.DataFrame:
    frame = percent_cumulative_plot_frame(
        history,
        currency,
        include_provisional=include_provisional,
    )
    if frame.empty:
        return pd.DataFrame(columns=["date", "level"])
    output = frame.loc[:, ["date", "cumulative_return"]].copy()
    output = output.rename(columns={"cumulative_return": "level"})
    return output


def drawdown_plot_frame(
    history: pd.DataFrame,
    currency: str,
    *,
    include_provisional: bool = False,
) -> pd.DataFrame:
    return percent_drawdown_plot_frame(
        history,
        currency,
        include_provisional=include_provisional,
    )


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
            require_daily_coverage=True,
        )
        secondary_twr = None
        secondary_mwr = None
        if secondary_currency is not None:
            secondary_metrics = _calculate_metrics_from_frame(
                year_frame,
                secondary_currency,
                risk_free_rate_annual=risk_free_rate_annual,
                require_daily_coverage=True,
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
    for column in ("summary_cash_flow_usd", "summary_cash_flow_sgd"):
        if column not in frame.columns:
            frame[column] = pd.NA
    return frame.sort_values("date", kind="stable").reset_index(drop=True)


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
    require_daily_coverage: bool = False,
) -> dict[str, float | None]:
    if history.empty:
        return _empty_metrics()

    nav_col = _nav_column(currency)
    flow_col = _flow_column(currency)
    summary_flow_col = _summary_flow_column(currency)
    return_col = _return_column(currency)
    available = history.loc[
        history[nav_col].notna(),
        ["date", nav_col, flow_col, summary_flow_col, return_col],
    ].copy()
    if len(available) < 2:
        return _empty_metrics()

    returns = pd.to_numeric(available.iloc[1:][return_col], errors="coerce")
    twr_return = None if returns.empty or returns.isna().all() else float((1.0 + returns.fillna(0.0)).prod() - 1.0)
    mwr_return = _mwr_return_from_window(available, currency)

    valid_returns = pd.to_numeric(available.iloc[1:][return_col], errors="coerce").dropna()
    daily_returns = pd.Series(
        valid_returns.to_numpy(dtype=float),
        index=pd.to_datetime(available.loc[valid_returns.index, "date"], errors="coerce"),
        dtype=float,
    )
    has_daily_coverage = _has_trustworthy_daily_coverage(daily_returns)
    if require_daily_coverage and not has_daily_coverage:
        return {
            "twr_return": twr_return,
            "mwr_return": mwr_return,
            "annualized_return": None,
            "annualized_vol": None,
            "sharpe_ratio": None,
            "max_drawdown": None,
        }

    ann_return = _annualized_return_from_returns(daily_returns) if has_daily_coverage else None
    ann_vol = _annualized_vol_from_returns(daily_returns) if has_daily_coverage else None
    sharpe = None if ann_return is None or ann_vol is None or ann_vol <= 0 else float((ann_return - risk_free_rate_annual) / ann_vol)
    drawdown = _max_drawdown_from_returns(daily_returns) if has_daily_coverage else None

    return {
        "twr_return": twr_return,
        "mwr_return": mwr_return,
        "annualized_return": ann_return,
        "annualized_vol": ann_vol,
        "sharpe_ratio": sharpe,
        "max_drawdown": drawdown,
    }


def _percent_frame_from_history(history: pd.DataFrame, currency: str) -> pd.DataFrame:
    nav_col = _nav_column(currency)
    return_col = _return_column(currency)
    available = history.loc[history[nav_col].notna(), ["date", nav_col, return_col]].copy().reset_index(drop=True)
    if len(available) < 2:
        return pd.DataFrame(columns=["date", "cumulative_return", "drawdown"])

    returns = pd.to_numeric(available.iloc[1:][return_col], errors="coerce")
    valid_returns = returns.dropna()
    if valid_returns.empty:
        return pd.DataFrame(columns=["date", "cumulative_return", "drawdown"])

    first_valid_idx = int(valid_returns.index[0])
    opening_date = pd.to_datetime(available.loc[first_valid_idx - 1, "date"], errors="coerce")
    return_dates = pd.to_datetime(available.loc[valid_returns.index, "date"], errors="coerce")
    levels = pd.Series([1.0], index=[opening_date], dtype=float)
    compounded = (1.0 + pd.Series(valid_returns.to_numpy(dtype=float), index=return_dates, dtype=float)).cumprod()
    levels = pd.concat([levels, compounded])
    peaks = levels.cummax()
    frame = pd.DataFrame(
        {
            "date": pd.to_datetime(levels.index),
            "cumulative_return": levels.to_numpy(dtype=float) - 1.0,
            "drawdown": (levels / peaks - 1.0).to_numpy(dtype=float),
        }
    )
    return frame.reset_index(drop=True)


def _dollar_frame_from_history(history: pd.DataFrame, currency: str) -> pd.DataFrame:
    nav_col = _nav_column(currency)
    flow_col = _flow_column(currency)
    available = history.loc[history[nav_col].notna(), ["date", nav_col, flow_col]].copy()
    if len(available) < 2:
        return pd.DataFrame(columns=["date", "cumulative_pnl", "drawdown"])

    start_nav = float(available.iloc[0][nav_col])
    flows = pd.to_numeric(available.iloc[1:][flow_col], errors="coerce").fillna(0.0)
    dates = pd.to_datetime(available["date"], errors="coerce")
    pnl_values = [0.0]
    cumulative_flow = 0.0
    for flow, (_, row) in zip(flows, available.iloc[1:].iterrows(), strict=False):
        cumulative_flow += float(flow)
        pnl_values.append(float(row[nav_col]) - start_nav - cumulative_flow)
    pnl = pd.Series(pnl_values, index=dates, dtype=float)
    drawdown = pnl - pnl.cummax()
    return pd.DataFrame(
        {
            "date": pd.to_datetime(pnl.index),
            "cumulative_pnl": pnl.to_numpy(dtype=float),
            "drawdown": drawdown.to_numpy(dtype=float),
        }
    ).reset_index(drop=True)


def _mwr_return_from_window(history: pd.DataFrame, currency: str) -> float | None:
    nav_col = _nav_column(currency)
    flow_col = _flow_column(currency)
    summary_flow_col = _summary_flow_column(currency)
    available = history.loc[history[nav_col].notna(), ["date", nav_col, flow_col, summary_flow_col]].copy()
    if len(available) < 2:
        return None
    nav_points = [
        FlexNavPoint(date=pd.Timestamp(row["date"]).date(), nav=float(row[nav_col]))
        for _, row in available.iterrows()
    ]
    flow_schedule: dict[date, float] = {}
    has_summary_only_flows = False
    for row_date, flow_amount, summary_amount in zip(
        available.iloc[1:]["date"],
        pd.to_numeric(available.iloc[1:][flow_col], errors="coerce"),
        pd.to_numeric(available.iloc[1:][summary_flow_col], errors="coerce"),
        strict=False,
    ):
        if not pd.isna(flow_amount) and abs(float(flow_amount)) > 1e-12:
            flow_schedule[pd.Timestamp(row_date).date()] = float(flow_amount)
        if not pd.isna(summary_amount) and abs(float(summary_amount)) > 1e-12:
            has_summary_only_flows = True
    if has_summary_only_flows:
        return None
    return _calculate_period_irr_return(nav_points, flow_schedule)


def _has_trustworthy_daily_coverage(returns: pd.Series) -> bool:
    clean = pd.Series(pd.to_numeric(returns, errors="coerce").dropna(), dtype=float)
    if len(clean) < MIN_DAILY_OBSERVATIONS:
        return False
    sorted_index = pd.DatetimeIndex(pd.to_datetime(clean.index)).sort_values()
    business_days = pd.bdate_range(sorted_index.min(), sorted_index.max())
    if len(business_days) == 0:
        return False
    coverage_ratio = len(sorted_index) / len(business_days)
    max_gap = 0 if len(sorted_index) < 2 else int(sorted_index.to_series().diff().dropna().dt.days.max())
    return bool(coverage_ratio >= MIN_DAILY_COVERAGE_RATIO and max_gap <= MAX_DAILY_GAP_DAYS)


def _annualized_return_from_returns(returns: pd.Series) -> float | None:
    clean = pd.Series(pd.to_numeric(returns, errors="coerce").dropna(), dtype=float)
    if clean.empty:
        return None
    total_return = float((1.0 + clean).prod() - 1.0)
    return float((1.0 + total_return) ** (ANNUALIZATION_FACTOR / len(clean)) - 1.0)


def _annualized_vol_from_returns(returns: pd.Series) -> float | None:
    clean = pd.Series(pd.to_numeric(returns, errors="coerce").dropna(), dtype=float)
    if len(clean) < 2:
        return None
    return float(historical_vol(returns=clean, return_method="simple", annualization_factor=ANNUALIZATION_FACTOR))


def _max_drawdown_from_returns(returns: pd.Series) -> float | None:
    clean = pd.Series(pd.to_numeric(returns, errors="coerce").dropna(), dtype=float)
    if clean.empty:
        return None
    levels = (1.0 + clean).cumprod()
    drawdown = levels / levels.cummax() - 1.0
    return float(drawdown.min())


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


def _summary_flow_column(currency: str) -> str:
    normalized = currency.strip().upper()
    if normalized not in {"USD", "SGD"}:
        raise ValueError(f"Unsupported currency: {currency}")
    return f"summary_cash_flow_{normalized.lower()}"


def _return_column(currency: str) -> str:
    normalized = currency.strip().upper()
    if normalized not in {"USD", "SGD"}:
        raise ValueError(f"Unsupported currency: {currency}")
    return f"twr_return_{normalized.lower()}"
