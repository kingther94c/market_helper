import market_helper.domain.integration.services.trade_advisor as ta


def _positions():
    return [
        {
            "as_of": "2026-06-01T00:00:00+00:00",
            "symbol": "AAPL",
            "weight": "0.6",
            "market_value": "60000",
            "currency": "USD",
            "unrealized_pnl": "5000",
        },
        {
            "as_of": "2026-06-01T00:00:00+00:00",
            "symbol": "CASH",
            "weight": "0.4",
            "market_value": "40000",
            "currency": "USD",
            "unrealized_pnl": "0",
        },
    ]


def _regime():
    return {
        "date": "2026-05-31",
        "final_regime": "Up Growth / Up Inflation",
        "confidence": "High",
        "final_growth_score": 0.45,
        "final_inflation_score": 0.32,
        "risk_overlay_on": False,
        "disagreement_flag": False,
    }


def test_build_prompt_includes_positions_and_regime() -> None:
    prompt = ta.build_advisor_prompt(_positions(), _regime())
    assert "AAPL" in prompt
    assert "60.0%" in prompt  # weight rendered as percent
    assert "Up Growth / Up Inflation" in prompt
    assert "actionable considerations" in prompt
    # Data-only guard: mitigates ChatGPT account-memory bleed into advisories.
    assert "single source of truth" in prompt


def test_summarize_regime_handles_missing() -> None:
    assert "no regime snapshot" in ta.summarize_regime(None).lower()


def test_request_advice_posts_and_parses(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_post(*, endpoint_base_url, token, payload, session_key=None, timeout=120):
        captured["endpoint_base_url"] = endpoint_base_url
        captured["token"] = token
        captured["payload"] = payload
        captured["session_key"] = session_key
        return {
            "choices": [{"message": {"content": "  Stay diversified; trim AAPL.  "}}],
            "usage": {"prompt_tokens": 123, "completion_tokens": 45},
        }

    monkeypatch.setattr(ta, "post_chat_completion", fake_post)

    result = ta.request_advice(
        positions=_positions(),
        regime_snapshot=_regime(),
        endpoint_base_url="http://127.0.0.1:18789/v1",
        token="tok",
        model="openclaw/trade-advisor",
        session_key="conv-1",
    )

    assert result.advice == "Stay diversified; trim AAPL."
    assert result.prompt_tokens == 123
    assert result.completion_tokens == 45
    assert captured["session_key"] == "conv-1"
    assert captured["token"] == "tok"
    assert captured["payload"]["model"] == "openclaw/trade-advisor"
    assert captured["payload"]["messages"][0]["role"] == "user"


def test_request_advice_raises_on_no_choices(monkeypatch) -> None:
    monkeypatch.setattr(ta, "post_chat_completion", lambda **_: {"choices": []})
    try:
        ta.request_advice(
            positions=_positions(),
            regime_snapshot=None,
            endpoint_base_url="http://x/v1",
            token="t",
            model="m",
        )
    except RuntimeError as exc:
        assert "no choices" in str(exc)
    else:  # pragma: no cover - explicit failure path
        raise AssertionError("expected RuntimeError when no choices are returned")


def test_render_markdown_contains_advice_and_disclaimer() -> None:
    result = ta.AdvisorResult(
        advice="Rotate toward quality.",
        model="openclaw/trade-advisor",
        prompt_tokens=10,
        completion_tokens=4,
    )
    markdown = ta.render_advisory_markdown(
        positions=_positions(),
        regime_snapshot=_regime(),
        result=result,
    )
    assert "Rotate toward quality." in markdown
    assert "Up Growth / Up Inflation" in markdown
    assert "not investment advice" in markdown.lower()
