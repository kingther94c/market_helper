"""Option-chain data providers, tried in priority order with graceful fallback.

Priority (overridable):

1. **CBOE delayed JSON** (``cdn.cboe.com``) — stdlib ``urllib`` only, ships full
   greeks + IV + OI + volume per strike. No key. ~15-min delayed. Primary.
2. **yfinance** — broad coverage; no greeks, so they're computed locally via
   :mod:`.pricing`. Lazy-imported; skipped cleanly if unavailable.
3. **Synthetic** vol-surface — builds a plausible chain from ``spot`` + an ATM
   IV using a simple deterministic skew/term surface. The user can override
   ``spot`` and ``iv``; the anchor can also come from realized vol or a live
   IBKR snapshot. Always available — the advisor never hard-fails on data.

Every :class:`~.contracts.ChainSnapshot` is tagged with a ``data_mode`` so the
advisor can be honest about how real the numbers are.

Read-only by construction: these only GET public market data.
"""

from __future__ import annotations

import datetime as _dt
import json
import math
import urllib.error
import urllib.request
from dataclasses import replace

from . import pricing
from .contracts import (
    DATA_LIVE_ANCHORED,
    DATA_LIVE_CHAIN,
    DATA_SYNTHETIC,
    DATA_USER_OVERRIDE,
    ChainSnapshot,
    OptionQuote,
    VolSurfaceParams,
)

__all__ = [
    "parse_occ_symbol",
    "fetch_cboe_chain",
    "fetch_yfinance_chain",
    "build_synthetic_chain",
    "surface_iv",
    "get_chain",
    "ChainError",
]

# CBOE serves index options under an underscore-prefixed key.
_INDEX_SYMBOLS = frozenset({"SPX", "VIX", "NDX", "RUT", "XSP", "DJX", "OEX", "VX"})
_CBOE_URL = "https://cdn.cboe.com/api/global/delayed_quotes/options/{sym}.json"
_USER_AGENT = "Mozilla/5.0 (market_helper option-advisor; read-only research)"


class ChainError(RuntimeError):
    """Raised when no provider (including synthetic) can produce a chain."""


def _f(x) -> float | None:
    try:
        if x is None:
            return None
        v = float(x)
        return v if math.isfinite(v) else None
    except (TypeError, ValueError):
        return None


def _i(x) -> int | None:
    v = _f(x)
    return int(v) if v is not None else None


def _today() -> _dt.date:
    return _dt.date.today()


def _now_iso() -> str:
    return _dt.datetime.now().isoformat(timespec="seconds")


# --------------------------------------------------------------------------- #
# OCC symbol parsing
# --------------------------------------------------------------------------- #


def parse_occ_symbol(occ: str) -> tuple[str, str, str, float]:
    """Parse an OCC option symbol → ``(root, expiry_iso, right, strike)``.

    OCC layout: ``ROOT`` + ``YYMMDD`` + ``C|P`` + 8-digit strike×1000.
    The fixed suffix is always 15 chars, so the root is everything before it.
    Example: ``AAPL260619C00200000`` → ``("AAPL", "2026-06-19", "C", 200.0)``.
    """
    occ = occ.strip().replace(" ", "")
    suffix = occ[-15:]
    root = occ[:-15]
    yy, mm, dd = int(suffix[0:2]), int(suffix[2:4]), int(suffix[4:6])
    right = suffix[6].upper()
    strike = int(suffix[7:15]) / 1000.0
    expiry = _dt.date(2000 + yy, mm, dd).isoformat()
    return root, expiry, right, strike


def _within_filters(dte: int, strike: float, spot: float, dte_max: int | None, moneyness: float | None) -> bool:
    if dte < 0:
        return False
    if dte_max is not None and dte > dte_max:
        return False
    if moneyness is not None and spot > 0:
        if not (spot * (1.0 - moneyness) <= strike <= spot * (1.0 + moneyness)):
            return False
    return True


