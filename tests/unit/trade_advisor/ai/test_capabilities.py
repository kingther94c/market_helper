"""The advisor-AI capability manifest assembles core + tactical contributions (no network)."""

from __future__ import annotations

from market_helper.trade_advisor.ai.capabilities import build_advisor_ai_capabilities


def test_manifest_includes_core_and_tactical():
    cap = build_advisor_ai_capabilities()
    # tactical read-only tools registered
    for name in ("get_regime_snapshot", "get_policy_expert", "get_tactical_anchors", "get_price_trend"):
        assert name in cap.tools
    # the production skill + alternatives, all read-only prompts
    assert cap.skills.get("tactical_default") is not None
    assert {s.name for s in cap.skills.for_task("tactical_brief")} >= {"tactical_default", "tactical_adversarial", "tactical_terse"}
    # core + tactical knowledge
    assert cap.knowledge.get("read_only_invariant") is not None
    assert cap.knowledge.get("tactical_themes") is not None


def test_manifest_serializes_and_describes():
    cap = build_advisor_ai_capabilities()
    d = cap.as_dict()
    assert any(t["name"] == "get_regime_snapshot" and t["read_only"] for t in d["tools"])
    assert any(s["task"] == "tactical_brief" for s in d["skills"])
    text = cap.describe()
    assert "Advisor AI capabilities" in text and "get_regime_snapshot" in text
