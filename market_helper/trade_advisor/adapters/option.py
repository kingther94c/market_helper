"""Option advisor → umbrella adapter.

Wraps :mod:`market_helper.domain.option_advisor.service` and maps each
``OptionIdea`` onto the shared :class:`~..contracts.Suggestion`. No behavior
change to the option engine — a projection that also surfaces a **risk explainer**
(scenario P&L, vol-shock, liquidity, and plain-English risk flags) so the module
reads as a risk/overlay analyzer first, not just an idea recommender.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from market_helper.domain.option_advisor import service as option_service
from market_helper.domain.option_advisor.contracts import OptionAdvisoryResult, OptionIdea

from ..contracts import (
    LABEL_INFO,
    LABEL_REJECT,
    LABEL_RESEARCH_READY,
    LABEL_WATCHLIST,
    TIER_DETERMINISTIC,
    AdvisorContext,
    AdvisorResult,
    AuditEntry,
    IdeaAssessment,
    Sizing,
    Suggestion,
    cap_label_for_tier,
    data_quality_for_mode,
)

_CONF_BY_ENGINE = {"PROCEED": "high", "MONITOR": "medium", "REJECT": "low", "INFO": "low"}

# Map the option ENGINE's internal labels onto the cockpit's research-framed vocabulary.
# The engine emits PROCEED only on a live chain with all hard filters passed and a real
# (non-model-only) structure — exactly the T2 RESEARCH_READY gate.
_LABEL_MAP = {"PROCEED": LABEL_RESEARCH_READY, "MONITOR": LABEL_WATCHLIST, "REJECT": LABEL_REJECT, "INFO": LABEL_INFO}


def _sizing_from(idea: OptionIdea) -> Sizing | None:
    s = idea.sizing
    if s is None:
        return None
    return Sizing(
        basis=s.basis,
        max_units=s.max_contracts,
        capital_at_risk_usd=s.capital_at_risk_usd,
        notional_pct_of_aum=s.notional_pct_of_aum,
        notes=s.notes,
    )


def _interp_payoff(curve, target: float) -> float | None:
    pts = sorted((float(s), float(p)) for s, p in (curve or []) if s is not None and p is not None)
    if not pts:
        return None
    if target <= pts[0][0]:
        return pts[0][1]
    if target >= pts[-1][0]:
        return pts[-1][1]
    for (s0, p0), (s1, p1) in zip(pts, pts[1:]):
        if s0 <= target <= s1:
            return p0 if s1 == s0 else p0 + (target - s0) / (s1 - s0) * (p1 - p0)
    return None


def _scenario_pnl(idea: OptionIdea) -> dict[str, float]:
    """At-expiry structure P&L at spot shocks — the defined-risk profile (per structure unit)."""
    spot = idea.spot
    if not spot or not idea.est_payoff_curve:
        return {}
    out: dict[str, float] = {}
    for shock in (-0.20, -0.10, -0.05, 0.05, 0.10):
        v = _interp_payoff(idea.est_payoff_curve, spot * (1.0 + shock))
        if v is not None:
            out[f"{shock:+.0%}"] = round(v, 2)
    return out


def _vol_shock_usd(idea: OptionIdea, vol_points: float = 5.0) -> float | None:
    """≈ MTM impact of a +vol_points move (net vega is per 1.00 sigma = 100 vol points)."""
    vega = idea.net_greeks.get("vega")
    return round(vega * vol_points / 100.0, 2) if vega is not None else None


def _risk_flags(idea: OptionIdea) -> list[str]:
    """Plain-English risk disclosures — the explainer's core, not a 'yield' story."""
    flags: list[str] = []
    legs = idea.legs or []
    shorts = [l for l in legs if str(l.action).lower().startswith("s")]
    longs = [l for l in legs if str(l.action).lower().startswith("b")]
    spot = idea.spot
    if shorts and not longs:
        flags.append("Undefined left-tail (naked premium sale) — gap / margin / assignment risk, not a 'yield'.")
    for l in shorts:
        k = l.resolved_strike
        if k is None or not spot:
            continue
        right = str(l.right).upper()
        itm = (right == "C" and spot > k) or (right == "P" and spot < k)
        if itm:
            extra = " + early-exercise/dividend risk around ex-div" if right == "C" else ""
            flags.append(f"Assignment risk: short {right}{k:g} is ITM (spot {spot:g}){extra}.")
    return flags


def _liquidity_bits(idea: OptionIdea) -> dict[str, Any]:
    liq = idea.liquidity
    if liq is None:
        return {"status": "unknown_no_chain"}
    return {"status": liq.status, "worst_spread_pct": liq.worst_spread_pct, "min_open_interest": liq.min_open_interest}


def _risk_block(idea: OptionIdea) -> dict[str, Any]:
    return {
        "scenarios_at_expiry": _scenario_pnl(idea),
        "vol_shock_5pt_usd": _vol_shock_usd(idea),
        "flags": _risk_flags(idea),
        "liquidity": _liquidity_bits(idea),
        "net_greeks": dict(idea.net_greeks),
    }


