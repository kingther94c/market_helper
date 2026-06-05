"""AI+ advisor: prompt building + advisory parsing (hermetic, injected post)."""

from __future__ import annotations

import pytest

from market_helper.trade_advisor.ai import advisor as ai
from market_helper.trade_advisor.ai.gateway import GatewayAuthMissing, GatewayConfig, GatewayError
from market_helper.trade_advisor.contracts import AdvisorContext, Suggestion


def _ctx():
    return AdvisorContext(
        as_of="2026-06-05",
        holdings={"SPY": 200.0, "QQQ": 100.0},
        aum=500_000.0,
        watchlist=["NVDA"],
        regime_label="Reflation",
        regime_confidence="High",
        crisis_flag=True,
    )


def _suggestions():
    return [
        Suggestion(advisor="option", suggestion_id="o1", as_of="t", title="COVERED_CALL · SPY",
                   subject="SPY", category="INCOME", label="MONITOR", score=0.8,
                   why_now="IV elevated", headline_metrics={"net": "credit 250"}),
        Suggestion(advisor="fx_hedge", suggestion_id="f1", as_of="t", title="FX hedge target · USD/SGD",
                   subject="USD/SGD", category="FX_HEDGE", label="MONITOR", score=0.7),
    ]


# --------------------------------------------------------------------------- #
# Summaries + prompt
# --------------------------------------------------------------------------- #


def test_summarize_context_has_key_facts():
    text = ai.summarize_context(_ctx())
    assert "500000" in text.replace(",", "") or "500000.0" in text
    assert "SPY" in text and "Reflation" in text and "stress overlay" in text


def test_summarize_suggestions_empty_note():
    assert "no ideas" in ai.summarize_suggestions([]).lower()


def test_summarize_suggestions_lists_ideas():
    text = ai.summarize_suggestions(_suggestions())
    assert "option/MONITOR" in text and "COVERED_CALL · SPY" in text
    assert "fx_hedge/MONITOR" in text


def test_build_prompt_pins_data_and_forbids_orders():
    prompt = ai.build_prompt(_ctx(), _suggestions())
    assert "single source of truth" in prompt
    assert "never output an order" in prompt
    assert "Rule-based ideas" in prompt and "COVERED_CALL · SPY" in prompt


# --------------------------------------------------------------------------- #
# request_ai_advisory
# --------------------------------------------------------------------------- #


def test_request_parses_advisory():
    def fake_post(*, config, token, payload):
        assert token == "tkn" and payload["model"] == config.model
        return {"choices": [{"message": {"content": "  Positioned for reflation.  "}}],
                "usage": {"prompt_tokens": 120, "completion_tokens": 80}}

    out = ai.request_ai_advisory(
        context=_ctx(), suggestions=_suggestions(),
        config=GatewayConfig(model="openclaw/trade-advisor"), token="tkn", post=fake_post,
    )
    assert out.advice == "Positioned for reflation."
    assert out.model == "openclaw/trade-advisor"
    assert out.prompt_tokens == 120 and out.completion_tokens == 80


def test_request_no_choices_raises():
    with pytest.raises(GatewayError):
        ai.request_ai_advisory(context=_ctx(), token="t", post=lambda **k: {"choices": []})


def test_request_empty_content_raises():
    bad = {"choices": [{"message": {"content": "   "}}]}
    with pytest.raises(GatewayError):
        ai.request_ai_advisory(context=_ctx(), token="t", post=lambda **k: bad)


def test_request_without_token_raises_auth_missing():
    # token="" + the real post boundary → GatewayAuthMissing, no network touched.
    with pytest.raises(GatewayAuthMissing):
        ai.request_ai_advisory(context=_ctx(), suggestions=[], token="")
