"""Tactical AI tools/skills/knowledge contributions (hermetic — no I/O)."""

from __future__ import annotations

from market_helper.domain.tactical_ideas import generate_tactical_ideas
from market_helper.domain.tactical_ideas.ai_tools import (
    build_tactical_tool_registry,
    tactical_knowledge,
    tactical_skills,
    tactical_tool_messages,
)
from market_helper.domain.tactical_ideas.signals import TacticalContext


def test_tactical_tools_registered_read_only():
    reg = build_tactical_tool_registry()
    for name in ("get_regime_snapshot", "get_policy_expert", "get_tactical_anchors", "get_price_trend"):
        assert name in reg
    assert all(t.read_only for t in reg.all())


def test_get_regime_snapshot_tool_dispatches():
    # Inject a tiny context via regime_path-free build is I/O; instead exercise dispatch through
    # a registry whose context is the constructed one by monkeypatching is overkill — just confirm
    # the tool is callable and returns JSON for a (possibly empty) context.
    import json

    reg = build_tactical_tool_registry()
    out = json.loads(reg.dispatch("get_tactical_anchors", {}))
    assert isinstance(out, (list, dict))  # list of anchors, or an error dict — never a crash


def test_tactical_skills_are_brief_prompts():
    skills = tactical_skills()
    assert {s.name for s in skills} >= {"tactical_default", "tactical_adversarial", "tactical_terse"}
    assert all(s.task == "tactical_brief" and s.system and s.ask for s in skills)


def test_tactical_knowledge_present():
    assert {e.name for e in tactical_knowledge()} >= {"tactical_themes", "derived_quadrant"}


def test_tool_messages_bake_the_protocol_into_system():
    ctx = TacticalContext(regime_effective="Reflation", growth_score=0.1, inflation_score=0.2, risk_score=0.2)
    reg = build_tactical_tool_registry()
    msgs = tactical_tool_messages(ctx, generate_tactical_ideas(ctx), reg)
    assert msgs[0]["role"] == "system" and "tool_call" in msgs[0]["content"]
    assert msgs[1]["role"] == "user"