def _atm_iv_from_quotes(quotes: list[OptionQuote], spot: float) -> float | None:
    """ATM IV = average call/put IV at the nearest strike of the nearest expiry."""
    valid = [q for q in quotes if q.iv and q.iv > 0]
    if not valid or spot <= 0:
        return None
    nearest_exp = min({q.expiry for q in valid}, key=lambda e: min(q.dte for q in valid if q.expiry == e))
    same_exp = [q for q in valid if q.expiry == nearest_exp]
    atm_strike = min(same_exp, key=lambda q: abs(q.strike - spot)).strike
    at = [q.iv for q in same_exp if abs(q.strike - atm_strike) < 1e-6]
    return sum(at) / len(at) if at else None


# --------------------------------------------------------------------------- #
# CBOE (primary)
# --------------------------------------------------------------------------- #


def fetch_cboe_chain(
    symbol: str,
    *,
    dte_max: int | None = 120,
    moneyness: float | None = 0.25,
    rate: float = 0.04,
    dividend_yield: float = 0.0,
    timeout: float = 25.0,
) -> ChainSnapshot:
    """Fetch a live (≈15-min delayed) chain with greeks from CBOE's public JSON."""
    sym = symbol.upper()
    req_sym = ("_" + sym) if sym in _INDEX_SYMBOLS else sym
    url = _CBOE_URL.format(sym=req_sym)
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        payload = json.load(resp)

    data = payload.get("data") or {}
    spot = _f(data.get("current_price"))
    if spot is None or spot <= 0:
        raise ChainError(f"CBOE returned no usable spot for {sym}")

    quotes: list[OptionQuote] = []
    for o in data.get("options", []):
        try:
            _root, expiry, right, strike = parse_occ_symbol(o["option"])
        except Exception:
            continue
        dte = (_dt.date.fromisoformat(expiry) - _today()).days
        if not _within_filters(dte, strike, spot, dte_max, moneyness):
            continue
        quotes.append(
            OptionQuote(
                underlying=sym,
                expiry=expiry,
                dte=dte,
                right=right,
                strike=strike,
                bid=_f(o.get("bid")),
                ask=_f(o.get("ask")),
                last=_f(o.get("last_trade_price")),
                iv=_f(o.get("iv")),
                delta=_f(o.get("delta")),
                gamma=_f(o.get("gamma")),
                theta=_f(o.get("theta")),
                vega=_f(o.get("vega")),
                open_interest=_i(o.get("open_interest")),
                volume=_i(o.get("volume")),
                source="cboe",
                status="ok",
            )
        )
    if not quotes:
        raise ChainError(f"CBOE returned no contracts for {sym} within filters")

    return ChainSnapshot(
        underlying=sym,
        as_of=str(payload.get("timestamp") or _now_iso()),
        spot=spot,
        quotes=quotes,
        atm_iv=_atm_iv_from_quotes(quotes, spot),
        risk_free_rate=rate,
        dividend_yield=dividend_yield,
        data_mode=DATA_LIVE_CHAIN,
        source="cboe",
    )


# --------------------------------------------------------------------------- #
# yfinance (fallback)
# --------------------------------------------------------------------------- #


def fetch_yfinance_chain(
    symbol: str,
    *,
    dte_max: int | None = 120,
    moneyness: float | None = 0.25,
    rate: float = 0.04,
    dividend_yield: float = 0.0,
) -> ChainSnapshot:
    """Fetch a chain from yfinance; greeks are computed locally (no greeks in feed)."""
    import yfinance as yf  # lazy: optional dependency

    tk = yf.Ticker(symbol)
    spot = None
    try:
        spot = _f(getattr(tk, "fast_info", {}).get("last_price"))
    except Exception:
        spot = None
    if spot is None:
        hist = tk.history(period="1d")
        if not hist.empty:
            spot = _f(hist["Close"].iloc[-1])
    if spot is None or spot <= 0:
        raise ChainError(f"yfinance returned no usable spot for {symbol}")

    quotes: list[OptionQuote] = []
    for expiry in tk.options or []:
        dte = (_dt.date.fromisoformat(expiry) - _today()).days
        if dte < 0 or (dte_max is not None and dte > dte_max):
            continue
        oc = tk.option_chain(expiry)
        t_years = max(dte, 0) / 365.0
        for frame, right in ((oc.calls, "C"), (oc.puts, "P")):
            for row in frame.itertuples(index=False):
                strike = _f(getattr(row, "strike", None))
                if strike is None or not _within_filters(dte, strike, spot, dte_max, moneyness):
                    continue
                iv = _f(getattr(row, "impliedVolatility", None))
                g = pricing.bs_greeks(right, spot, strike, t_years, rate, iv or 0.0, dividend_yield) if iv else None
                quotes.append(
                    OptionQuote(
                        underlying=symbol.upper(),
                        expiry=expiry,
                        dte=dte,
                        right=right,
                        strike=strike,
                        bid=_f(getattr(row, "bid", None)),
                        ask=_f(getattr(row, "ask", None)),
                        last=_f(getattr(row, "lastPrice", None)),
                        iv=iv,
                        delta=g.delta if g else None,
                        gamma=g.gamma if g else None,
                        theta=g.theta if g else None,
                        vega=g.vega if g else None,
                        open_interest=_i(getattr(row, "openInterest", None)),
                        volume=_i(getattr(row, "volume", None)),
                        source="yfinance",
                        status="ok",
                    )
                )
    if not quotes:
        raise ChainError(f"yfinance returned no contracts for {symbol} within filters")

    return ChainSnapshot(
        underlying=symbol.upper(),
        as_of=_now_iso(),
        spot=spot,
        quotes=quotes,
        atm_iv=_atm_iv_from_quotes(quotes, spot),
        risk_free_rate=rate,
        dividend_yield=dividend_yield,
        data_mode=DATA_LIVE_CHAIN,
        source="yfinance",
    )


