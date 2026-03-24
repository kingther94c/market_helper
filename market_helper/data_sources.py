from __future__ import annotations

from typing import Dict

import pandas as pd
import yfinance as yf


def _one_week_return_from_series(series: pd.Series) -> float:
    series = series.dropna()
    if len(series) < 6:
        raise ValueError("Not enough observations to compute 1W return")
    start = series.iloc[-6]
    end = series.iloc[-1]
    if start == 0:
        raise ValueError("Invalid start price (0)")
    return float(end / start - 1.0)


def fetch_recent_one_week_moves() -> Dict[str, float]:
    """Fetch recent daily data and derive 1W returns & spread proxies."""
    tickers = ["SPY", "IWM", "VWO", "VEA", "HYG", "LQD", "XLY", "XLP", "COPX", "USO", "TLT", "TIP", "IEF"]
    df = yf.download(tickers=tickers, period="1mo", interval="1d", auto_adjust=True, progress=False)

    if df.empty:
        raise RuntimeError("No data downloaded from Yahoo Finance")

    if isinstance(df.columns, pd.MultiIndex):
        closes = df["Close"]
    else:
        closes = df

    moves: Dict[str, float] = {}
    for ticker in tickers:
        if ticker in closes.columns:
            moves[ticker] = _one_week_return_from_series(closes[ticker])

    def rel(a: str, b: str, name: str) -> None:
        if a in moves and b in moves:
            moves[name] = moves[a] - moves[b]

    rel("IWM", "SPY", "IWM_vs_SPY")
    rel("VWO", "VEA", "VWO_vs_VEA")
    rel("HYG", "LQD", "HYG_vs_LQD")
    rel("XLY", "XLP", "XLY_vs_XLP")
    rel("TIP", "IEF", "TIP_vs_IEF")

    return moves
