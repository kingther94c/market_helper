"""Signal layer: assemble an :class:`~.contracts.UnderlyingContext` per symbol.

Pulls together what's known about an underlying — spot, realized-vol term
structure, ATM IV + IV rank (from the chain), trend, regime, and any held
position — into one frozen record the candidate rules consume. Best-effort:
realized vol / trend come from a lightweight price pull and degrade to ``None``
on failure rather than blocking the advisor.
"""

from __future__ import annotations

import datetime as _dt

from . import earnings as _earnings
from .contracts import ChainSnapshot, EventRisk, RealizedVolMetrics, UnderlyingContext


def realized_vol_and_trend(symbol: str) -> dict | None:
    """Annualized realized-vol term structure + a simple SMA trend, via yfinance.

    Returns ``None`` on any failure (no network, symbol miss, etc.).
    """
    try:
        import numpy as np
        import yfinance as yf

        hist = yf.Ticker(symbol).history(period="1y")
        if hist is None or hist.empty or "Close" not in hist:
            return None
        close = hist["Close"].to_numpy(dtype=float)
        if close.size < 25:
            return None
        logret = np.diff(np.log(close))

        def ann(n: int) -> float | None:
            seg = logret[-n:]
            return float(np.std(seg, ddof=1) * np.sqrt(252)) if seg.size > 2 else None

        sma50 = float(close[-50:].mean()) if close.size >= 50 else float(close.mean())
        sma200 = float(close[-200:].mean()) if close.size >= 200 else None
        last = float(close[-1])
        if sma200 is not None:
            trend = "up" if last > sma50 > sma200 else "down" if last < sma50 < sma200 else "chop"
        else:
            trend = "up" if last > sma50 else "down"
        return {
            "vol_1m": ann(21),
            "vol_3m": ann(63),
            "vol_6m": ann(126),
            "vol_1y": ann(252),
            "trend": trend,
        }
    except Exception:
        return None


def build_context(
    symbol: str,
    chain: ChainSnapshot,
    *,
    internal_id: str | None = None,
    held_qty: float = 0.0,
    held_delta_exposure_usd: float | None = None,
    weight: float = 0.0,
    sector: str = "",
    asset_class: str = "EQ",
    dir_exposure: str = "L",
    regime_label: str = "",
    regime_confidence: str = "",
    crisis_flag: bool = False,
    fetch_realized: bool = True,
    realized: RealizedVolMetrics | None = None,
    fetch_events: bool = False,
    event_risk: EventRisk | None = None,
    event_override_date: str | None = None,
) -> UnderlyingContext:
    """Assemble the context. ``realized`` / ``event_risk`` can be injected (tests);
    otherwise they're fetched best-effort when their ``fetch_*`` flag is set.

    Earnings precedence: an explicit ``event_risk`` wins, then a user-supplied
    ``event_override_date`` (ISO ``YYYY-MM-DD``), then a best-effort feed pull
    (only when ``fetch_events`` is set). Anything unavailable leaves it ``None``
    (the filter then reads 'earnings unverified')."""
    rv = realized
    trend = "unknown"
    if rv is None and fetch_realized:
        info = realized_vol_and_trend(symbol)
        if info:
            rv = RealizedVolMetrics(
                symbol=symbol, as_of=chain.as_of,
                vol_1m=info["vol_1m"], vol_3m=info["vol_3m"],
                vol_6m=info["vol_6m"], vol_1y=info["vol_1y"],
            )
            trend = info["trend"]

    er = event_risk
    if er is None and event_override_date:
        try:
            od = _dt.date.fromisoformat(event_override_date)
            er = _earnings.event_risk_from_dates(symbol, [od])
        except ValueError:
            er = None
    if er is None and fetch_events:
        er = _earnings.fetch_earnings(symbol)

    atm_iv = chain.atm_iv
    rv_ref = (rv.vol_1m if rv else None) or (chain.realized_vol)
    rv_iv_ratio = (rv_ref / atm_iv) if (rv_ref and atm_iv and atm_iv > 0) else None

    return UnderlyingContext(
        internal_id=internal_id or f"STK:{symbol}:SMART",
        symbol=symbol,
        as_of=chain.as_of,
        spot=chain.spot,
        realized_vol=rv,
        atm_iv=atm_iv,
        iv_rank=chain.iv_rank,
        rv_iv_ratio=rv_iv_ratio,
        trend_state=trend,
        regime_label=regime_label,
        regime_confidence=regime_confidence,
        crisis_flag=crisis_flag,
        held_qty=held_qty,
        held_delta_exposure_usd=held_delta_exposure_usd,
        weight=weight,
        sector=sector,
        asset_class=asset_class,
        dir_exposure=dir_exposure,
        event_risk=er,
    )
