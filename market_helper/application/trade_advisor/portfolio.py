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


# CME-style FX future roots whose economic exposure is to the FOREIGN currency even
# though the contract is USD-quoted (so a long 6A is AUD exposure, not USD).
_FX_FUTURE_CCYS = frozenset({"AUD", "EUR", "GBP", "JPY", "CNH", "CHF", "CAD", "NZD", "MXN", "SGD"})


def _currency_of_risk(iid: str, symbol: str, currency: str) -> str:
    """The currency a position is economically exposed to (coarse, honest).

    FX futures map to the foreign currency they track (the symbol); everything else
    maps to its quote/settlement currency. This is a listing-currency proxy — it does
    NOT look through a USD-listed ex-US fund to its underlying-asset currencies (that
    deeper lookthrough is a refinement).
    """
    if iid.startswith("FUT:") and symbol in _FX_FUTURE_CCYS:
        return symbol
    return (currency or "?").strip().upper() or "?"


def _currency_weights_for_row(iid: str, symbol: str, currency: str, *, manual, taxonomy) -> list[tuple[str, float]]:
    """``[(currency, weight), …]`` (weights sum to 1) for one position row.

    Equity rows are looked *through* to their underlying-country currencies via the
    country lookthrough (the deeper FX exposure); any uncovered remainder falls back to
    the listing currency. FX futures + cash/bonds keep their currency-of-risk.
    """
    if iid.startswith("STK:") and manual is not None:
        from market_helper.domain.portfolio_monitor.services.currency_lookthrough import (
            symbol_currency_weights,
        )

        weights = symbol_currency_weights(symbol, manual=manual, taxonomy=taxonomy)
        if weights:
            covered = sum(w for _c, w in weights)
            out = list(weights)
            if covered < 0.999:  # honest gap-fill: unresearched remainder → listing currency
                out.append((_currency_of_risk(iid, symbol, currency), 1.0 - covered))
            return out
    return [(_currency_of_risk(iid, symbol, currency), 1.0)]


def currency_exposure_from_positions_csv(
    path: str | Path | None = None,
    *,
    lookthrough: bool = True,
    manual: dict | None = None,
    taxonomy: dict | None = None,
) -> dict:
    """Per-currency economic exposure of the live book.

    Sums ``|market_value|`` by currency-of-risk across stock / cash / futures rows
    (options excluded). FX futures count toward the foreign currency they track. With
    ``lookthrough`` (default), equities are looked *through* to their underlying-country
    currencies via the country lookthrough — so a USD-listed ex-US fund contributes
    JPY/EUR/AUD/… rather than all USD. ``manual`` / ``taxonomy`` are injectable for tests;
    when omitted (and ``lookthrough``) the maintained country lookthrough CSVs are loaded.
    Returns ``{"by_currency": [(ccy, usd, weight), …] desc, "total_usd", "as_of",
    "n_positions", "lookthrough": bool, "fx_overlay_by_currency": {ccy: {"usd":
    signed_notional, "qty": signed_contracts}}}``; empty when the file is missing.
    The overlay is the FX-futures slice kept *signed* — what the FX Hedge decision
    panel diffs against the target hedge legs.
    """
    csv_path = Path(path) if path else DEFAULT_POSITIONS_CSV
    if lookthrough and manual is None:
        from market_helper.domain.portfolio_monitor.services.currency_lookthrough import (
            load_country_manual,
            load_country_taxonomy,
        )

        manual = load_country_manual()
        taxonomy = taxonomy if taxonomy is not None else load_country_taxonomy()
    if not lookthrough:
        manual = None

    by_ccy: dict[str, float] = {}
    fx_overlay: dict[str, dict[str, float]] = {}
    total = 0.0
    as_of = ""
    n = 0
    if csv_path.exists():
        with csv_path.open(newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                iid = (row.get("internal_id") or "").strip()
                if _is_option_row(row, iid):
                    continue  # overlays, not a denominated exposure
                mv = _f(row.get("market_value"))
                if not mv:
                    continue
                as_of = as_of or (row.get("as_of") or "")
                symbol = (row.get("symbol") or "").strip()
                amt = abs(mv)
                for ccy, weight in _currency_weights_for_row(
                    iid, symbol, row.get("currency") or "",
                    manual=manual, taxonomy=taxonomy,
                ):
                    by_ccy[ccy] = by_ccy.get(ccy, 0.0) + amt * weight
                if iid.startswith("FUT:") and symbol in _FX_FUTURE_CCYS:
                    # The FX-futures overlay, kept SIGNED (mv is the signed notional;
                    # qty the signed contract count) — this is what the FX Hedge
                    # decision panel compares against the target hedge legs.
                    slot = fx_overlay.setdefault(symbol, {"usd": 0.0, "qty": 0.0})
                    slot["usd"] += mv
                    slot["qty"] += _f(row.get("quantity")) or 0.0
                total += amt
                n += 1
    ranked = sorted(by_ccy.items(), key=lambda kv: kv[1], reverse=True)
    return {
        "by_currency": [(c, round(v, 2), (v / total if total else 0.0)) for c, v in ranked],
        "total_usd": round(total, 2),
        "as_of": as_of,
        "n_positions": n,
        "lookthrough": bool(manual is not None),
        "fx_overlay_by_currency": {
            c: {"usd": round(v["usd"], 2), "qty": v["qty"]} for c, v in fx_overlay.items()
        },
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
