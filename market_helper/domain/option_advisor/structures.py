"""Build concrete option structures from a chain + resolve payoff / Greeks.

Each ``build_*`` takes a :class:`~.contracts.ChainSnapshot` and an
:class:`~.contracts.UnderlyingContext` and returns a fully-resolved
:class:`~.contracts.OptionIdea` (legs with strikes/expiries/premia/Greeks,
net debit/credit, max loss/gain, breakevens, a payoff curve, and net Greeks) —
or ``None`` when the chain can't supply a sane strike/expiry.

Conventions
-----------
* One structure unit = ``mult`` shares (100). Stock-inclusive structures
  (covered call, protective put, collar) assume ``mult`` shares per unit and
  use the current spot as the go-forward cost basis.
* ``est_net_debit_credit`` is the **option-leg** cash flow per unit, positive =
  net credit received.
* ``est_max_loss`` / ``est_max_gain`` / ``est_breakevens`` / payoff describe the
  **total resulting position** P&L at expiry (incl. stock where applicable).
"""

from __future__ import annotations

import math
from dataclasses import replace

from . import pricing
from .contracts import (
    CATEGORY_DIRECTIONAL,
    CATEGORY_HEDGE,
    CATEGORY_INCOME,
    LiquidityAssessment,
    OptionIdea,
    OptionLeg,
    OptionQuote,
    STRUCTURE_CALL_SPREAD,
    STRUCTURE_CARRY_SHORT_CALL,
    STRUCTURE_CARRY_SHORT_PUT,
    STRUCTURE_CASH_SECURED_PUT,
    STRUCTURE_COLLAR,
    STRUCTURE_COVERED_CALL,
    STRUCTURE_PROTECTIVE_PUT,
    STRUCTURE_PUT_SPREAD,
    STRUCTURE_ZERO_COST_COLLAR,
    UnderlyingContext,
    ChainSnapshot,
)

MULT = 100


# --------------------------------------------------------------------------- #
# Premium / leg helpers
# --------------------------------------------------------------------------- #


def _premium(q: OptionQuote) -> float | None:
    p = q.mid
    return p if (p is not None and p > 0) else (q.last if (q.last and q.last > 0) else None)


def _leg_from_quote(q: OptionQuote, action: str, strike_rule: str, expiry_rule: str, qty_ratio: int = 1) -> OptionLeg | None:
    prem = _premium(q)
    if prem is None:
        return None
    return OptionLeg(
        right=q.right,
        action=action,
        strike_rule=strike_rule,
        expiry_rule=expiry_rule,
        qty_ratio=qty_ratio,
        resolved_strike=q.strike,
        resolved_expiry=q.expiry,
        resolved_dte=q.dte,
        est_iv=q.iv,
        est_price=prem,
        est_delta=q.delta,
        est_gamma=q.gamma,
        est_theta=q.theta,
        est_vega=q.vega,
        quote_status="live" if q.status == "ok" else "model",
        bid=q.bid,
        ask=q.ask,
        open_interest=q.open_interest,
        volume=q.volume,
    )


def _sign(action: str) -> float:
    return 1.0 if action.lower().startswith(("b", "l")) else -1.0  # buy/long = +1, sell = -1


# --------------------------------------------------------------------------- #
# Payoff / metrics
# --------------------------------------------------------------------------- #


def _leg_intrinsic(leg: OptionLeg, s_t: float) -> float:
    if leg.right == "C":
        return max(0.0, s_t - (leg.resolved_strike or 0.0))
    return max(0.0, (leg.resolved_strike or 0.0) - s_t)