def _headline_metrics(idea: OptionIdea) -> dict[str, str]:
    m: dict[str, str] = {}
    cf = idea.est_net_debit_credit
    if cf is not None:
        m["net"] = f"{'credit' if cf >= 0 else 'debit'} {abs(cf):,.0f}"
    if idea.est_max_loss is not None:
        m["max_loss"] = f"{idea.est_max_loss:,.0f}"
    if idea.est_max_gain is not None:
        m["max_gain"] = f"{idea.est_max_gain:,.0f}"
    if idea.category == "INCOME":
        # The premium value-screen signals: annualized yield (from the ranking driver) + VRP.
        ann = dict(idea.drivers).get("raw_metric")
        if ann:
            m["yield"] = f"{float(ann) * 100:.0f}%/yr"
        if idea.vrp_ratio is not None:
            m["IV/RV"] = f"{idea.vrp_ratio:.2f}x"
    scen = _scenario_pnl(idea)
    if "-10%" in scen:
        m["@-10%"] = f"{scen['-10%']:,.0f}"      # the risk-explainer headline: P&L if spot -10% (at expiry)
    vshock = _vol_shock_usd(idea)
    if vshock is not None:
        m["+5vol"] = f"{vshock:,.0f}"
    liq = _liquidity_bits(idea)
    if liq.get("status") and liq["status"] != "unknown_no_chain":
        m["liq"] = str(liq["status"])
    if idea.est_breakevens:
        m["breakeven"] = ", ".join(f"{b:g}" for b in idea.est_breakevens)
    er = idea.event_risk
    if er is not None and er.event_status == "known" and er.days_to_earnings is not None:
        m["earnings"] = f"{er.days_to_earnings}d"
    return m


def _option_assessment(idea: OptionIdea, data_mode: str, facing_label: str, flags: list[str]) -> IdeaAssessment:
    naked = any("Undefined left-tail" in f for f in flags)
    confidence = _CONF_BY_ENGINE.get(idea.label, "low")
    if idea.data_status == "model_only" and confidence == "high":
        confidence = "medium"   # model-only is never high-confidence
    return IdeaAssessment(
        confidence=confidence,
        actionability="staged" if facing_label == LABEL_RESEARCH_READY else ("watch" if facing_label == LABEL_WATCHLIST else "parked"),
        risk_boundedness="undefined" if naked else "defined",
        data_quality=data_quality_for_mode(data_mode),
        notes={
            "risk_boundedness": flags[0] if naked else "Defined-risk structure (bounded max loss).",
            "data_quality": f"chain: {idea.data_status}",
        },
    )


def suggestion_from_idea(idea: OptionIdea, data_mode: str) -> Suggestion:
    facing = cap_label_for_tier(_LABEL_MAP.get(idea.label, LABEL_WATCHLIST), TIER_DETERMINISTIC)
    flags = _risk_flags(idea)
    invalidation = (
        "Breakevens " + ", ".join(f"{b:g}" for b in idea.est_breakevens) if idea.est_breakevens
        else "Adverse move past the structure's wings / floor."
    )
    return Suggestion(
        advisor="option",
        suggestion_id=idea.idea_id,
        as_of=idea.as_of,
        title=f"{idea.structure_type} · {idea.underlying_symbol}",
        subject=idea.underlying_symbol,
        category=idea.category,
        label=facing,
        decision_tier=TIER_DETERMINISTIC,
        score=idea.score,
        thesis=idea.thesis,
        why_now=idea.why_now,
        rationale=idea.rationale,
        headline_metrics=_headline_metrics(idea),
        drivers=list(idea.drivers),
        audit=[AuditEntry(f.filter_name, f.passed, f.severity, f.detail) for f in idea.filters_applied],
        data_mode=data_mode,
        assessment=_option_assessment(idea, data_mode, facing, flags),
        instrument_family="option_structure",
        risk="; ".join(flags) if flags else (f"Max loss {idea.est_max_loss:,.0f}" if idea.est_max_loss is not None else ""),
        invalidation=invalidation,
        portfolio_interaction="Overlay on the base position — net against existing exposure before sizing.",
        sizing=_sizing_from(idea),
        body_kind="option_payoff",
        detail={**asdict(idea), "risk": _risk_block(idea)},
    )


class OptionAdvisorPlugin:
    """Umbrella plugin for the option advisor."""

    key = "option"
    title = "Option Advisor"

    def produce(
        self,
        context: AdvisorContext,
        *,
        symbols: list[str] | None = None,
        overrides: dict[str, dict] | None = None,
        rules_path: str | None = None,
        prefer: tuple[str, ...] = ("cboe", "yfinance"),
        fetch_realized: bool = False,
        fetch_events: bool = False,
    ) -> AdvisorResult:
        syms = symbols if symbols is not None else context.symbols()
        result: OptionAdvisoryResult = option_service.run_advisor(
            syms,
            rules_path=rules_path,
            aum=context.aum,
            holdings=context.holdings,
            sectors=context.sectors,
            regime_label=context.regime_label,
            regime_confidence=context.regime_confidence,
            crisis_flag=context.crisis_flag,
            overrides=overrides,
            prefer=prefer,
            fetch_realized=fetch_realized,
            fetch_events=fetch_events,
            as_of=context.as_of or None,
        )
        suggestions = [suggestion_from_idea(i, result.data_mode) for i in result.ideas]
        return AdvisorResult(
            advisor="option",
            as_of=result.as_of,
            suggestions=suggestions,
            data_mode=result.data_mode,
            warnings=list(result.warnings),
            config_version=result.config_version,
            meta={"universe_scanned": result.universe_scanned},
        )
