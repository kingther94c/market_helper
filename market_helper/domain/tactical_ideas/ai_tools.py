"""Tactical Trade Ideas — the AI's read-only tools, skills, and knowledge.

This is where the Tactical module contributes to the advisor-AI capability set:

- **Tools** (:func:`build_tactical_tool_registry`): read-only functions the AI can
  call mid-brief to pull live local data — the regime snapshot, the policy-expert
  forward tilt + trending, the rule-based anchors, and a per-symbol price trend.
  Driven by the structured-text tool protocol in ``trade_advisor.ai.tools`` (the
  OpenClaw gateway ignores native OpenAI function-calling — see that module).
- **Skills** (:func:`tactical_skills`): the injected prompts for the
  ``tactical_brief`` task — the harness-selected production prompt plus tested
  alternatives (adversarial, terse), all selectable.
- **Knowledge** (:func:`tactical_knowledge`): tactical-specific facts.

Everything here is read-only / advisory; no tool places, sizes, or mutates.
"""

from __future__ import annotations

from typing import Any

from market_helper.trade_advisor.ai.skills import KnowledgeEntry, PromptSkill
from market_helper.trade_advisor.ai.tools import AiToolRegistry

from .signals import build_tactical_context, generate_tactical_ideas
from .synthesis import DEFAULT_STYLE, IDEAGEN_STYLE, _ORDER_GUARD

_NO_PARAMS: dict[str, Any] = {"type": "object", "properties": {}, "additionalProperties": False}

# Random-stimulus pool for the guided-creativity ideagen (adapted from the
# operator's idea-generation-macro skill). Deliberately OUTSIDE finance: the
# divergence effect comes from force-fitting a non-financial concept's STRUCTURE
# onto a market. Hand-picked "random" words cluster on near-neighbours and kill
# the effect — always draw via the tool.
_STIMULUS_POOL = (
    # natural phenomena (cyclical, deterministic, mechanical)
    "tide", "monsoon", "geyser", "avalanche", "rip current", "thermocline", "wildfire",
    "permafrost", "eclipse", "solstice", "tornado", "tsunami", "magma chamber", "aurora",
    "magnetic field reversal", "river meander",
    # biology (feedback loops, predator-prey, contagion)
    "mycorrhiza", "lichen", "molting", "hibernation", "swarming", "stampede", "antibody",
    "vaccine", "metamorphosis", "symbiosis", "parasite", "bloom", "migration",
    "echolocation", "camouflage", "mimicry",
    # engineering / infrastructure (load, redundancy, failure modes)
    "dam spillway", "transformer", "circuit breaker", "load balancer", "shock absorber",
    "flywheel", "ratchet", "governor (engine)", "fuse", "expansion joint", "blast furnace",
    "cooling tower", "pressure valve",
    # craft / kitchen / textile (technique, sequencing)
    "kneading", "fermentation", "tempering", "marbling", "lamination", "weaving",
    "felting", "smelting", "annealing", "quenching", "etching",
    # sport / movement (timing, leverage)
    "feint", "draft (cycling)", "tackle", "counter-punch", "checkmate setup", "rebound",
    "tip-off", "slipstream",
    # art / music (composition, dynamics)
    "counterpoint", "fugue", "ostinato", "chiaroscuro", "negative space", "vanishing point",
    "rubato", "polyrhythm", "syncopation",
    # old technology
    "semaphore", "telegraph", "abacus", "sundial", "windmill", "watermill", "lighthouse",
    "lever arm", "pulley system",
    # abstract structural concepts
    "phase transition", "cascade", "threshold effect", "tipping point", "feedback loop",
    "deadlock", "bottleneck", "starvation (in CS)", "garbage collection", "memoization",
    "hysteresis", "resonance", "interference pattern", "standing wave", "critical mass",
    # information / social dynamics
    "rumour", "gossip cascade", "stampede (panic)", "queue jumping", "rationing",
    "fire drill", "evacuation", "muster point",
)