# --------------------------------------------------------------------------- #
# Synthetic vol-surface (final fallback; user can override spot + IV)
# --------------------------------------------------------------------------- #


def surface_iv(surface: VolSurfaceParams, strike: float, forward: float, t_years: float) -> float:
    """Deterministic IV for a (strike, expiry) from a simple skew/smile/term model.

    Skew flattens with maturity as ``(t_ref / T)**skew_decay`` (the empirical
    ``~1/sqrt(T)`` regularity); the ATM level can tilt in sqrt-time.
    """
    m = math.log(strike / forward) if (strike > 0 and forward > 0) else 0.0
    t = max(t_years, 1e-6)
    base = surface.atm_iv + surface.term_slope * (math.sqrt(t) - math.sqrt(surface.t_ref_years))
    slope = surface.skew * (surface.t_ref_years / t) ** surface.skew_decay
    iv = base + slope * m + surface.smile * m * m
    return max(surface.iv_floor, min(surface.iv_cap, iv))


def build_synthetic_chain(
    symbol: str,
    spot: float,
    atm_iv: float,
    *,
    surface: VolSurfaceParams | None = None,
    expiries_dte: tuple[int, ...] = (7, 14, 30, 45, 60, 90),
    n_strikes: int = 21,
    strike_step_pct: float = 0.025,
    rate: float = 0.04,
    dividend_yield: float = 0.0,
    iv_rank: float | None = None,
    realized_vol: float | None = None,
    data_mode: str = DATA_SYNTHETIC,
    source: str = "synthetic",
    warnings: list[str] | None = None,
) -> ChainSnapshot:
    """Build a synthetic chain from a spot + ATM IV anchor.

    Bid/ask bracket the model price by a small assumed half-spread so downstream
    liquidity logic has something to read. Every quote is ``status='model'``.
    """
    if spot <= 0 or atm_iv <= 0:
        raise ChainError("synthetic chain needs positive spot and atm_iv")
    surface = surface or VolSurfaceParams(atm_iv=atm_iv)
    today = _today()
    quotes: list[OptionQuote] = []
    half = n_strikes // 2
    for dte in expiries_dte:
        expiry = (today + _dt.timedelta(days=dte)).isoformat()
        t_years = dte / 365.0
        forward = spot * math.exp((rate - dividend_yield) * t_years)
        for i in range(-half, half + 1):
            strike = round(spot * (1.0 + i * strike_step_pct), 2)
            if strike <= 0:
                continue
            iv = surface_iv(surface, strike, forward, t_years)
            for right in ("C", "P"):
                g = pricing.bs_greeks(right, spot, strike, t_years, rate, iv, dividend_yield)
                price = max(0.0, g.price)
                spread_half = max(0.02, 0.02 * price)
                quotes.append(
                    OptionQuote(
                        underlying=symbol.upper(),
                        expiry=expiry,
                        dte=dte,
                        right=right,
                        strike=strike,
                        bid=round(max(0.0, price - spread_half), 2),
                        ask=round(price + spread_half, 2),
                        last=round(price, 2),
                        iv=iv,
                        delta=g.delta,
                        gamma=g.gamma,
                        theta=g.theta,
                        vega=g.vega,
                        open_interest=None,
                        volume=None,
                        source=source,
                        status="model",
                    )
                )
    return ChainSnapshot(
        underlying=symbol.upper(),
        as_of=_now_iso(),
        spot=spot,
        quotes=quotes,
        atm_iv=atm_iv,
        iv_rank=iv_rank,
        realized_vol=realized_vol,
        risk_free_rate=rate,
        dividend_yield=dividend_yield,
        data_mode=data_mode,
        source=source,
        warnings=list(warnings or []),
    )


