"""Tactical AI synthesis: prompt guards, messages array, multi-turn feedback (no network)."""

from __future__ import annotations

from market_helper.domain.tactical_ideas.signals import TacticalContext, generate_tactical_ideas
from market_helper.domain.tactical_ideas.synthesis import (
    TacticalPromptStyle,
    build_tactical_messages,
    build_tactical_prompt,
    continue_messages,
    request_tactical_brief,
    request_tactical_chat,
)


def _ctx():
    return TacticalContext(regime="Reflation", confidence="Medium", crisis=False,
                           growth_score=0.1, inflation_score=0.2, risk_score=0.2)


def _fake_post(reply="**Macro read**\nReflation tape.", captured=None):
    def post(*, config, token, payload):
        if captured is not None:
            captured["token"] = token
            captured["payload"] = payload
        return {
            "model": "openclaw/trade-advisor",
            "choices": [{"message": {"content": reply}}],
            "usage": {"prompt_tokens": 42, "completion_tokens": 18},
        }
    return post


def test_messages_have_system_guard_and_user_context():
    ideas = generate_tactical_ideas(_ctx())
    messages = build_tactical_messages(_ctx(), ideas)
    assert [m["role"] for m in messages] == ["system", "user"]
    assert "NEVER output an order" in messages[0]["content"]   # order guard in the system turn
    user = messages[1]["content"]
    for section in ("**Macro read**", "**Top tactical ideas**", "**Anchors I'd fade**", "**Biggest risk**"):
        assert section in user
    assert "Reflation" in user                                 # pinned to the supplied context
    assert "[SHORT_USD]" in user                               # grounded anchors handed to the model


def test_build_tactical_prompt_renders_full_text():
    prompt = build_tactical_prompt(_ctx(), generate_tactical_ideas(_ctx()))
    assert "NEVER output an order" in prompt and "**Biggest risk**" in prompt


def test_request_brief_is_hermetic_and_parses():
    captured = {}
    brief = request_tactical_brief(context=_ctx(), ideas=[], token="secret-tok", post=_fake_post(captured=captured))
    assert brief.brief.startswith("**Macro read**")
    assert brief.prompt_tokens == 42 and brief.completion_tokens == 18
    assert captured["token"] == "secret-tok"
    roles = [m["role"] for m in captured["payload"]["messages"]]
    assert roles[0] == "system" and roles[-1] == "user"


def test_continue_messages_injects_feedback_turn():
    captured = {}
    messages = build_tactical_messages(_ctx(), generate_tactical_ideas(_ctx()))
    convo = continue_messages(messages, "prior brief text", "Drop short-vol; only the 2 best, be concise.")
    request_tactical_chat(messages=convo, token="t", post=_fake_post(captured=captured))
    sent = captured["payload"]["messages"]
    assert sent[-2] == {"role": "assistant", "content": "prior brief text"}
    assert sent[-1]["role"] == "user" and "Drop short-vol" in sent[-1]["content"]


def test_style_swaps_the_system_framing():
    style = TacticalPromptStyle(name="t", system="SYSTEM-XYZ never order", ask="ASK-XYZ")
    messages = build_tactical_messages(_ctx(), [], style=style)
    assert messages[0]["content"] == "SYSTEM-XYZ never order"
    assert messages[1]["content"].endswith("ASK-XYZ")
