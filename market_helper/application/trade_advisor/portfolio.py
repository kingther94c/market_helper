"""Seed an :class:`AdvisorContext` from the real portfolio positions CSV.

Classifies each row by its ``internal_id`` prefix:

* ``STK:`` → a stock holding (``{symbol: shares}``) and counts toward funded AUM.
* ``CASH`` → counts toward funded AUM.
* ``OPT:`` / ``OUTSIDE_SCOPE:OPT:`` (or any row with option Greeks columns) →
  a held option (parsed from the ``option_*`` columns + the OSI ``local_symbol``).
* ``FUT:`` / other → excluded from AUM, holdings, and options.

Funded AUM is **stock-like + cash only** (excludes options/futures), per the
existing risk gotcha. Read-only: it only reads the artifact.
"""

from __future__ import annotations

import csv
import math
from pathlib import Path

from market_helper.app.paths import PORTFOLIO_ARTIFACTS_DIR
from market_helper.domain.option_advisor.providers import parse_occ_symbol
from market_helper.trade_advisor.contracts import AdvisorContext

DEFAULT_POSITIONS_CSV = PORTFOLIO_ARTIFACTS_DIR / "live_ibkr_position_report.csv"


def _f(value) -> float | None:
    try:
        if value is None or value == "":
            return None
        x = float(value)
        return x if math.isfinite(x) else None
    except (TypeError, ValueError):
        return None


def _is_option_row(row: dict, iid: str) -> bool:
    return (
        iid.startswith("OPT:")
        or ":OPT:" in iid
        or bool((row.get("option_greeks_status") or "").strip())
        or bool((row.get("option_underlying_symbol") or "").strip())
    )


def _parse_option_row(row: dict) -> dict | None:
    local = (row.get("local_symbol") or "").replace(" ", "")
    underlying = (row.get("option_underlying_symbol") or "").strip()
    try:
        root, expiry, right, strike = parse_occ_symbol(local)
    except Exception:
        return None  # unparseable OSI → skip rather than mislead
    return {
        "underlying": underlying or root,
        "right": right,
        "strike": strike,
        "expiry": expiry,
        "qty": _f(row.get("quantity")) or 0.0,
        "underlying_price": _f(row.get("option_underlying_price")),
        "delta": _f(row.get("option_delta")),
        "iv": _f(row.get("option_implied_vol")),
    }


def context_from_positions_csv(
    path: str | Path | None = None,
    *,
    watchlist: list[str] | None = None,
    regime_label: str = "",
    regime_confidence: str = "",
    crisis_flag: bool = False,
) -> AdvisorContext:
    """Build an AdvisorContext from a positions CSV (defaults to the live book).

    Returns an empty-but-valid context when the file is missing — the caller
    degrades to a watchlist-only scan rather than failing.
    """
    csv_path = Path(path) if path else DEFAULT_POSITIONS_CSV
    holdings: dict[str, float] = {}
    held_options: list[dict] = []
    held_futures: list[dict] = []
    aum = 0.0
    as_of = ""

    if csv_path.exists():
        with csv_path.open(newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                iid = (row.get("internal_id") or "").strip()
                symbol = (row.get("symbol") or "").strip()
                qty = _f(row.get("quantity"))
                mv = _f(row.get("market_value"))
                as_of = as_of or (row.get("as_of") or "")
                if _is_option_row(row, iid):
                    opt = _parse_option_row(row)
                    if opt:
                        held_options.append(opt)
                elif iid.startswith("STK:"):
                    if symbol and qty:
                        holdings[symbol] = holdings.get(symbol, 0.0) + qty
                    if mv:
                        aum += mv
                elif iid.startswith("CASH"):
                    if mv:
                        aum += mv
                elif iid.startswith("FUT:"):
                    # Futures are excluded from funded AUM (the sizing gotcha) but DO need
                    # roll/carry management — collect them for the Roll & Carry Calendar.
                    held_futures.append({
                        "root": symbol,
                        "contract": (row.get("local_symbol") or "").strip(),
                        "internal_id": iid,
                        "exchange": (row.get("exchange") or "").strip(),
                        "qty": qty or 0.0,
                        "latest_price": _f(row.get("latest_price")),
                        "market_value": mv,
                    })
                # other → excluded

    return AdvisorContext(
        as_of=as_of,
        holdings=holdings,
        aum=(round(aum, 2) if aum else None),
        watchlist=list(watchlist or []),
        regime_label=regime_label,
        regime_confidence=regime_confidence,
        crisis_flag=crisis_flag,
        held_options=held_options,
        held_futures=held_futures,
    )