# --------------------------------------------------------------------------- #
# Orchestrator
# --------------------------------------------------------------------------- #


def get_chain(
    symbol: str,
    *,
    prefer: tuple[str, ...] = ("cboe", "yfinance"),
    spot_override: float | None = None,
    iv_override: float | None = None,
    realized_vol: float | None = None,
    iv_rank: float | None = None,
    dte_max: int | None = 120,
    moneyness: float | None = 0.25,
    rate: float = 0.04,
    dividend_yield: float = 0.0,
    allow_synthetic: bool = True,
    surface: VolSurfaceParams | None = None,
) -> ChainSnapshot:
    """Return the best chain available, trying live providers then synthesizing.

    User overrides win: if BOTH ``spot_override`` and ``iv_override`` are given,
    the chain is synthesized straight from them (``data_mode='user_override'``) —
    no network call. Otherwise live providers are tried in ``prefer`` order; on
    total failure a synthetic chain is anchored on whatever spot/vol is known.
    """
    warnings: list[str] = []

    if spot_override is not None and iv_override is not None:
        return build_synthetic_chain(
            symbol, spot_override, iv_override,
            surface=surface or VolSurfaceParams(atm_iv=iv_override),
            rate=rate, dividend_yield=dividend_yield, iv_rank=iv_rank,
            realized_vol=realized_vol, data_mode=DATA_USER_OVERRIDE, source="user_override",
        )

    fetchers = {"cboe": fetch_cboe_chain, "yfinance": fetch_yfinance_chain}
    for name in prefer:
        fetch = fetchers.get(name)
        if fetch is None:
            continue
        try:
            snap = fetch(
                symbol, dte_max=dte_max, moneyness=moneyness, rate=rate, dividend_yield=dividend_yield
            )
        except Exception as exc:  # noqa: BLE001 — provider failures must not be fatal
            warnings.append(f"{name} failed: {type(exc).__name__}: {str(exc)[:160]}")
            continue
        # Layer in any extra context the caller knows (realized vol, iv rank,
        # and an explicit spot override applied as a sanity correction).
        updates: dict = {}
        if realized_vol is not None and snap.realized_vol is None:
            updates["realized_vol"] = realized_vol
        if iv_rank is not None and snap.iv_rank is None:
            updates["iv_rank"] = iv_rank
        if warnings:
            updates["warnings"] = [*snap.warnings, *warnings]
        return replace(snap, **updates) if updates else snap

    if not allow_synthetic:
        raise ChainError(f"no live chain for {symbol}; synthetic disabled. {warnings}")

    # Synthetic fallback — anchor on the best spot/vol we have.
    spot = spot_override
    if spot is None:
        raise ChainError(
            f"cannot synthesize chain for {symbol}: no spot. "
            f"Pass spot_override (and optionally iv_override). Provider notes: {warnings}"
        )
    atm = iv_override or realized_vol
    if atm is None:
        atm = 0.20
        warnings.append("no IV/realized-vol anchor — defaulted ATM IV to 0.20; pass iv_override to fix")
    data_mode = DATA_LIVE_ANCHORED if (iv_override or realized_vol) else DATA_SYNTHETIC
    return build_synthetic_chain(
        symbol, spot, atm, surface=surface, rate=rate, dividend_yield=dividend_yield,
        iv_rank=iv_rank, realized_vol=realized_vol, data_mode=data_mode, source="synthetic",
        warnings=warnings,
    )
