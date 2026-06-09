"""Bounded inputs + pure context builders for `/advisor` (unit-tested).

The universe and regime/confidence option sets are fixed, validated lists — there
is no free-form input because there is no AI to interpret it. ``build_context`` /
``build_run_context`` map those bounded inputs to an ``AdvisorContext`` shared by
both the rule-based and AI+ tabs.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from market_helper.application.trade_advisor import context_from_positions_csv
from market_helper.trade_advisor.contracts import AdvisorContext

# Bounded option sets — the universe is a fixed, validated list (no free text).
# LIQUID_UNIVERSE is the liquid default subset; the full option-scannable universe
# is loaded from configs/security_universe.csv (see load_option_universe).
LIQUID_UNIVERSE = [
    "SPY", "QQQ", "IWM", "DIA", "XLK", "XLF", "XLE",
    "AAPL", "MSFT", "NVDA", "TSLA", "AMZN", "GOOGL", "META",
]
REGIME_OPTIONS = ["", "Goldilocks", "Reflation", "Stagflation", "Deflationary Slowdown"]
CONFIDENCE_OPTIONS = ["", "High", "Medium", "Low"]


def load_option_universe(path=None) -> list[str]:
    """US-listed EQ tickers from ``configs/security_universe.csv`` (option-scannable).

    The v2 Option module scans the *security universe* rather than a hardcoded
    14-name list. We keep only equity STK rows that are US-listed (an option chain
    is fetchable), drop ``.L`` London listings, and surface the liquid names first.
    Falls back to ``LIQUID_UNIVERSE`` if the CSV is unreadable.
    """
    import csv

    from market_helper.app.paths import CONFIGS_DIR

    csv_path = path or (CONFIGS_DIR / "security_universe.csv")
    try:
        with open(csv_path, newline="", encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
    except (OSError, csv.Error):
        return list(LIQUID_UNIVERSE)

    scannable: list[str] = []
    for row in rows:
        if (row.get("asset_class") or "").strip().upper() != "EQ":
            continue
        if (row.get("sec_type") or "").strip().upper() != "STK":
            continue
        if (row.get("yahoo_symbol") or "").strip().upper().endswith(".L"):
            continue  # London listing — no US option chain
        sym = (row.get("ibkr_symbol") or "").strip().upper()
        if sym and sym not in scannable:
            scannable.append(sym)
    if not scannable:
        return list(LIQUID_UNIVERSE)
    # Liquid names first (stable, good defaults), then the rest of the universe.
    liquid = [s for s in LIQUID_UNIVERSE if s in scannable]
    rest = [s for s in scannable if s not in liquid]
    return liquid + rest


@dataclass
class AdvisorInputs:
    symbols: list[str] = field(default_factory=lambda: ["SPY", "QQQ"])
    held: list[str] = field(default_factory=lambda: ["SPY"])
    aum: float = 250_000.0
    regime: str = ""
    confidence: str = ""
    crisis: bool = False
    fetch_realized: bool = False
    check_earnings: bool = False


def build_context(inp: AdvisorInputs) -> AdvisorContext:
    """Map bounded inputs → AdvisorContext. Held = 100 sh each (∩ chosen universe)."""
    holdings = {s: 100.0 for s in inp.held if s in inp.symbols}
    watchlist = [s for s in inp.symbols if s not in holdings]
    return AdvisorContext(
        holdings=holdings,
        aum=float(inp.aum or 0.0),
        watchlist=watchlist,
        regime_label=inp.regime or "",
        regime_confidence=inp.confidence or "",
        crisis_flag=bool(inp.crisis),
    )


def option_run_params(inp: AdvisorInputs) -> dict:
    return {
        "option": {"fetch_realized": bool(inp.fetch_realized), "fetch_events": bool(inp.check_earnings)},
        # Pull the external Tactical Edge daily brief when present (offline + graceful if absent).
        "tactical": {"include_edge": True},
    }


def build_run_context(inp: AdvisorInputs, *, use_portfolio: bool) -> tuple[AdvisorContext, str]:
    """Resolve the advisor context (+ a short book note) from bounded inputs.

    ``use_portfolio`` seeds held stock/options + funded AUM from the live
    positions CSV (degrading to a watchlist-only scan when none is found);
    otherwise the manual Universe / Held / AUM controls are used. Shared by the
    rule-based and AI+ tabs so both see the same book.
    """
    if use_portfolio:
        from dataclasses import replace as _replace

        context = context_from_positions_csv(
            watchlist=inp.symbols, regime_label=inp.regime,
            regime_confidence=inp.confidence, crisis_flag=inp.crisis,
        )
        if context.aum is None:
            context = _replace(context, aum=inp.aum)
        book_note = (
            f" · book: {len(context.holdings)} stk / {len(context.held_options)} opt"
            if (context.holdings or context.held_options)
            else " · no live positions found (watchlist only)"
        )
        return context, book_note
    return build_context(inp), ""
