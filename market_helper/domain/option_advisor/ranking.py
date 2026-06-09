"""Ranking + triage labelling.

Score = weighted blend of (yield/efficiency, regime alignment, liquidity
confidence, event safety). Label precedence: any hard-filter failure →
``REJECT``; model-only data or any soft-filter failure → at most ``MONITOR``;
otherwise eligible for ``PROCEED``, capped to the top-N by score. Every idea
carries its score drivers for the audit trail.
"""

from __future__ import annotations

from dataclasses import replace

from .contracts import (
    CATEGORY_HEDGE,
    CATEGORY_INCOME,
    LABEL_MONITOR,
    LABEL_PROCEED,
    LABEL_REJECT,
    OptionIdea,
)

def _clip(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def _efficiency(idea: OptionIdea, premium_cfg: dict | None = None) -> tuple[float, float]:
    """Return (efficiency 0..1, raw_metric) for the idea's primary objective.

    For INCOME (selling premium) the value screen blends two researched signals:
    the **annualized yield** on capital at risk *and* the **variance risk premium**
    (IV/RV richness) — premium-selling only carries an edge when implied vol exceeds
    the realized vol the underlying actually delivers. See the option_advisor devplan
    "Premium value screen". The VRP term only engages when realized vol is known.
    """
    premium_cfg = premium_cfg or {}
    credit = idea.est_net_debit_credit or 0.0
    max_loss = abs(idea.est_max_loss) if idea.est_max_loss is not None else None
    max_gain = idea.est_max_gain if idea.est_max_gain is not None else None
    dte = max((leg.resolved_dte or 30) for leg in idea.legs) if idea.legs else 30

    if idea.category == CATEGORY_INCOME and credit > 0:
        # Annualized return on capital at risk.
        base = max_loss if (max_loss and max_loss > 0) else (idea.legs[0].resolved_strike or 1) * 100
        ann = (credit / base) * (365.0 / max(dte, 1))
        target_yield = float(premium_cfg.get("target_yield_annualized", 0.40)) or 0.40
        yld = _clip(ann / target_yield)
        vrp = idea.vrp_ratio
        if vrp is not None:
            span = float(premium_cfg.get("vrp_ratio_span", 0.5)) or 0.5
            vrp_eff = _clip((vrp - 1.0) / span)        # IV `span`% above RV → richness 1.0
            return _clip((yld * vrp_eff) ** 0.5), ann  # geometric: reward rich premium AND positive VRP
        return yld, ann                                # no realized vol → pure yield (back-compat)
    if idea.category == CATEGORY_HEDGE:
        cost = max(0.0, -credit)
        notional = (idea.underlying_symbol and 0) or 0
        # cheaper protection (as % of strike notional) scores higher
        strike_notional = (idea.legs[0].resolved_strike or 1) * 100
        cost_pct = cost / strike_notional if strike_notional else 1.0
        return _clip(1.0 - cost_pct / 0.05), cost_pct   # ≥5% cost → 0
    # Directional / other: reward-to-risk.
    if max_gain and max_loss and max_loss > 0:
        rr = max_gain / max_loss
        return _clip(rr / 2.0), rr              # 2:1 → score 1.0
    return 0.4, 0.0


def _regime_align(idea: OptionIdea) -> float:
    # Regime *gating* already happened in candidate generation; here we keep a
    # mild category-based prior (income/hedge slightly favoured for stability).
    if idea.category in (CATEGORY_INCOME, CATEGORY_HEDGE):
        return 0.7
    return 0.6


def _liquidity_conf(idea: OptionIdea) -> float:
    if not idea.liquidity:
        return 0.5
    return {"ok": 1.0, "thin": 0.5, "unknown_no_chain": 0.25}.get(idea.liquidity.status, 0.5)


def _event_safety(idea: OptionIdea) -> float:
    er = idea.event_risk
    if er is None or er.event_status == "none":
        return 1.0
    if er.event_status == "known" and er.days_to_earnings is not None:
        return 0.5 if er.days_to_earnings <= 7 else 0.9
    return 0.85  # unverified


def score_components(
    idea: OptionIdea, premium_cfg: dict | None = None
) -> tuple[dict[str, float], list[tuple[str, float]]]:
    eff, raw = _efficiency(idea, premium_cfg)
    comp = {
        "yield_or_efficiency": eff,
        "regime_align": _regime_align(idea),
        "liquidity_conf": _liquidity_conf(idea),
        "event_penalty": _event_safety(idea),
    }
    drivers = [
        ("efficiency", round(eff, 3)),
        ("raw_metric", round(raw, 4)),
        ("liquidity_conf", round(comp["liquidity_conf"], 3)),
        ("event_safety", round(comp["event_penalty"], 3)),
    ]
    if idea.category == CATEGORY_INCOME and idea.vrp_ratio is not None:
        drivers.append(("vrp_ratio", round(idea.vrp_ratio, 3)))  # IV/RV value-screen signal
    return comp, drivers


def _rationale(idea: OptionIdea, label: str, model_only: bool) -> str:
    bits = [f"{label}."]
    if label == LABEL_REJECT:
        hard = [fo for fo in idea.filters_applied if not fo.passed and fo.severity == "hard"]
        bits.append("Hard filter: " + "; ".join(fo.detail for fo in hard) if hard else "Failed a hard filter.")
    else:
        if model_only:
            bits.append("Model-only data (no live per-strike quote) - capped at MONITOR until chain-validated.")
        soft = [fo for fo in idea.filters_applied if not fo.passed and fo.severity == "soft"]
        if soft:
            bits.append("Watch: " + "; ".join(fo.detail for fo in soft))
    return " ".join(bits)


def _augment_income_rationale(idea: OptionIdea, rationale: str, premium_cfg: dict) -> str:
    """Append the premium value read (VRP) + the researched management note for INCOME ideas."""
    if idea.category != CATEGORY_INCOME:
        return rationale
    bits: list[str] = []
    vrp = idea.vrp_ratio
    if vrp is not None:
        rich = "rich vs realized" if vrp > 1.0 else "CHEAP vs realized — poor seller value"
        bits.append(f"VRP IV/RV {vrp:.2f}x ({rich})")
    manage = int(premium_cfg.get("manage_dte", 21))
    bits.append(f"manage ~{manage} DTE (close ≈50% max profit / before gamma ramps)")
    return (rationale + " " + "; ".join(bits) + ".").strip()


def rank_and_label(ideas: list[OptionIdea], rules: dict) -> list[OptionIdea]:
    weights = rules.get("ranking", {}).get("weights", {})
    max_proceed = int(rules.get("ranking", {}).get("max_proceed", 8))
    premium_cfg = rules.get("premium_screen", {})

    scored: list[OptionIdea] = []
    for idea in ideas:
        comp, drivers = score_components(idea, premium_cfg)
        score = sum(weights.get(k, 0.0) * v for k, v in comp.items())
        hard_fail = any((not fo.passed and fo.severity == "hard") for fo in idea.filters_applied)
        soft_fail = any((not fo.passed and fo.severity == "soft") for fo in idea.filters_applied)
        model_only = idea.data_status != "chain_validated"
        if hard_fail:
            label = LABEL_REJECT
        elif soft_fail or model_only:
            label = LABEL_MONITOR
        else:
            label = LABEL_PROCEED
        rationale = _rationale(replace(idea, label=label), label, model_only)
        scored.append(replace(
            idea, score=round(score, 4), drivers=drivers, label=label,
            rationale=_augment_income_rationale(idea, rationale, premium_cfg),
        ))

    # Cap PROCEED to the top-N by score; demote the rest to MONITOR.
    proceeds = sorted([i for i in scored if i.label == LABEL_PROCEED], key=lambda i: i.score, reverse=True)
    keep = {id(i) for i in proceeds[:max_proceed]}
    final: list[OptionIdea] = []
    for i in scored:
        if i.label == LABEL_PROCEED and id(i) not in keep:
            final.append(replace(i, label=LABEL_MONITOR, rationale=i.rationale + " (below top-N; monitoring)"))
        else:
            final.append(i)

    order = {LABEL_PROCEED: 0, LABEL_MONITOR: 1, LABEL_REJECT: 2}
    final.sort(key=lambda i: (order.get(i.label, 9), -i.score))
    return final
