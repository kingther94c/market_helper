"""Tactical AI synthesis: prompt guards + hermetic request (no network)."""

from __future__ import annotations

from market_helper.domain.tactical_ideas.signals import TacticalContext, generate_tactical_ideas
from market_helper.domain.tactical_ideas.synthesis import build_tactical_prompt, request_tactical_brief


def _ctx():
    return TacticalContext(regime="Reflation", confidence="Medium", crisis=False,
                           growth_score=0.1, inflation_score=0.2, risk_score=0.2)


def test_prompt_pins_context_and_forbids_orders():
    ideas = generate_tactical_ideas(_ctx())
    prompt = build_tactical_prompt(_ctx(), ideas)
    assert "NEVER output an order" in prompt
    for section in ("**Macro read**", "**Top tactical ideas**", "**What the rules miss**", "**Biggest risk**"):
        assert section in prompt
    assert "Reflation" in prompt                       # pinned to the supplied context
    assert "[SHORT_USD]" in prompt or "SHORT_USD" in prompt  # anchors handed to the model


def test_request_brief_is_hermetic_via_injected_post():
    captured = {}

    def fake_post(*, config, token, payload):
        captured["token"] = token
        captured["payload"] = payload
        return {
            "model": "openclaw/trade-advisor",
            "choices": [{"message": {"content": "**Macro read**\nReflation tape."}}],
            "usage": {"prompt_tokens": 42, "completion_tokens": 18},
        }

    brief = request_tactical_brief(context=_ctx(), ideas=[], token="secret-tok", post=fake_post)
    assert brief.brief.startswith("**Macro read**")
    assert brief.prompt_tokens == 42 and brief.completion_tokens == 18
    assert captured["token"] == "secret-tok"
    assert captured["payload"]["messages"][0]["role"] == "user"
