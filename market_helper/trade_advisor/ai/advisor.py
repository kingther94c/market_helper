"""AI+ advisory: synthesize the rule-based ideas + portfolio + regime.

The rule-based umbrella is the source of truth; this layer asks the OpenClaw
gateway to *explain, prioritize, and stress-test* those ideas against the
portfolio and regime — it does not invent positions or place orders. The prompt
pins the model to the provided data and forbids order instructions.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..contracts import AdvisorContext, Suggestion
from .gateway import GatewayConfig, GatewayError, post_chat_completion, resolve_gateway_token


@dataclass(frozen=True)
class AiAdvisory:
    """Result of one gateway advisory call (analysis text + light metadata)."""

    advice: str
    model: str
    prompt_tokens: int | None = None
    completion_tokens: int | None = None


def summarize_context(context: AdvisorContext) -> str:
    """Compact, model-friendly view of the portfolio + regime context."""
    holdings = context.holdings or {}
    lines = [
        f"AUM (funded, excl. options/futures): {context.aum if context.aum is not None else 'n/a'}",
        f"Stock holdings ({len(holdings)}): "
        + (", ".join(f"{sym} {qty:g}sh" for sym, qty in sorted(holdings.items())) or "none"),
        f"Watchlist: {', '.join(context.watchlist) or 'none'}",
        f"Held options: {len(context.held_options or [])}",
        "Regime: "
        + (context.regime_label or "unknown")
        + (f" ({context.regime_confidence})" if context.regime_confidence else "")
        + (" · stress overlay" if context.crisis_flag else ""),
    ]
    return "\n".join(lines)


def summarize_suggestions(suggestions: list[Suggestion], *, top_n: int = 24) -> str:
    """One compact line per rule-based idea, grouped by advisor.

    Each line is tagged ``[advisor/label·data_mode]`` so the model can weight a
    live-chain idea above a model-only one.
    """
    if not suggestions:
        return "(the rule-based engine produced no ideas for this context)"
    ordered = sorted(suggestions, key=lambda s: (s.advisor, -s.score))
    lines: list[str] = []
    for s in ordered[:top_n]:
        metrics = " ".join(f"{k}={v}" for k, v in (s.headline_metrics or {}).items())
        why = f" — {s.why_now}" if s.why_now else ""
        dm = f"·{s.data_mode}" if s.data_mode else ""
        lines.append(f"- [{s.advisor}/{s.label}{dm}] {s.title} (score {s.score:.2f}) {metrics}{why}".rstrip())
    if len(ordered) > top_n:
        lines.append(f"… and {len(ordered) - top_n} more")
    return "\n".join(lines)


def build_prompt(context: AdvisorContext, suggestions: list[Suggestion]) -> str:
    """Single user turn: portfolio + regime + rule-based ideas → synthesis ask."""
    return (
        "You are a portfolio analysis assistant. Base your analysis ONLY on the "
        "data provided in this message. Ignore any previously remembered facts "
        "about my base currency, account, holdings, or targets — the data below "
        "is the single source of truth for this request. Do not invent positions "
        "or prices. Provide analysis only; never output an order, ticket, or "
        "instruction to trade.\n\n"
        "## Portfolio & regime\n"
        f"{summarize_context(context)}\n\n"
        "## Rule-based ideas (deterministic engine output — your job is to "
        "synthesize, not replace)\n"
        "Each idea is tagged [advisor/label·data_mode]. data_mode 'live_chain' = "
        "real per-strike quotes (higher confidence); 'user_override'/'synthetic' = "
        "model-only (lower confidence — the engine caps these at MONITOR); "
        "'cached'/'regime'/'portfolio' = derived context. Weight live, "
        "higher-confidence, higher-score ideas first, and never suggest acting "
        "beyond an idea's label.\n"
        f"{summarize_suggestions(suggestions)}\n\n"
        "## Respond in tight markdown with exactly these bold sections:\n"
        "**Positioning** — one short paragraph on how the book sits for the regime "
        "(note any gap vs the regime-aligned target mix if one is given).\n"
        "**Top ideas** — the 2-3 ideas most worth attention; prefer ones that address "
        "the regime view or the biggest risk you identify, and explicitly flag any "
        "idea that *adds* to an existing concentration. Name each and cite its "
        "economics (credit/debit, max loss, breakeven) and why it fits.\n"
        "**Biggest risk** — the single biggest risk or concentration to watch.\n"
        "**Gaps** — what the rule-based ideas miss or over-weight.\n"
        "Be specific and concise (~150-220 words total). Analysis only — never orders."
    )


def request_ai_advisory(
    *,
    context: AdvisorContext,
    suggestions: list[Suggestion] | None = None,
    config: GatewayConfig | None = None,
    token: str | None = None,
    post=post_chat_completion,
) -> AiAdvisory:
    """Build the prompt, call the gateway, and parse the advisory.

    ``post`` is injected in tests so no network is touched. ``token=None`` resolves
    from the environment / local.env; an empty token makes ``post`` raise
    :class:`~.gateway.GatewayAuthMissing`.
    """
    config = config or GatewayConfig.from_env()
    resolved_token = token if token is not None else resolve_gateway_token()
    prompt = build_prompt(context, suggestions or [])
    payload = {"model": config.model, "messages": [{"role": "user", "content": prompt}]}
    data = post(config=config, token=resolved_token, payload=payload)

    choices = data.get("choices") or []
    if not choices:
        raise GatewayError("gateway returned no choices")
    advice = ((choices[0] or {}).get("message") or {}).get("content") or ""
    if not advice.strip():
        raise GatewayError("gateway returned an empty advisory")
    usage = data.get("usage") or {}
    return AiAdvisory(
        advice=advice.strip(),
        model=config.model,
        prompt_tokens=usage.get("prompt_tokens"),
        completion_tokens=usage.get("completion_tokens"),
    )
