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

from .contracts import (
    CATEGORY_DIRECTIONAL,
    CATEGORY_HEDGE,
    CATEGORY_INCOME,
    LiquidityAssessment,
    OptionIdea,
    OptionLeg,
    OptionQuote,
    STRUCTURE_CALL_SPREAD,
    STRUCTURE_CASH_SECURED_PUT,
    STRUCTURE_COLLAR,
    STRUCTURE_COVERED_CALL,
    STRUCTURE_PROTECTIVE_PUT,
    STRUCTURE_PUT_SPREAD,
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
    return OptionIdea(
        idea_id=f"{ctx.symbol}:{structure_type}:{expiry}",
        as_of=chain.as_of,
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