def build_tactical_tool_registry(*, regime_path=None) -> AiToolRegistry:
    """Read-only tools the AI may call while writing a tactical brief.

    The context is built once and cached across the tools so repeated calls within
    one brief are cheap + consistent.
    """
    reg = AiToolRegistry()
    cache: dict[str, Any] = {}

    def _ctx():
        if "ctx" not in cache:
            cache["ctx"] = build_tactical_context(regime_path=regime_path)
        return cache["ctx"]

    @reg.tool(
        "get_regime_snapshot",
        "Latest macro regime: Growth×Inflation quadrant (effective + raw engine label) and the "
        "growth / inflation / risk scores + crisis flag.",
        _NO_PARAMS,
    )
    def get_regime_snapshot() -> dict:
        c = _ctx()
        return {
            "regime": c.regime_effective or c.regime, "regime_label_raw": c.regime_label_raw,
            "confidence": c.confidence, "crisis": c.crisis,
            "growth_score": c.growth_score, "inflation_score": c.inflation_score, "risk_score": c.risk_score,
        }

    @reg.tool(
        "get_policy_expert",
        "Forward policy-expert tilt (which Growth×Inflation expert leads, sleeve weights) and the "
        "backward 'trending' momentum probabilities.",
        _NO_PARAMS,
    )
    def get_policy_expert() -> dict:
        c = _ctx()
        return {
            "available": c.expert_available, "top_expert": c.top_expert, "expert_confidence": c.expert_confidence,
            "sleeve_weights": c.sleeve_weights, "trend_top": c.trend_top, "trend_probabilities": c.trend_probabilities,
        }

    @reg.tool(
        "get_tactical_anchors",
        "The rule-based tactical idea anchors that fired (theme, direction, conviction, thesis, evidence, "
        "invalidation, expression) — the grounded starting set.",
        _NO_PARAMS,
    )
    def get_tactical_anchors() -> list:
        ideas = generate_tactical_ideas(_ctx())
        return [
            {"theme": i.theme, "direction": i.direction, "confidence": i.confidence, "thesis": i.thesis,
             "evidence": i.evidence, "invalidation": i.invalidation, "expression": i.expression}
            for i in ideas
        ]

    @reg.tool(
        "get_price_trend",
        "Realized volatility (1m/3m/6m/1y) and SMA trend (up/down/chop) for one ticker from the local cache.",
        {"type": "object", "properties": {"symbol": {"type": "string", "description": "ticker, e.g. SPY"}},
         "required": ["symbol"], "additionalProperties": False},
    )
    def get_price_trend(symbol: str) -> dict:
        from market_helper.domain.option_advisor.signals import realized_vol_and_trend
        out = realized_vol_and_trend(str(symbol).upper())
        return out if isinstance(out, dict) else {"result": out}

    @reg.tool(
        "get_tactical_edge",
        "The external daily Tactical Edge research brief — independent idea cards (title, status, mechanism, "
        "Skeptic's view, conviction score). Pull this to reconcile your read against it, or to fade it.",
        _NO_PARAMS,
    )
    def get_tactical_edge() -> list:
        from .tactical_edge import load_tactical_edge

        _, cards = load_tactical_edge()  # offline + graceful; [] when the brief is absent
        return [
            {"number": c.number, "title": c.title, "status": c.status, "mechanism": c.get("mechanism"),
             "skeptic": c.get("skeptic's view"), "expression": c.get("retail expression"), "scores": dict(c.scores)}
            for c in cards
        ]

    @reg.tool(
        "draw_random_stimulus",
        "Draw N genuinely random non-financial concepts (the ideagen divergence engine). Force-fit each "
        "draw's STRUCTURE onto a market; most won't connect — discard those. Draws are prompts, not "
        "commitments. Never pick your own 'random' words — they cluster on near-neighbours.",
        {"type": "object", "properties": {"n": {"type": "integer", "description": "number of draws (default 5)"}},
         "additionalProperties": False},
    )
    def draw_random_stimulus(n: int = 5) -> dict:
        import random

        k = max(1, min(int(n or 5), 10))
        return {
            "draws": random.sample(_STIMULUS_POOL, k=k),
            "how_to_use": "For each: where does this concept's STRUCTURE show up in the cross-asset world? "
                          "Build ideas only where a real mechanism appears.",
        }

    return reg


