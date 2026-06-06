"""Risk filters + sizing → a per-idea audit trail of :class:`FilterOutcome`.

Hard failures force ``REJECT`` (in :mod:`.ranking`); soft failures force at most
``MONITOR``. Sizing caps contracts to a share of funded AUM (which, per the
project gotcha, excludes options/futures).
"""

from __future__ import annotations

from .contracts import FilterOutcome, OptionIdea, SizingGuidance, UnderlyingContext

# Overlay structures sit on top of an existing share lot; standalone ones tie up
# fresh capital and are sized against the AUM cap.
_OVERLAY = {"COVERED_CALL", "PROTECTIVE_PUT", "COLLAR"}


def _net_debit(idea: OptionIdea) -> float:
    """Positive = you pay (debit)."""
    return max(0.0, -(idea.est_net_debit_credit or 0.0))


def _sizing(idea: OptionIdea, ctx: UnderlyingContext, rules: dict) -> SizingGuidance:
    f = rules.get("filters", {})
    aum = f.get("_aum")  # injected by service.advise_symbol
    if idea.structure_type in _OVERLAY:
        lots = int(ctx.held_qty // 100)
        cost = _net_debit(idea) * 100.0
        return SizingGuidance(
            basis="held_lots",
            max_contracts=lots or None,
            capital_at_risk_usd=round(cost, 2),
            notes=f"overlay on {lots} held lot(s); upfront option cost ${cost:,.0f}/unit",
        )
    risk = abs(idea.est_max_loss) if idea.est_max_loss is not None else None
    if aum and risk and risk > 0:
        max_dollars = float(f.get("max_notional_pct_aum", 0.05)) * aum
        n = int(max_dollars // risk)
        return SizingGuidance(
            basis="max_loss_cap",
            max_contracts=n,
            capital_at_risk_usd=round(risk, 2),
            notional_pct_of_aum=round(risk / aum, 4),
            notes=f"cap {f.get('max_notional_pct_aum', 0.05):.0%} AUM (${max_dollars:,.0f}) / ${risk:,.0f} risk",
        )
    return SizingGuidance(
        basis="max_loss_cap",
        capital_at_risk_usd=round(risk, 2) if risk else None,
        notes="AUM not supplied — size manually",
    )


def evaluate(idea: OptionIdea, ctx: UnderlyingContext, rules: dict) -> tuple[list[FilterOutcome], SizingGuidance]:
    f = rules.get("filters", {})
    out: list[FilterOutcome] = []

    liq = idea.liquidity
    if liq and liq.worst_spread_pct is not None:
        cap = float(f.get("max_spread_pct", 0.15))
        ok = liq.worst_spread_pct <= cap
        out.append(FilterOutcome("liquidity_spread", ok, "hard",
                                 f"worst-leg spread {liq.worst_spread_pct:.1%} vs cap {cap:.0%}"))
    if liq and liq.min_open_interest is not None:
        thin = int(f.get("thin_oi", 50))
        out.append(FilterOutcome("open_interest", liq.min_open_interest >= thin, "soft",
                                 f"min OI {liq.min_open_interest} vs floor {thin}"))
    if liq and liq.status == "unknown_no_chain":
        out.append(FilterOutcome("liquidity_data", False, "soft",
                                 "no live bid/ask/OI — liquidity unconfirmed"))

    # Transaction-cost worthwhileness for credit (income) ideas.
    credit = idea.est_net_debit_credit or 0.0
    if credit > 0:
        n_legs = len(idea.legs)
        commission = float(f.get("commission_per_contract", 0.65)) * n_legs
        half_spread = 0.0
        for leg in idea.legs:
            if leg.bid and leg.ask and leg.ask > leg.bid:
                half_spread += (leg.ask - leg.bid) / 2.0 * 100.0 * leg.qty_ratio
        costs = commission + half_spread
        need = float(f.get("min_premium_over_costs", 1.5)) * costs
        out.append(FilterOutcome("premium_vs_costs", credit >= need, "soft",
                                 f"net credit ${credit:,.0f} vs needed ${need:,.0f} (costs ${costs:,.0f})"))

    # Assignment risk: short leg in/near the money close to expiry.
    spot = ctx.spot or 0.0
    for leg in idea.legs:
        if leg.action.lower().startswith("s") and leg.resolved_strike and (leg.resolved_dte or 99) <= 21:
            itm = (leg.right == "C" and spot >= leg.resolved_strike) or (leg.right == "P" and spot <= leg.resolved_strike)
            if itm:
                out.append(FilterOutcome("assignment_risk", False, "soft",
                                         f"short {leg.right} ITM with {leg.resolved_dte}DTE — early-assignment risk"))

    # Event risk — informational unless a real feed says otherwise.
    er = idea.event_risk
    if er and er.event_status == "known" and er.days_to_earnings is not None:
        max_dte = max((leg.resolved_dte or 0) for leg in idea.legs)
        spans = er.days_to_earnings <= max_dte
        out.append(FilterOutcome("event_risk", not spans, "soft",
                                 f"earnings in {er.days_to_earnings}d {'within' if spans else 'beyond'} the trade"))
    else:
        out.append(FilterOutcome("event_risk", True, "soft", "earnings unverified (no events feed)"))

    sizing = _sizing(idea, ctx, rules)
    if sizing.basis == "max_loss_cap" and sizing.max_contracts is not None and sizing.max_contracts < 1:
        out.append(FilterOutcome("sizing", False, "hard",
                                 "min 1 contract exceeds AUM risk cap - position too large"))

    return out, sizing
