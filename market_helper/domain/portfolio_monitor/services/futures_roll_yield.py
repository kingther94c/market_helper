"""Two-contract roll yield for held futures — the first honest slice of carry.

For each held **month-coded** contract (``NGQ26``) we find the *next liquid*
contract on the root's liquid-months cycle, quote both via Yahoo's
month-contract symbols (``NGQ26.NYM``), and compute the annualized roll yield

    roll_yield_ann = ln(F_held / F_next) × 365 / Δdays(delivery anchors)

**positive = backwardation** (the curve pays a long to roll), **negative =
contango** (rolling a long costs). This is deliberately a *two-contract slice*
for **held roots only** — not the GSCI F1/F7 deferred-carry view, which stays
blocked on a full forward curve (see ``futures_roll_calendar``'s honest note).

Pure math + an injectable quote ``fetcher`` (the default Yahoo fetcher lives in
the application layer so this module stays network-free and hermetic to test).
Contracts without a parseable month code (``ZN``'s "10Y US", FX futures) are
skipped with a reason, never guessed.
"""

from __future__ import annotations

import datetime as _dt
import math
from typing import Any, Callable

from .futures_roll_calendar import (
    MONTH_CODES,
    SCHEDULE_GSCI,
    FuturesRollConfig,
    parse_contract_month,
)

_CODE_BY_MONTH = {v: k for k, v in MONTH_CODES.items()}
ALL_MONTHS = "FGHJKMNQUVXZ"
QUARTERLY_MONTHS = "HMUZ"

# Yahoo month-contract symbol suffix by IBKR exchange label.
YAHOO_EXCH_SUFFIX = {
    "NYMEX": "NYM",
    "CME": "CME",
    "GLOBEX": "CME",
    "CBOT": "CBT",
    "ECBOT": "CBT",
    "COMEX": "CMX",
    "NYBOT": "NYB",
    "ICE": "NYB",
}

QuoteFetcher = Callable[[str], "float | None"]


def liquid_months_for(root: str, config: FuturesRollConfig | None) -> str:
    """The root's liquid delivery-month cycle (config override, else by schedule)."""
    cfg = (config.for_root(root) if config is not None else {}) or {}
    months = str(cfg.get("liquid_months") or "").upper()
    if months and all(m in MONTH_CODES for m in months):
        return months
    schedule = str(cfg.get("schedule", "")).lower()
    return ALL_MONTHS if schedule == SCHEDULE_GSCI else QUARTERLY_MONTHS


def next_liquid_contract(root: str, contract: str, liquid_months: str) -> "tuple[str, int, int] | None":
    """``(next_contract_code, year, month)`` after the held contract on the cycle.

    ``None`` when the held contract has no parseable month code — never guessed.
    """
    parsed = parse_contract_month(root, contract)
    if parsed is None or not liquid_months:
        return None
    year, month = parsed
    ordered = sorted(MONTH_CODES[m] for m in liquid_months)
    nxt = next((m for m in ordered if m > month), None)
    if nxt is None:
        year, nxt = year + 1, ordered[0]
    return f"{root.upper()}{_CODE_BY_MONTH[nxt]}{year % 100:02d}", year, nxt


def yahoo_contract_symbol(root: str, contract_code: str, exchange: str) -> str | None:
    """``NGU26`` on NYMEX → ``NGU26.NYM``; unknown exchange → ``None`` (skip)."""
    suffix = YAHOO_EXCH_SUFFIX.get((exchange or "").upper())
    if not suffix:
        return None
    return f"{contract_code.upper()}.{suffix}"


def annualized_roll_yield(
    held_px: float, next_px: float, held_ym: "tuple[int, int]", next_ym: "tuple[int, int]"
) -> "float | None":
    """``ln(F_held/F_next) × 365/Δdays`` between the two delivery-month anchors."""
    if held_px <= 0 or next_px <= 0:
        return None
    days = (_dt.date(next_ym[0], next_ym[1], 1) - _dt.date(held_ym[0], held_ym[1], 1)).days
    if days <= 0:
        return None
    return math.log(held_px / next_px) * 365.0 / days


def compute_roll_yields(
    held_futures: list[dict],
    *,
    config: FuturesRollConfig | None = None,
    fetcher: QuoteFetcher,
) -> list[dict[str, Any]]:
    """One row per held month-coded contract: the two-contract roll yield.

    Skips (with a reason) anything without a month code or a Yahoo-mappable
    exchange; a failed quote degrades that row, never the batch. De-duplicates
    by (root, contract) so a position split across rows quotes once.
    """
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    quote_cache: dict[str, float | None] = {}

    def _quote(symbol: str) -> "float | None":
        if symbol not in quote_cache:
            try:
                quote_cache[symbol] = fetcher(symbol)
            except Exception:  # noqa: BLE001 — one bad quote never sinks the batch
                quote_cache[symbol] = None
        return quote_cache[symbol]

    for fut in held_futures or []:
        root = str(fut.get("root", "") or "").upper()
        contract = str(fut.get("contract", "") or "").upper()
        exchange = str(fut.get("exchange", "") or "")
        if not root or (root, contract) in seen:
            continue
        seen.add((root, contract))

        held_ym = parse_contract_month(root, contract)
        if held_ym is None:
            rows.append({"root": root, "held_contract": contract or "—", "status": "skipped",
                         "note": "no month code on the position — cannot identify the curve point"})
            continue
        months = liquid_months_for(root, config)
        nxt = next_liquid_contract(root, contract, months)
        if nxt is None:
            rows.append({"root": root, "held_contract": contract, "status": "skipped",
                         "note": "no liquid-month cycle configured"})
            continue
        next_code, next_year, next_month = nxt
        sym_held = yahoo_contract_symbol(root, contract if contract.startswith(root) else f"{root}{contract}", exchange)
        sym_next = yahoo_contract_symbol(root, next_code, exchange)
        if not sym_held or not sym_next:
            rows.append({"root": root, "held_contract": contract, "next_contract": next_code,
                         "status": "skipped", "note": f"exchange {exchange or '?'} has no Yahoo mapping"})
            continue

        held_px = _quote(sym_held)
        next_px = _quote(sym_next)
        if held_px is None or next_px is None:
            missing = sym_held if held_px is None else sym_next
            rows.append({"root": root, "held_contract": contract, "next_contract": next_code,
                         "status": "no_quote", "note": f"no quote for {missing}"})
            continue

        ann = annualized_roll_yield(held_px, next_px, held_ym, (next_year, next_month))
        rows.append({
            "root": root,
            "held_contract": contract,
            "next_contract": next_code,
            "held_px": round(held_px, 4),
            "next_px": round(next_px, 4),
            "roll_yield_ann": (round(ann, 4) if ann is not None else None),
            "curve": ("backwardation" if ann is not None and ann > 0 else
                      "contango" if ann is not None and ann < 0 else "flat"),
            "yahoo_symbols": [sym_held, sym_next],
            "status": "ok",
            "note": "two-contract slice (held vs next liquid) — not the full F1/F7 curve",
        })
    return rows