# Alternative injected prompts for the tactical_brief task (harness-tested) — registered
# as skills so the prompt-per-task choice is discoverable + extensible.
_ADVERSARIAL = PromptSkill(
    name="tactical_adversarial",
    task="tactical_brief",
    when_to_use="When you want every leading idea stress-tested with an explicit bear case + which anchors to fade.",
    system=(
        "You are a macro/market TACTICAL RESEARCH partner whose job is to PRESSURE-TEST, not cheerlead. "
        "Research SHORT-TERM INDEPENDENT ideas; for each leading one give the bull AND a concrete bear case, "
        "and say which rule-based anchors you would FADE and why. Revise specifically to operator feedback. "
        + _ORDER_GUARD
    ),
    ask=(
        "Markdown sections: **Macro read** (note divergence); **Top tactical ideas (stress-tested)** — rank 3-4; "
        "each: trade (no size), thesis, evidence, bear case, monitorable invalidation; **Anchors I'd fade**; "
        "**Biggest risk**. Never output an order or size."
    ),
)
_TERSE = PromptSkill(
    name="tactical_terse",
    task="tactical_brief",
    when_to_use="Quick scan / mobile — a compact conviction table and a single top pick.",
    system=(
        "You are a macro/market TACTICAL RESEARCH partner. Be decisive and scannable; rank by conviction. "
        "Research SHORT-TERM INDEPENDENT ideas. Revise specifically to feedback. " + _ORDER_GUARD
    ),
    ask=(
        "Markdown: **Read** (1-2 sentences); **Ideas** — a table (max 4): Conviction | Trade (no size) | "
        "Evidence | Monitorable invalidation; **Top pick** (one line); **Biggest risk** (one line). No order or size."
    ),
)


def tactical_skills() -> list[PromptSkill]:
    """The injected prompts for the tactical_brief task (production default + alternatives)."""
    return [
        PromptSkill(
            name="tactical_default",
            task="tactical_brief",
            when_to_use="Default — conviction table + 'Anchors I'd fade' + monitorable invalidation; best for the "
                        "interactive feedback loop. (Harness-selected.)",
            system=DEFAULT_STYLE.system,
            ask=DEFAULT_STYLE.ask,
            notes=f"backed by synthesis.DEFAULT_STYLE ({DEFAULT_STYLE.name})",
        ),
        _ADVERSARIAL,
        _TERSE,
        PromptSkill(
            name="tactical_ideagen",
            task="tactical_brief",
            when_to_use="Idea GENERATION (the accumulate loop): divergent, off-preset ideas via creativity "
                        "operators + random stimulus, evaluated by the return-source hard filter. Use when the "
                        "operator wants NEW ideas rather than a synthesis of the existing anchors. (Internalized "
                        "from the operator's idea-generation-macro skill; pane default for Tactical AI Plus.)",
            system=IDEAGEN_STYLE.system,
            ask=IDEAGEN_STYLE.ask,
            notes=f"backed by synthesis.IDEAGEN_STYLE ({IDEAGEN_STYLE.name}); pairs with the "
                  "draw_random_stimulus tool + return_sources/idea_filters knowledge",
        ),
    ]


def tactical_tool_messages(context, ideas, registry: AiToolRegistry, *, style=None) -> list[dict]:
    """Initial messages for a TOOL-ENABLED tactical brief: the style system turn (with the
    tool protocol baked in) + the user turn (context + anchors + ask). The caller drives
    the loop with ``run_tool_chat(..., inject_protocol=False)`` so the protocol is added once.
    ``style`` selects the injected prompt (default: the harness-selected DEFAULT_STYLE).
    """
    from market_helper.trade_advisor.ai.tools import tool_protocol_instructions

    from .synthesis import build_tactical_messages

    messages = build_tactical_messages(context, ideas, style=style or DEFAULT_STYLE)
    if registry is not None and len(registry):
        messages[0]["content"] = messages[0]["content"] + tool_protocol_instructions(registry)
    return messages


def tactical_knowledge_block(names: "list[str] | None" = None) -> str:
    """Selected tactical knowledge rendered as a system-prompt block (for builders)."""
    from market_helper.trade_advisor.ai.skills import KnowledgeBook, knowledge_system_block

    kb = KnowledgeBook()
    for entry in tactical_knowledge():
        kb.register(entry)
    return knowledge_system_block(kb, names=names)


