"""AI synthesis for Tactical Trade Ideas — research/synthesis, never orders.

Takes the offline :class:`TacticalContext` + the rule-based anchors and asks the
local OpenClaw gateway (reusing :mod:`market_helper.trade_advisor.ai.gateway`,
the single network boundary) to research and expand them into a short tactical
brief. The prompt **pins the model to the supplied context** and forbids any
order/ticket/size — the model may only reason, cite evidence, and state
invalidations. Display-only; nothing here trades.

The conversation is an OpenAI-style ``messages`` array: a *system* turn (the
framing/guard — swappable via :class:`TacticalPromptStyle`) + a *user* turn
(context + anchors + the ask). :func:`request_tactical_chat` posts any messages
array, so the UI can keep the dialog going: append the assistant brief + the
user's feedback (:func:`continue_messages`) and re-post for a refined brief.
``post`` is injectable so tests never touch the network.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from market_helper.trade_advisor.ai.gateway import (
    GatewayConfig,
    post_chat_completion,
    resolve_gateway_token,
)


@dataclass(frozen=True)
class TacticalPromptStyle:
    """A swappable 'inject prompt': the system framing/guard + the response ask."""

    name: str
    system: str
    ask: str


# --------------------------------------------------------------------------- #
# Production style (selected by the prompt-variant harness — see
# scripts/research / the comparison summary). Conviction-ranked + feedback-aware,
# with the order-leakage guard always first.
# --------------------------------------------------------------------------- #

_ORDER_GUARD = (
    "You must NEVER output an order, ticket, position size, lot/contract count to "
    "execute, or any instruction to trade — analysis only. Base everything ONLY on the "
    "provided regime/signal context and rule-based anchors; do not invent prices, "
    "levels, or positions."
)

DEFAULT_STYLE = TacticalPromptStyle(
    # Selected by the prompt-variant harness: a synthesis of the strongest elements —
    # V3's scannable conviction table + V2's adversarial "anchors I'd fade" + a
    # monitorable invalidation per idea + feedback-aware revision.
    name="ranked_adversarial_feedback",
    system=(
        "You are a macro/market TACTICAL RESEARCH partner for a single operator, working in an "
        "interactive dialog. Research and synthesize SHORT-TERM, INDEPENDENT trade ideas (macro / "
        "rates / FX / volatility / commodity / sector — e.g. de-dollarization, risk-off, short-VIX "
        "carry, trend persistence, curve steepeners, sector rotation, commodity relative-value), "
        "distinct from base-position option overlays. Rank by conviction, be specific about the "
        "expression and the evidence, and PRESSURE-TEST rather than cheerlead: say which rule-based "
        "anchors look weak or crowded and would be faded. When the operator gives feedback, REVISE "
        "specifically to it — drop what they reject, deepen what they ask for — while keeping prior "
        "grounding. " + _ORDER_GUARD
    ),
    ask=(
        "Respond in tight markdown:\n"
        "**Macro read** — 1-2 sentences on the regime/signal picture; note any forward-vs-momentum "
        "divergence.\n"
        "**Top tactical ideas** — a compact markdown table ranked by conviction (max 4 rows), columns: "
        "Conviction (High/Med/Low) | Trade (instrument/expression, NO size) | Evidence | Monitorable "
        "invalidation (a level/condition the operator could actually watch).\n"
        "**Anchors I'd fade** — which rule-based anchors look weak/crowded and why (1-2 lines).\n"
        "**Biggest risk** — one line: the main way this whole stance is wrong now.\n"
        "Never output an order or a size."
    ),
)


@dataclass(frozen=True)
class TacticalBrief:
    brief: str
    model: str = ""
    prompt_tokens: int | None = None
    completion_tokens: int | None = None


def _context_lines(ctx: Any) -> str:
    parts = [
        f"- regime: {getattr(ctx, 'regime_effective', '') or getattr(ctx, 'regime', '') or '?'} "
        f"(confidence {getattr(ctx, 'confidence', '') or '?'}; engine label "
        f"{getattr(ctx, 'regime_label_raw', '') or 'n/a'})",
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


def build_user_turn(context: Any, ideas: list, *, ask: str) -> str:
    """The first user message: context + grounded anchors + the response ask."""
    return (
        f"## Regime + signal context (as of {getattr(context, 'as_of', '') or 'latest'})\n"
        f"{_context_lines(context)}\n\n"
        f"## Rule-based idea anchors (already grounded)\n"
        f"{_anchor_lines(ideas)}\n\n"
        f"{ask}"
    )


def build_tactical_messages(context: Any, ideas: list, *, style: TacticalPromptStyle = DEFAULT_STYLE) -> list[dict]:
    """The initial conversation: a system (framing/guard) turn + the user turn."""
    return [
        {"role": "system", "content": style.system},
        {"role": "user", "content": build_user_turn(context, ideas, ask=style.ask)},
    ]


def continue_messages(messages: list[dict], assistant_text: str, feedback: str) -> list[dict]:
    """Extend a conversation with the model's last brief + the operator's feedback turn."""
    return [
        *messages,
        {"role": "assistant", "content": assistant_text},
        {"role": "user", "content": feedback.strip()},
    ]


def build_tactical_prompt(context: Any, ideas: list, *, style: TacticalPromptStyle = DEFAULT_STYLE) -> str:
    """The full first-turn prompt as one string (system guard + user turn). Kept for
    callers/tests that want the rendered text rather than the messages array."""
    return f"{style.system}\n\n{build_user_turn(context, ideas, ask=style.ask)}"


def _parse_brief(resp: dict, cfg: GatewayConfig) -> TacticalBrief:
    choices = resp.get("choices") or []
    content = (choices[0].get("message") or {}).get("content", "") if choices else ""
    usage = resp.get("usage") or {}
    return TacticalBrief(
        brief=(content or "").strip(),
        model=str(resp.get("model", cfg.model)),
        prompt_tokens=usage.get("prompt_tokens"),
        completion_tokens=usage.get("completion_tokens"),
    )


def request_tactical_chat(
    *,
    messages: list[dict],
    config: GatewayConfig | None = None,
    token: str | None = None,
    post: Callable[..., dict] = post_chat_completion,
) -> TacticalBrief:
    """POST a full messages array to the gateway and parse the brief. The multi-turn seam.

    Raises :class:`~market_helper.trade_advisor.ai.gateway.GatewayAuthMissing` when no
    token is configured and :class:`GatewayError` on transport failure — the UI catches
    both and shows an explainer (the rule-based anchors are unaffected).
    """
    cfg = config or GatewayConfig.from_env()
    tok = token if token is not None else resolve_gateway_token()
    payload = {"model": cfg.model, "messages": messages, "temperature": 0.3}
    return _parse_brief(post(config=cfg, token=tok, payload=payload), cfg)


def request_tactical_brief(
    *,
    context: Any,
    ideas: list | None = None,
    style: TacticalPromptStyle = DEFAULT_STYLE,
    config: GatewayConfig | None = None,
    token: str | None = None,
    post: Callable[..., dict] = post_chat_completion,
) -> TacticalBrief:
    """One-shot initial brief (builds the messages array, posts, parses)."""
    messages = build_tactical_messages(context, ideas or [], style=style)
    return request_tactical_chat(messages=messages, config=config, token=token, post=post)
