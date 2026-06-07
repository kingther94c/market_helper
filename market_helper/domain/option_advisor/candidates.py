"""Candidate generation: rule-based structure templates → raw OptionIdea list.

Which structures fire depends on the YAML rules + context: covered calls /
protective puts / collars require a held round lot; cash-secured puts and
verticals are available for any scanned name. Regime gates suppress
upside-capping income in strong risk-on and bias toward hedges in
defensive/crisis regimes.
"""

from __future__ import annotations

from . import structures
from .contracts import ChainSnapshot, OptionIdea, UnderlyingContext


def _enabled(rules: dict, name: str) -> bool:
    return bool(rules.get("strategies", {}).get(name, {}).get("enabled"))


def generate(chain: ChainSnapshot, ctx: UnderlyingContext, rules: dict) -> list[OptionIdea]:
    strat = rules.get("strategies", {})
    gates = rules.get("regime_gates", {})
    regime_key = f"{ctx.regime_label}:{ctx.regime_confidence}"
    suppress_income = regime_key in gates.get("suppress_income_when", [])
    hedge_bias = ctx.crisis_flag and "crisis_flag" in gates.get("hedge_bias_when", [])
    hedge_bias = hedge_bias or ctx.regime_label in gates.get("hedge_bias_when", [])
    held_lots = int(ctx.held_qty // structures.MULT)

    ideas: list[OptionIdea | None] = []

    # --- Income (needs no upside-cap suppression) ---
    if _enabled(rules, "covered_call") and held_lots >= strat["covered_call"].get("min_round_lots", 1) and not suppress_income:
        cc = strat["covered_call"]
        ideas.append(structures.build_covered_call(chain, ctx, target_delta=cc["target_delta"], dte=cc["dte"]))
    if _enabled(rules, "cash_secured_put") and not suppress_income:
        csp = strat["cash_secured_put"]
        ideas.append(structures.build_cash_secured_put(chain, ctx, target_delta=csp["target_delta"], dte=csp["dte"]))

    # --- Income (carry premium — naked premium-selling, capped at MONITOR by filters) ---
    if _enabled(rules, "carry_short_call") and held_lots == 0 and not suppress_income:
        # Held names get the (PROCEED-eligible) covered_call instead; this is the naked carry play.
        csc = strat["carry_short_call"]
        ideas.append(structures.build_carry_short_call(chain, ctx, target_delta=csc["target_delta"], dte=csc["dte"]))
    if _enabled(rules, "carry_short_put") and not suppress_income:
        csp2 = strat["carry_short_put"]
        ideas.append(structures.build_carry_short_put(chain, ctx, target_delta=csp2["target_delta"], dte=csp2["dte"]))

    # --- Hedge (only meaningful on a held long) ---
    if _enabled(rules, "protective_put") and held_lots >= 1:
        pp = strat["protective_put"]
        ideas.append(structures.build_protective_put(chain, ctx, target_delta=pp["target_delta"], dte=pp["dte"]))
    if _enabled(rules, "collar") and held_lots >= 1:
        co = strat["collar"]
        ideas.append(structures.build_collar(chain, ctx, put_delta=co["put_delta"], call_delta=co["call_delta"], dte=co["dte"]))
    if _enabled(rules, "zero_cost_collar") and held_lots >= 1:
        zc = strat["zero_cost_collar"]
        ideas.append(structures.build_zero_cost_collar(
            chain, ctx,
            protect_put_delta=zc["protect_put_delta"],
            floor_put_delta=zc["floor_put_delta"],
            dte=zc["dte"],
        ))

    # --- Directional (defined-risk) ---
    if _enabled(rules, "call_spread") and not hedge_bias:
        cs = strat["call_spread"]
        ideas.append(structures.build_call_spread(chain, ctx, long_delta=cs["long_delta"], short_delta=cs["short_delta"], dte=cs["dte"]))
    if _enabled(rules, "put_spread"):
        ps = strat["put_spread"]
        ideas.append(structures.build_put_spread(chain, ctx, long_delta=ps["long_delta"], short_delta=ps["short_delta"], dte=ps["dte"]))

    return [i for i in ideas if i is not None]