def tactical_knowledge() -> list[KnowledgeEntry]:
    """Tactical-specific reference knowledge."""
    return [
        KnowledgeEntry(
            "tactical_themes", "Tactical",
            "Independent short-term themes the module covers: de-dollarization / short USD, risk-off / vol, "
            "short-VIX carry (only at calm/extreme), trend persistence / add exposure, bond-curve steepeners "
            "(futures), sector rotation, commodity curve / relative-value (e.g. oil product premium, soyoil "
            "share). These are PURE INDEPENDENT trades, distinct from the Option module's base-position overlays.",
            ("tactical", "scope"),
        ),
        KnowledgeEntry(
            "derived_quadrant", "Tactical",
            "When the regime engine emits a non-quadrant label (e.g. 'Neutral/Mixed'), the module derives the "
            "Growth×Inflation quadrant from the axis-score signs and labels it 'derived from scores'. "
            "A Goldilocks-forward (policy-expert) vs Reflation-momentum (trending) divergence means lower "
            "conviction — prefer targeted expressions over broad beta.",
            ("tactical", "macro"),
        ),
        KnowledgeEntry(
            "return_sources", "Ideagen",
            "Return-source families — anchor every idea in exactly ONE; name the crowded default form and "
            "your incremental edge (conditioner / horizon / universe / flow / structure):\n"
            "1) RISK PREMIA — ERP (default: long SPY; edge: regime-conditioned overlay, equal-weight tilt) · "
            "term premium (long TLT; edge: cross-country spreads ZB/Bund/JGB, policy-regime steepeners) · "
            "credit (long HYG; edge: HY/IG ratio, OAS-regime tilt) · vol risk premium (short VIX naked — "
            "blew up 2018; edge: /VX calendar by term-structure regime, cross-asset vol relative cheapness) · "
            "FX carry (long EM vs USD; edge: vol-adjusted, risk-regime-gated, funder rotation JPY/CHF) · "
            "commodity carry (long backwardation; edge: calendar spreads, seasonality) · liquidity (edge: "
            "ETF-vs-NAV stress deviations, rebal-flow capture).\n"
            "2) ANOMALIES — trend/TS-momentum (12-1 equities; edge: cross-asset futures, regime-gated, "
            "horizon variation) · cross-sectional momentum (edge: sector/country ETF rotation) · short-horizon "
            "mean-reversion (edge: ADR-vs-local, ETF-vs-NAV, correlated futures pairs CL-BZ/GC-SI/ZN-ZB) · "
            "value (edge: gold-vs-real-yields, commodity 5y lows, bond yield z-scores) · defensive/low-vol.\n"
            "3) FLOWS & POSITIONING — pension month/quarter-end rebal · dealer gamma (OPEX pinning vs "
            "amplification) · CTA forced de-leveraging on vol spikes · CB flows (BoJ/ECB/PBoC, QT, "
            "intervention) · index reconstitution · 0DTE dealer flow · EM CB peg defense.\n"
            "4) BEHAVIORAL — post-news over/under-reaction (fade CPI/NFP/FOMC gaps conditioned on "
            "positioning) · sentiment extremes (contrarian at 95th pct) · disposition effect.\n"
            "5) MICROSTRUCTURE / REGIME / EVENT — regime shifts (multi-asset overlays with confirmation "
            "rules) · cross-asset vol dispersion · skew extremes · curve-shape change (DV01-weighted "
            "spreads) · scheduled-event vol calendars.",
            ("ideagen", "taxonomy"),
        ),
        KnowledgeEntry(
            "idea_filters", "Ideagen",
            "The HARD FILTER — every idea clears all six or is flagged failing: (1) MECHANISM: a named "
            "return-source family — 'the chart looks good' is not a mechanism. (2) ORTHOGONALITY: state the "
            "crowded default form + the incremental edge; the default itself is a robustness sweep, not an "
            "idea. (3) LEAK-SAFE: the signal at time t uses only data ≤ t. (4) RETAIL-IMPLEMENTABLE: a "
            "specific LISTED instrument (ETF ticker / futures code / listed options structure); single "
            "stocks are an auto-reject. (5) SKEPTIC'S VIEW: the single strongest reason it fails (crowding / "
            "slippage / decay / borrow / regime dependence). (6) CHEAPEST FIRST TEST: one observation or "
            "paper-trade in ≤ 2 weeks that confirms or kills.\n"
            "SCORES 1-5 each (all-5 = not being honest): Novelty (5 = new source / off-preset; 1 = textbook "
            "default) · Mechanism plausibility (5 = documented economic force; 1 = chart pattern) · "
            "Tradability (retail-friction-adjusted: spread, decay, borrow, capacity) · Conviction-today "
            "(are the conditioners aligned RIGHT NOW). Maturity verdict: Raw = park · Developing = next "
            "test defined · Ready = mechanism + cheapest-test + instrument all line up.",
            ("ideagen", "discipline"),
        ),
    ]
