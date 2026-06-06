"""Earnings-date feed → :class:`~.contracts.EventRisk` (best-effort, graceful).

The option engine's ``EventRisk`` was always ``'unverified'`` — nothing populated
it. This adds a lightweight next-earnings lookup (yfinance, already an optional
dependency) so an idea whose expiry **spans the next earnings print** gets flagged
in the per-idea audit trail (``event_risk`` filter) and nudged down by the
ranking's event-safety term. Any network/parse failure or missing data degrades
to ``None`` (caller keeps ``'unverified'``) rather than raising.

Read-only: only reads public earnings calendars. The pure
:func:`event_risk_from_dates` core is unit-tested without any network.
"""

from __future__ import annotations

import datetime as _dt

from .contracts import EventRisk


def event_risk_from_dates(symbol: str, dates, *, today: _dt.date | None = None) -> EventRisk:
    """Build an :class:`EventRisk` from candidate earnings dates (pure, no network).

    Picks the nearest date on/after ``today``. Empty / all-past → ``'none'``.
    """
    today = today or _dt.date.today()
    future = sorted(d for d in dates if d is not None and d >= today)
    if not future:
        return EventRisk(symbol=symbol, event_status="none")
    nxt = future[0]
    return EventRisk(
        symbol=symbol,
        next_earnings_date=nxt.isoformat(),
        days_to_earnings=(nxt - today).days,
        event_status="known",
    )


def _to_date(value) -> _dt.date | None:
    """Coerce a pandas Timestamp / datetime / date / ISO string → ``date`` (or None)."""
    if value is None:
        return None
    if isinstance(value, _dt.datetime):
        return value.date()
    if isinstance(value, _dt.date):
        return value
    to_date = getattr(value, "date", None)  # pandas Timestamp et al.
    if callable(to_date):
        try:
            return to_date()
        except Exception:  # noqa: BLE001
            return None
    try:
        return _dt.date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _yf_earnings_dates(symbol: str) -> list[_dt.date]:
    """Best-effort earnings dates via yfinance (``get_earnings_dates`` → ``calendar``)."""
    import yfinance as yf  # lazy: optional dependency

    tk = yf.Ticker(symbol)
    dates: list[_dt.date] = []

    try:  # richest source of *future* prints
        df = tk.get_earnings_dates(limit=16)
        if df is not None and not df.empty:
            dates.extend(d for d in (_to_date(idx) for idx in df.index) if d is not None)
    except Exception:  # noqa: BLE001
        pass

    if not dates:  # fall back to the calendar (dict in new yfinance, DataFrame in old)
        try:
            cal = tk.calendar
            raw = []
            if isinstance(cal, dict):
                raw = cal.get("Earnings Date") or []
                if not isinstance(raw, (list, tuple)):
                    raw = [raw]
            else:
                try:
                    raw = list(cal.loc["Earnings Date"].values)
                except Exception:  # noqa: BLE001
                    raw = []
            dates.extend(d for d in (_to_date(v) for v in raw) if d is not None)
        except Exception:  # noqa: BLE001
            pass

    return dates


def fetch_earnings(symbol: str, *, today: _dt.date | None = None) -> EventRisk | None:
    """Next-earnings :class:`EventRisk` via yfinance, or ``None`` on any failure."""
    try:
        dates = _yf_earnings_dates(symbol)
    except Exception:  # noqa: BLE001 — never let an events lookup sink a scan
        return None
    if not dates:
        return None
    return event_risk_from_dates(symbol, dates, today=today)