def structure_metrics(
    legs: list[OptionLeg],
    spot: float,
    *,
    stock_shares: int = 0,
    mult: int = MULT,
    grid_points: int = 401,
) -> dict:
    """Compute net cash flow, payoff curve, max loss/gain, breakevens, net Greeks."""
    # Option-leg net premium (credit positive).
    net_credit = 0.0
    for leg in legs:
        net_credit += -_sign(leg.action) * (leg.est_price or 0.0) * leg.qty_ratio * mult

    def pnl(s_t: float) -> float:
        total = stock_shares * (s_t - spot)
        for leg in legs:
            payoff = _sign(leg.action) * (_leg_intrinsic(leg, s_t) - (leg.est_price or 0.0))
            total += payoff * leg.qty_ratio * mult
        return total

    hi = max(spot * 3.0, *(l.resolved_strike or 0.0 for l in legs)) if legs else spot * 3.0
    grid = [hi * i / (grid_points - 1) for i in range(grid_points)]
    # ensure strikes + spot are sampled exactly (kinks)
    for k in {spot, *(l.resolved_strike for l in legs if l.resolved_strike)}:
        grid.append(float(k))
    grid = sorted(set(grid))
    curve = [(s, pnl(s)) for s in grid]

    pnls = [p for _, p in curve]
    max_gain = max(pnls)
    max_loss = min(pnls)

    breakevens: list[float] = []
    for (s0, p0), (s1, p1) in zip(curve, curve[1:]):
        if p0 == 0.0:
            breakevens.append(round(s0, 2))
        elif p0 * p1 < 0:
            be = s0 + (s1 - s0) * (0.0 - p0) / (p1 - p0)
            breakevens.append(round(be, 2))
    breakevens = sorted({b for b in breakevens})

    # Net Greeks (shares-equivalent). Stock contributes delta only.
    net = {"delta": float(stock_shares), "gamma": 0.0, "theta": 0.0, "vega": 0.0}
    for leg in legs:
        s = _sign(leg.action) * leg.qty_ratio * mult
        net["delta"] += s * (leg.est_delta or 0.0)
        net["gamma"] += s * (leg.est_gamma or 0.0)
        net["theta"] += s * (leg.est_theta or 0.0)
        net["vega"] += s * (leg.est_vega or 0.0)

    # Down-sample the payoff curve for storage/plot (~40 points).
    step = max(1, len(curve) // 40)
    sampled = [(round(s, 2), round(p, 2)) for s, p in curve[::step]]

    return {
        "net_credit": round(net_credit, 2),
        "max_gain": round(max_gain, 2),
        "max_loss": round(max_loss, 2),
        "breakevens": breakevens,
        "payoff_curve": sampled,
        "net_greeks": {k: round(v, 4) for k, v in net.items()},
    }


def _liquidity(legs: list[OptionLeg]) -> LiquidityAssessment:
    spreads = [
        (l.ask - l.bid) / (0.5 * (l.ask + l.bid))
        for l in legs
        if l.bid and l.ask and l.bid > 0 and l.ask > 0 and (l.ask + l.bid) > 0
    ]
    ois = [l.open_interest for l in legs if l.open_interest is not None]
    vols = [l.volume for l in legs if l.volume is not None]
    if not spreads and not ois:
        return LiquidityAssessment(status="unknown_no_chain", notes="no bid/ask or OI on legs")
    worst = max(spreads) if spreads else None
    min_oi = min(ois) if ois else None
    status = "ok"
    if (worst is not None and worst > 0.15) or (min_oi is not None and min_oi < 50):
        status = "thin"
    return LiquidityAssessment(
        status=status,
        worst_spread_pct=round(worst, 4) if worst is not None else None,
        min_open_interest=min_oi,
        min_volume=min(vols) if vols else None,
    )


def _idea(
    ctx: UnderlyingContext,
    chain: ChainSnapshot,
    category: str,
    structure_type: str,
    legs: list[OptionLeg],
    *,
    stock_shares: int,
    thesis: str,
    why_now: str,
    logic: str,
) -> OptionIdea | None:
    if not legs:
        return None
    m = structure_metrics(legs, chain.spot, stock_shares=stock_shares)
    expiry = legs[0].resolved_expiry or "?"
    skew = chain.atm_skew(expiry) if expiry != "?" else None
    return OptionIdea(
        idea_id=f"{ctx.symbol}:{structure_type}:{expiry}",
        as_of=chain.as_of,
        spot=chain.spot,
        underlying_id=ctx.internal_id,
        underlying_symbol=ctx.symbol,
        category=category,
        structure_type=structure_type,
        legs=legs,
        thesis=thesis,
        why_now=why_now,
        expiry_strike_logic=logic,
        est_net_debit_credit=m["net_credit"],
        est_max_loss=m["max_loss"],
        est_max_gain=m["max_gain"],
        est_breakevens=m["breakevens"],
        est_payoff_curve=m["payoff_curve"],
        net_greeks=m["net_greeks"],
        liquidity=_liquidity(legs),
        event_risk=ctx.event_risk,
        data_status="chain_validated" if chain.data_mode in ("live_chain",) else "model_only",
        iv_skew=skew,
    )


# --------------------------------------------------------------------------- #
# Builders
# --------------------------------------------------------------------------- #


def build_covered_call(chain, ctx, *, target_delta=0.30, dte=35) -> OptionIdea | None:
    expiry = chain.nearest_expiry(dte)
    if not expiry:
        return None
    q = chain.nearest_by_delta(expiry, "C", target_delta)
    if not q:
        return None
    leg = _leg_from_quote(q, "sell", f"delta~{target_delta:.2f}", f"dte~{dte}")
    iv_note = f"IV rank {ctx.iv_rank:.0%}" if ctx.iv_rank is not None else "IV context n/a"
    return _idea(
        ctx, chain, CATEGORY_INCOME, STRUCTURE_COVERED_CALL, [leg],
        stock_shares=MULT,
        thesis=f"Harvest premium on the {ctx.symbol} core long by selling an OTM call.",
        why_now=f"{iv_note}; regime {ctx.regime_label or 'n/a'}. Caps upside above the strike for income.",
        logic=f"Sell ~{target_delta:.0%}-delta call, ~{dte}DTE (strike {q.strike:g}, exp {expiry}).",
    )


def build_cash_secured_put(chain, ctx, *, target_delta=0.27, dte=35) -> OptionIdea | None:
    expiry = chain.nearest_expiry(dte)
    if not expiry:
        return None
    q = chain.nearest_by_delta(expiry, "P", target_delta)
    if not q:
        return None
    leg = _leg_from_quote(q, "sell", f"delta~{target_delta:.2f}", f"dte~{dte}")
    return _idea(
        ctx, chain, CATEGORY_INCOME, STRUCTURE_CASH_SECURED_PUT, [leg],
        stock_shares=0,
        thesis=f"Get paid to set a buy limit on {ctx.symbol} via a cash-secured put.",
        why_now=f"Regime {ctx.regime_label or 'n/a'}; collect premium, accept assignment near {q.strike:g}.",
        logic=f"Sell ~{target_delta:.0%}-delta put, ~{dte}DTE (strike {q.strike:g}, exp {expiry}).",
    )


def build_protective_put(chain, ctx, *, target_delta=0.15, dte=75) -> OptionIdea | None:
    expiry = chain.nearest_expiry(dte)
    if not expiry:
        return None
    q = chain.nearest_by_delta(expiry, "P", target_delta)
    if not q:
        return None
    leg = _leg_from_quote(q, "buy", f"delta~{target_delta:.2f}", f"dte~{dte}")
    return _idea(
        ctx, chain, CATEGORY_HEDGE, STRUCTURE_PROTECTIVE_PUT, [leg],
        stock_shares=MULT,
        thesis=f"Cap downside on the {ctx.symbol} long with an OTM protective put.",
        why_now=f"{'Crisis overlay active; ' if ctx.crisis_flag else ''}tail insurance on a concentrated long.",
        logic=f"Buy ~{target_delta:.0%}-delta put, ~{dte}DTE (strike {q.strike:g}, exp {expiry}).",
    )


def build_collar(chain, ctx, *, put_delta=0.20, call_delta=0.25, dte=60) -> OptionIdea | None:
    expiry = chain.nearest_expiry(dte)
    if not expiry:
        return None
    qp = chain.nearest_by_delta(expiry, "P", put_delta)
    qc = chain.nearest_by_delta(expiry, "C", call_delta)
    if not qp or not qc:
        return None
    legs = [
        _leg_from_quote(qp, "buy", f"delta~{put_delta:.2f}", f"dte~{dte}"),
        _leg_from_quote(qc, "sell", f"delta~{call_delta:.2f}", f"dte~{dte}"),
    ]
    if any(l is None for l in legs):
        return None
    return _idea(
        ctx, chain, CATEGORY_HEDGE, STRUCTURE_COLLAR, legs,
        stock_shares=MULT,
        thesis=f"Finance downside protection on {ctx.symbol} by capping upside (collar).",
        why_now="Low-cost hedge: the short call premium offsets the protective put.",
        logic=f"Buy ~{put_delta:.0%}d put + sell ~{call_delta:.0%}d call, ~{dte}DTE (exp {expiry}).",
    )


def _annualized_carry_pct(premium: float | None, strike: float | None, dte: int | None) -> float | None:
    """Premium as an annualized yield on the strike notional (carry framing)."""
    if not premium or not strike or strike <= 0:
        return None
    days = max(int(dte or 0), 1)
    return (premium / strike) * (365.0 / days)


def build_zero_cost_collar(
    chain,
    ctx,
    *,
    protect_put_delta=0.25,
    floor_put_delta=0.10,
    call_delta_candidates=(0.35, 0.30, 0.25, 0.20, 0.15),
    dte=60,
) -> OptionIdea | None:
    """Zero-cost protection: buy an OTM put *spread*, finance it by selling an OTM call.

    Legs (overlay on ``MULT`` held shares):
      * BUY put  @ ``protect_put_delta`` (the protection — closer to spot, higher strike)
      * SELL put @ ``floor_put_delta``   (the floor — further OTM, lower strike; caps the
        protected band and cheapens the hedge)
      * SELL call (chosen from ``call_delta_candidates`` to finance the put-spread debit)

    Intent: net cost ≈ flat or a small credit and **net-short-vega** (two shorts vs one
    long). Honest caveat: the put *spread* only protects the band
    ``[floor_strike, protect_strike]`` — the tail below the floor is uncovered (that
    residual tail is exactly what makes it cheap/zero-cost).
    """
    expiry = chain.nearest_expiry(dte)
    if not expiry:
        return None
    qp_long = chain.nearest_by_delta(expiry, "P", protect_put_delta)   # protection (buy)
    qp_short = chain.nearest_by_delta(expiry, "P", floor_put_delta)    # floor (sell)
    if not qp_long or not qp_short:
        return None
    # Floor must sit strictly below the protection strike (both OTM puts).
    if qp_short.strike >= qp_long.strike:
        return None
    long_prem = _premium(qp_long)
    short_prem = _premium(qp_short)
    if long_prem is None or short_prem is None:
        return None
    spread_debit = max(long_prem - short_prem, 0.0)

    # Pick the call that best finances the put-spread debit: prefer the *least* upside
    # given up (smallest premium) that still covers the debit (→ credit); else closest.
    best: tuple[int, float, OptionQuote, float] | None = None
    for cd in call_delta_candidates:
        qc = chain.nearest_by_delta(expiry, "C", cd)
        if not qc or (qc.strike is not None and chain.spot and qc.strike <= chain.spot):
            continue
        cprem = _premium(qc)
        if cprem is None:
            continue
        rank = (0 if cprem >= spread_debit else 1, abs(cprem - spread_debit))
        if best is None or rank < (best[0], best[1]):
            best = (rank[0], rank[1], qc, cprem)
    if best is None:
        return None
    qc = best[2]

    legs = [
        _leg_from_quote(qp_long, "buy", f"delta~{protect_put_delta:.2f}", f"dte~{dte}"),
        _leg_from_quote(qp_short, "sell", f"delta~{floor_put_delta:.2f}", f"dte~{dte}"),
        _leg_from_quote(qc, "sell", "finance-call", f"dte~{dte}"),
    ]
    if any(l is None for l in legs):
        return None
    return _idea(
        ctx, chain, CATEGORY_HEDGE, STRUCTURE_ZERO_COST_COLLAR, legs,
        stock_shares=MULT,
        thesis=(
            f"Protect the {ctx.symbol} long for ~zero cost: buy a {qp_long.strike:g}/{qp_short.strike:g} "
            f"put spread, finance it by selling the {qc.strike:g} call."
        ),
        why_now=(
            "Net-short-vega, cost ≈ flat/credit. Covers the "
            f"{qp_short.strike:g}–{qp_long.strike:g} band; tail below {qp_short.strike:g} stays uncovered "
            "(the cost of zero-cost). Upside capped above the short call."
        ),
        logic=(
            f"Buy ~{protect_put_delta:.0%}d put / sell ~{floor_put_delta:.0%}d put + sell call to finance, "
            f"~{dte}DTE (exp {expiry})."
        ),
    )


def build_carry_short_call(chain, ctx, *, target_delta=0.20, dte=35) -> OptionIdea | None:
    """Single short call to harvest premium carry. Naked (undefined upside risk) →
    capped at MONITOR by :mod:`.filters`; shown with an annualized carry yield."""
    expiry = chain.nearest_expiry(dte)
    if not expiry:
        return None
    q = chain.nearest_by_delta(expiry, "C", target_delta)
    if not q:
        return None
    leg = _leg_from_quote(q, "sell", f"delta~{target_delta:.2f}", f"dte~{dte}")
    if leg is None:
        return None
    ann = _annualized_carry_pct(leg.est_price, q.strike, q.dte)
    carry_txt = f"~{ann:.0%}/yr premium carry" if ann is not None else "premium carry"
    return _idea(
        ctx, chain, CATEGORY_INCOME, STRUCTURE_CARRY_SHORT_CALL, [leg],
        stock_shares=0,
        thesis=f"Harvest call premium on {ctx.symbol} (naked short call, carry play).",
        why_now=f"Collect {carry_txt}. NAKED — undefined upside risk; advisory MONITOR only.",
        logic=f"Sell ~{target_delta:.0%}-delta call, ~{dte}DTE (strike {q.strike:g}, exp {expiry}).",
    )


def build_carry_short_put(chain, ctx, *, target_delta=0.18, dte=35) -> OptionIdea | None:
    """Single short put to harvest premium carry (further OTM than the cash-secured put).
    Loss bounded at strike→0 but uncollateralized here → capped at MONITOR; shown with an
    annualized carry yield."""
    expiry = chain.nearest_expiry(dte)
    if not expiry:
        return None
    q = chain.nearest_by_delta(expiry, "P", target_delta)
    if not q:
        return None
    leg = _leg_from_quote(q, "sell", f"delta~{target_delta:.2f}", f"dte~{dte}")
    if leg is None:
        return None
    ann = _annualized_carry_pct(leg.est_price, q.strike, q.dte)
    carry_txt = f"~{ann:.0%}/yr premium carry" if ann is not None else "premium carry"
    return _idea(
        ctx, chain, CATEGORY_INCOME, STRUCTURE_CARRY_SHORT_PUT, [leg],
        stock_shares=0,
        thesis=f"Harvest put premium on {ctx.symbol} (short put, carry play).",
        why_now=f"Collect {carry_txt}. Loss to zero if assigned; advisory MONITOR only.",
        logic=f"Sell ~{target_delta:.0%}-delta put, ~{dte}DTE (strike {q.strike:g}, exp {expiry}).",
    )


def _vertical(chain, ctx, right, long_delta, short_delta, dte, category, structure_type, thesis, why_now):
    expiry = chain.nearest_expiry(dte)
    if not expiry:
        return None
    q_long = chain.nearest_by_delta(expiry, right, long_delta)
    q_short = chain.nearest_by_delta(expiry, right, short_delta)
    if not q_long or not q_short or q_long.strike == q_short.strike:
        return None
    legs = [
        _leg_from_quote(q_long, "buy", f"delta~{long_delta:.2f}", f"dte~{dte}"),
        _leg_from_quote(q_short, "sell", f"delta~{short_delta:.2f}", f"dte~{dte}"),
    ]
    if any(l is None for l in legs):
        return None
    logic = f"Buy ~{long_delta:.0%}d / sell ~{short_delta:.0%}d {right}, ~{dte}DTE (exp {expiry})."
    return _idea(ctx, chain, category, structure_type, legs, stock_shares=0,
                 thesis=thesis, why_now=why_now, logic=logic)


def build_call_spread(chain, ctx, *, long_delta=0.40, short_delta=0.20, dte=40) -> OptionIdea | None:
    return _vertical(
        chain, ctx, "C", long_delta, short_delta, dte, CATEGORY_DIRECTIONAL, STRUCTURE_CALL_SPREAD,
        thesis=f"Defined-risk bullish view on {ctx.symbol} via a call debit spread.",
        why_now=f"Trend {ctx.trend_state}; regime {ctx.regime_label or 'n/a'} supports a measured upside bet.",
    )


def build_put_spread(chain, ctx, *, long_delta=0.40, short_delta=0.20, dte=40) -> OptionIdea | None:
    return _vertical(
        chain, ctx, "P", long_delta, short_delta, dte, CATEGORY_DIRECTIONAL, STRUCTURE_PUT_SPREAD,
        thesis=f"Defined-risk bearish/hedge view on {ctx.symbol} via a put debit spread.",
        why_now=f"Trend {ctx.trend_state}; {'crisis overlay; ' if ctx.crisis_flag else ''}capped-cost downside.",
    )


# --------------------------------------------------------------------------- #
# What-if recompute — the live-exploration engine (bounded inputs from the UI)
# --------------------------------------------------------------------------- #

_OVERLAY_STOCK = {
    STRUCTURE_COVERED_CALL: MULT,
    STRUCTURE_PROTECTIVE_PUT: MULT,
    STRUCTURE_COLLAR: MULT,
    STRUCTURE_ZERO_COST_COLLAR: MULT,
}


def stock_shares_for(structure_type: str) -> int:
    """Underlying shares implied by an overlay structure (0 for standalone)."""
    return _OVERLAY_STOCK.get(structure_type, 0)


def reprice_legs(
    legs: list[OptionLeg],
    spot: float,
    *,
    iv_shift: float = 0.0,
    iv_skew: float = 0.0,
    base_spot: float | None = None,
    rate: float = 0.04,
    dividend_yield: float = 0.0,
) -> list[OptionLeg]:
    """Re-price every leg at a new spot / shifted IV via Black–Scholes.

    ``iv_skew`` (the chain's ``∂IV/∂log-moneyness``) plus ``base_spot`` enable a
    **sticky-moneyness** vol response: moving spot from ``base_spot`` to ``spot``
    shifts every leg's moneyness by ``ln(base_spot/spot)``, so its IV moves by
    ``iv_skew · ln(base_spot/spot)`` — IV tracks the chain skew instead of staying
    flat. With ``iv_skew=0`` (the default) this is a pure flat re-price.
    """
    skew_dm = (
        iv_skew * math.log(base_spot / spot)
        if (iv_skew and base_spot and base_spot > 0 and spot > 0)
        else 0.0
    )
    out: list[OptionLeg] = []
    for leg in legs:
        t = max(leg.resolved_dte or 0, 0) / 365.0
        iv = max((leg.est_iv or 0.0) + iv_shift + skew_dm, 1e-4)
        g = pricing.bs_greeks(leg.right, spot, leg.resolved_strike or 0.0, t, rate, iv, dividend_yield)
        out.append(
            replace(
                leg,
                est_iv=iv,
                est_price=round(g.price, 4),
                est_delta=g.delta,
                est_gamma=g.gamma,
                est_theta=g.theta,
                est_vega=g.vega,
                quote_status="model",
            )
        )
    return out


def whatif(
    structure_type: str,
    legs: list[OptionLeg],
    spot: float,
    *,
    iv_shift: float = 0.0,
    iv_skew: float = 0.0,
    spot_override: float | None = None,
    qty_scale: int = 1,
    rate: float = 0.04,
    dividend_yield: float = 0.0,
) -> dict:
    """Recompute structure metrics under bounded what-if overrides.

    With all overrides at their no-op defaults (``iv_shift=0``, ``iv_skew=0``,
    ``spot_override=None``, ``qty_scale=1``) this reproduces the engine's
    original metrics for a model-priced structure — see the ``what-if == engine``
    test. ``iv_shift`` is in vol points (0.05 = +5 vol); ``iv_skew`` links IV to
    the chain skew as spot moves off ``spot`` (sticky-moneyness); ``qty_scale``
    multiplies every leg and any overlay stock.
    """
    s = float(spot_override) if spot_override is not None else float(spot)
    repriced = reprice_legs(
        legs, s, iv_shift=iv_shift, iv_skew=iv_skew, base_spot=float(spot),
        rate=rate, dividend_yield=dividend_yield,
    )
    scale = int(qty_scale)
    if scale != 1:
        repriced = [replace(leg, qty_ratio=leg.qty_ratio * scale) for leg in repriced]
    shares = stock_shares_for(structure_type) * scale
    return structure_metrics(repriced, s, stock_shares=shares, mult=MULT)


def whatif_from_detail(detail: dict, **overrides) -> dict:
    """What-if from a serialized idea ``detail`` (a ``Suggestion.detail`` dict).

    Reconstructs ``OptionLeg`` objects so the UI can drive recompute without
    holding engine objects. Raises ``ValueError`` if ``detail`` lacks a spot.
    """
    spot = detail.get("spot")
    if spot is None:
        raise ValueError("idea detail has no 'spot' — cannot run what-if")
    legs = [
        OptionLeg(
            right=leg["right"],
            action=leg["action"],
            strike_rule=leg.get("strike_rule", ""),
            expiry_rule=leg.get("expiry_rule", ""),
            qty_ratio=int(leg.get("qty_ratio", 1)),
            resolved_strike=leg.get("resolved_strike"),
            resolved_expiry=leg.get("resolved_expiry"),
            resolved_dte=leg.get("resolved_dte"),
            est_iv=leg.get("est_iv"),
            est_price=leg.get("est_price"),
            est_delta=leg.get("est_delta"),
            est_gamma=leg.get("est_gamma"),
            est_theta=leg.get("est_theta"),
            est_vega=leg.get("est_vega"),
        )
        for leg in (detail.get("legs") or [])
    ]
    return whatif(detail.get("structure_type", ""), legs, float(spot), **overrides)
