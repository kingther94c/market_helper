"""AI tool framework: registry, read-only enforcement, dispatch, structured-text loop (no network)."""

from __future__ import annotations

import json

import pytest

from market_helper.trade_advisor.ai.tools import (
    AiTool,
    AiToolRegistry,
    run_tool_chat,
    tool_protocol_instructions,
)


def _reg() -> AiToolRegistry:
    reg = AiToolRegistry()
    reg.tool("get_x", "get the x value", {"type": "object", "properties": {}, "additionalProperties": False})(lambda: {"x": 42})
    return reg


def test_read_only_is_enforced():
    reg = AiToolRegistry()
    with pytest.raises(ValueError):
        reg.register(AiTool(name="writer", description="d", parameters={}, fn=lambda: 1, read_only=False))


def test_dispatch_ok_unknown_and_error():
    reg = _reg()
    assert json.loads(reg.dispatch("get_x", {})) == {"x": 42}
    assert "error" in json.loads(reg.dispatch("missing", {}))

    def _boom():
        raise RuntimeError("kaboom")

    reg.tool("boom", "raises", {"type": "object", "properties": {}})(_boom)
    out = json.loads(reg.dispatch("boom", {}))
    assert "error" in out and "kaboom" in out["error"]


def test_to_openai_and_protocol_text():
    spec = _reg().to_openai_tools()[0]
    assert spec["type"] == "function" and spec["function"]["name"] == "get_x"
    txt = tool_protocol_instructions(_reg())
    assert "tool_call" in txt and "get_x" in txt


class _FakePost:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def __call__(self, *, config, token, payload):
        self.calls.append(payload)
        reply = self.replies[min(len(self.calls) - 1, len(self.replies) - 1)]
        return {"model": "m", "choices": [{"message": {"content": reply}}], "usage": {"prompt_tokens": 1, "completion_tokens": 2}}


def test_loop_dispatches_tool_then_answers():
    reg = _reg()
    fake = _FakePost(['```tool_call\n{"name": "get_x", "arguments": {}}\n```', "The x value is 42."])
    res = run_tool_chat(messages=[{"role": "user", "content": "what is x?"}], registry=reg, token="t", post=fake)
    assert [t["name"] for t in res.tool_calls] == ["get_x"]
    assert "42" in res.text
    # protocol got injected into a system turn on the first call
    assert any(m["role"] == "system" and "tool_call" in m["content"] for m in fake.calls[0]["messages"])
    # the tool result was fed back before the final answer
    assert any("tool_result" in m.get("content", "") for m in fake.calls[1]["messages"])


def test_no_tool_call_is_one_shot():
    fake = _FakePost(["Just answering directly, no tool."])
    res = run_tool_chat(messages=[{"role": "user", "content": "hi"}], registry=_reg(), token="t", post=fake)
    assert res.tool_calls == [] and len(fake.calls) == 1 and "directly" in res.text


def test_max_rounds_caps_and_forces_final():
    block = '```tool_call\n{"name": "get_x", "arguments": {}}\n```'
    fake = _FakePost([block, block, "forced final answer"])
    res = run_tool_chat(messages=[{"role": "user", "content": "q"}], registry=_reg(), token="t", post=fake, max_rounds=2)
    assert len(res.tool_calls) == 2          # two tool rounds, then a forced final pass
    assert len(fake.calls) == 3 and res.text == "forced final answer"


def test_inject_protocol_false_leaves_system_untouched():
    fake = _FakePost(["answer"])
    run_tool_chat(
        messages=[{"role": "system", "content": "S"}, {"role": "user", "content": "u"}],
        registry=_reg(), token="t", post=fake, inject_protocol=False,
    )
    assert fake.calls[0]["messages"][0]["content"] == "S"  # no protocol appended


def test_no_registry_is_plain_chat():
    fake = _FakePost(["plain"])
    res = run_tool_chat(messages=[{"role": "user", "content": "u"}], registry=None, token="t", post=fake)
    assert res.text == "plain" and "tools" not in fake.calls[0]
