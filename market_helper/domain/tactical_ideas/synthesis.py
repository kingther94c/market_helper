"""AI synthesis for Tactical Trade Ideas — research/synthesis, never orders.

Takes the offline :class:`TacticalContext` + the rule-based anchors and asks the
local OpenClaw gateway (reusing :mod:`market_helper.trade_advisor.ai.gateway`,
the single network boundary) to research and expand them into a short tactical
brief. The prompt **pins the model to the supplied context** and forbids any
order/ticket/size — the model may only reason, cite evidence, and state
invalidations. Display-only; nothing here trades.

``request_tactical_brief`` takes an injectable ``post`` so tests never touch the
network.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from market_helper.trade_advisor.ai.gateway import (
    GatewayConfig,
    post_chat_completion,
    resolve_gateway_token,
)

_SYSTEM_GUARD = (
    "You are a macro/market TACTICAL RESEARCH assistant for a single operator. "
    "Base your analysis ONLY on the regime + signal context and the rule-based idea "
    "anchors provided below — do not invent prices, levels, or positions. You may "
    "research and synthesize SHORT-TERM, INDEPENDENT trade ideas (macro / rates / FX / "
    "volatility / commodity / sector — e.g. de-dollarization, risk-off, short-VIX carry, "
    "trend persistence, curve steepeners, sector rotation, commodity relative-value), "
    "distinct from base-position option overlays. You must NEVER output an order, ticket, "
    "position size, or instruction to trade — analysis only."
)

_ASK = (
    "Respond in markdown with exactly these bold sections:\n"
    "**Macro read** — 2-3 sentences on the regime/signal picture.\n"
    "**Top tactical ideas** — 3-5 independent short-term ideas; for each: the trade "
    "(instrument/expression, no size), thesis, the concrete evidence it rests on, and a "
    "clear invalidation.\n"
    "**What the rules miss** — ideas or risks the rule-based anchors did not surface.\n"
    "**Biggest risk** — the main way this tactical stance is wrong right now.\n"
    "Keep it ~200-300 words. Never output an order or a size."
)


@dataclass(frozen=True)
class TacticalBrief:
    brief: str
    model: str = ""
    prompt_tokens: int | None = None
    completion_tokens: int | None = None


def _context_lines(ctx: Any) -> str:
    parts = [
        f"- regime: {getattr(ctx, 'regime', '') or '?'} (confidence {getattr(ctx, 'confidence', '') or '?'})",
        f"- crisis/overlay: {getattr(ctx, 'crisis', False)}; risk_score={getattr(ctx, 'risk_score', None)}",
        f"- growth_score={getattr(ctx, 'growth_score', None)}; inflation_score={getattr(ctx, 'inflation_score', None)}",
    ]
    if getattr(ctx, "expert_available", False):
        parts.append(
            f"- policy-expert forward tilt: top={getattr(ctx, 'top_expert', '')} "
            f"(conf {getattr(ctx, 'expert_confidence', 0.0):.0%}); sleeves={getattr(ctx, 'sleeve_weights', {})}"
        )
    if getattr(ctx, "trend_available", False):
        parts.append(f"- trending (momentum) top: {getattr(ctx, 'trend_top', '')}; probs={getattr(ctx, 'trend_probabilities', {})}")
    parts.append(f"- context sources: {', '.join(getattr(ctx, 'sources', []) or []) or 'none (regime defaults)'}")
    return "\n".join(parts)


def _anchor_lines(ideas: list) -> str:
    if not ideas:
        return "(no rule-based anchors fired)"
    out = []
    for idea in ideas:
        out.append(
            f"- [{getattr(idea, 'theme', '')}] {getattr(idea, 'direction', '')}: "
            f"{getattr(idea, 'thesis', '')} (conf {getattr(idea, 'confidence', '')}; "
            f"invalidation: {getattr(idea, 'invalidation', '')})"
        )
    return "\n".join(out)


def build_tactical_prompt(context: Any, ideas: list) -> str:
    return (
        f"{_SYSTEM_GUARD}\n\n"
        f"## Regime + signal context (as of {getattr(context, 'as_of', '') or 'latest'})\n"
        f"{_context_lines(context)}\n\n"
        f"## Rule-based idea anchors (already grounded)\n"
        f"{_anchor_lines(ideas)}\n\n"
        f"{_ASK}"
    )


def request_tactical_brief(
    *,
    context: Any,
    ideas: list | None = None,
    config: GatewayConfig | None = None,
    token: str | None = None,
    post: Callable[..., dict] = post_chat_completion,
) -> TacticalBrief:
    """Build the prompt, call the gateway, parse the brief. ``post`` is injectable.

    Raises :class:`~market_helper.trade_advisor.ai.gateway.GatewayAuthMissing` when no
    token is configured and :class:`GatewayError` on transport failure — the UI catches
    both and shows an explainer (the rule-based anchors are unaffected).
    """
    cfg = config or GatewayConfig.from_env()
    tok = token if token is not None else resolve_gateway_token()
    payload = {
        "model": cfg.model,
        "messages": [{"role": "user", "content": build_tactical_prompt(context, ideas or [])}],
        "temperature": 0.3,
    }
    resp = post(config=cfg, token=tok, payload=payload)
    choices = resp.get("choices") or []
    content = (choices[0].get("message") or {}).get("content", "") if choices else ""
    usage = resp.get("usage") or {}
    return TacticalBrief(
        brief=(content or "").strip(),
        model=str(resp.get("model", cfg.model)),
        prompt_tokens=usage.get("prompt_tokens"),
        completion_tokens=usage.get("completion_tokens"),
    )
