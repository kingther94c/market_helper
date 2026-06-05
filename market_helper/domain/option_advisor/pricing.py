"""Pure-stdlib Black–Scholes–Merton pricing, Greeks, and implied-vol solving.

No third-party dependencies: the normal CDF/PDF come from
:class:`statistics.NormalDist`, so the advisor's core math adds nothing to
``env.yml``. Every function is pure and unit-testable.

Conventions
-----------
* ``right`` is ``"C"``/``"call"`` or ``"P"``/``"put"`` (case-insensitive).
* Time ``t`` is in **years** (e.g. 30 days ≈ 30/365).
* ``r`` is the continuously-compounded risk-free rate; ``q`` the continuous
  dividend yield. Both as decimals (0.04 = 4%).
* ``sigma`` is annualized vol as a decimal (0.20 = 20%).
* **Vega** is per ``1.00`` (100 vol points) change in sigma — divide by 100 for
  the per-1-vol-point figure traders quote.
* **Theta** is per **year** — divide by 365 for per-calendar-day.
* **Rho** is per ``1.00`` (100 bps×100) change in ``r``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from statistics import NormalDist

__all__ = [
    "Greeks",
    "norm_cdf",
    "norm_pdf",
    "d1_d2",
    "bs_price",
    "bs_greeks",
    "implied_vol",
    "intrinsic",
    "leg_payoff_at_expiry",
]

_STD_NORMAL = NormalDist()
_INV_SQRT_2PI = 1.0 / math.sqrt(2.0 * math.pi)

# Sigma search bounds for the implied-vol solver.
_MIN_SIGMA = 1e-4
_MAX_SIGMA = 5.0


def _is_call(right: str) -> bool:
    r = right.strip().lower()
    if r in ("c", "call"):
        return True
    if r in ("p", "put"):
        return False
    raise ValueError(f"right must be C/call or P/put, got {right!r}")


def norm_cdf(x: float) -> float:
    """Standard-normal CDF."""
    return _STD_NORMAL.cdf(x)


def norm_pdf(x: float) -> float:
    """Standard-normal PDF (faster than NormalDist().pdf for hot loops)."""
    return _INV_SQRT_2PI * math.exp(-0.5 * x * x)


@dataclass(frozen=True)
class Greeks:
    """Black–Scholes price + the standard Greeks (see module docstring for units)."""

    price: float
    delta: float
    gamma: float
    vega: float
    theta: float
    rho: float


def intrinsic(right: str, spot: float, strike: float) -> float:
    """Intrinsic value per share at the given spot."""
    if _is_call(right):
        return max(0.0, spot - strike)
    return max(0.0, strike - spot)


def d1_d2(
    spot: float,
    strike: float,
    t: float,
    r: float,
    sigma: float,
    q: float = 0.0,
) -> tuple[float, float]:
    """Return the Black–Scholes ``d1, d2`` terms.

    Raises ``ValueError`` on non-positive spot/strike/t/sigma — callers that
    expect degenerate inputs (expired, zero-vol) should use :func:`bs_price` /
    :func:`bs_greeks`, which handle those gracefully.
    """
    if spot <= 0 or strike <= 0 or t <= 0 or sigma <= 0:
        raise ValueError("spot, strike, t, sigma must all be positive for d1/d2")
    vol_sqrt_t = sigma * math.sqrt(t)
    d1 = (math.log(spot / strike) + (r - q + 0.5 * sigma * sigma) * t) / vol_sqrt_t
    d2 = d1 - vol_sqrt_t
    return d1, d2


def bs_price(
    right: str,
    spot: float,
    strike: float,
    t: float,
    r: float,
    sigma: float,
    q: float = 0.0,
) -> float:
    """Black–Scholes–Merton price of a European option (per share).

    Degenerate inputs collapse to intrinsic value (``t <= 0`` or ``sigma <= 0``).
    """
    call = _is_call(right)
    if t <= 0 or sigma <= 0:
        return intrinsic(right, spot, strike)
    d1, d2 = d1_d2(spot, strike, t, r, sigma, q)
    disc_r = math.exp(-r * t)
    disc_q = math.exp(-q * t)
    if call:
        return spot * disc_q * norm_cdf(d1) - strike * disc_r * norm_cdf(d2)
    return strike * disc_r * norm_cdf(-d2) - spot * disc_q * norm_cdf(-d1)


def bs_greeks(
    right: str,
    spot: float,
    strike: float,
    t: float,
    r: float,
    sigma: float,
    q: float = 0.0,
) -> Greeks:
    """Price + delta/gamma/vega/theta/rho (see module docstring for units)."""
    call = _is_call(right)

    # Degenerate: at/after expiry or zero vol → a step payoff, no convexity.
    if t <= 0 or sigma <= 0:
        price = intrinsic(right, spot, strike)
        if call:
            delta = 1.0 if spot > strike else (0.5 if spot == strike else 0.0)
        else:
            delta = -1.0 if spot < strike else (-0.5 if spot == strike else 0.0)
        return Greeks(price=price, delta=delta, gamma=0.0, vega=0.0, theta=0.0, rho=0.0)

    d1, d2 = d1_d2(spot, strike, t, r, sigma, q)
    sqrt_t = math.sqrt(t)
    disc_r = math.exp(-r * t)
    disc_q = math.exp(-q * t)
    pdf_d1 = norm_pdf(d1)

    price = bs_price(right, spot, strike, t, r, sigma, q)
    gamma = disc_q * pdf_d1 / (spot * sigma * sqrt_t)
    vega = spot * disc_q * pdf_d1 * sqrt_t  # per 1.00 change in sigma

    if call:
        delta = disc_q * norm_cdf(d1)
        theta = (
            -(spot * disc_q * pdf_d1 * sigma) / (2.0 * sqrt_t)
            - r * strike * disc_r * norm_cdf(d2)
            + q * spot * disc_q * norm_cdf(d1)
        )
        rho = strike * t * disc_r * norm_cdf(d2)
    else:
        delta = -disc_q * norm_cdf(-d1)
        theta = (
            -(spot * disc_q * pdf_d1 * sigma) / (2.0 * sqrt_t)
            + r * strike * disc_r * norm_cdf(-d2)
            - q * spot * disc_q * norm_cdf(-d1)
        )
        rho = -strike * t * disc_r * norm_cdf(-d2)

    return Greeks(price=price, delta=delta, gamma=gamma, vega=vega, theta=theta, rho=rho)


def implied_vol(
    price: float,
    right: str,
    spot: float,
    strike: float,
    t: float,
    r: float,
    q: float = 0.0,
    *,
    tol: float = 1e-6,
    max_iter: int = 100,
) -> float | None:
    """Solve for the implied volatility that reproduces ``price``.

    Newton–Raphson seeded from a Brenner–Subrahmanyam ATM guess, with a
    bisection fallback. Returns ``None`` when the price is below intrinsic /
    above the no-arbitrage bound or the solve fails to converge — callers must
    treat ``None`` as "unsolvable", never as a vol of 0.
    """
    if t <= 0 or spot <= 0 or strike <= 0 or price <= 0:
        return None

    call = _is_call(right)
    disc_r = math.exp(-r * t)
    disc_q = math.exp(-q * t)
    # No-arbitrage bounds.
    lower = intrinsic(right, spot * disc_q, strike * disc_r)
    upper = spot * disc_q if call else strike * disc_r
    if price < lower - tol or price > upper + tol:
        return None

    # Brenner–Subrahmanyam ATM seed: sigma ≈ price/spot * sqrt(2*pi/t).
    guess = max(_MIN_SIGMA, min(_MAX_SIGMA, (price / spot) * math.sqrt(2.0 * math.pi / t)))

    sigma = guess
    for _ in range(max_iter):
        model = bs_price(right, spot, strike, t, r, sigma, q)
        diff = model - price
        if abs(diff) < tol:
            return sigma
        vega = spot * disc_q * norm_pdf(d1_d2(spot, strike, t, r, sigma, q)[0]) * math.sqrt(t)
        if vega < 1e-12:
            break  # flat region — hand off to bisection
        sigma -= diff / vega
        if sigma <= _MIN_SIGMA or sigma >= _MAX_SIGMA or math.isnan(sigma):
            break

    # Bisection fallback over the full bracket.
    lo, hi = _MIN_SIGMA, _MAX_SIGMA
    p_lo = bs_price(right, spot, strike, t, r, lo, q) - price
    p_hi = bs_price(right, spot, strike, t, r, hi, q) - price
    if p_lo * p_hi > 0:
        return None
    for _ in range(max_iter):
        mid = 0.5 * (lo + hi)
        p_mid = bs_price(right, spot, strike, t, r, mid, q) - price
        if abs(p_mid) < tol or (hi - lo) < tol:
            return mid
        if p_lo * p_mid < 0:
            hi = mid
        else:
            lo, p_lo = mid, p_mid
    return 0.5 * (lo + hi)


def leg_payoff_at_expiry(
    right: str,
    action: str,
    strike: float,
    premium: float,
    spot_at_expiry: float,
    *,
    qty_ratio: int = 1,
) -> float:
    """P&L per share of a single option leg held to expiry.

    ``action`` is ``"buy"`` (long, pay premium) or ``"sell"`` (short, collect
    premium). ``premium`` is the per-share price paid/received. ``qty_ratio``
    scales multi-contract legs (e.g. a 1x2 ratio spread).
    """
    sign = 1.0 if action.strip().lower() in ("buy", "long", "b") else -1.0
    value = intrinsic(right, spot_at_expiry, strike)
    # Long: pay premium up front, receive intrinsic at expiry.
    # Short: receive premium up front, pay out intrinsic at expiry.
    pnl_per_share = sign * (value - premium)
    return pnl_per_share * qty_ratio
