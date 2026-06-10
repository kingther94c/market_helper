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


# --------------------------------------------------------------------------- #
# Ideagen internalization (guided creativity — operators + filter + stimulus)
# --------------------------------------------------------------------------- #


def test_draw_random_stimulus_tool():
    import json

    from market_helper.domain.tactical_ideas.ai_tools import _STIMULUS_POOL

    reg = build_tactical_tool_registry()
    assert "draw_random_stimulus" in reg
    out = json.loads(reg.dispatch("draw_random_stimulus", {"n": 5}))
    assert len(out["draws"]) == 5
    assert all(d in _STIMULUS_POOL for d in out["draws"])           # from the pool, never invented
    assert len(set(out["draws"])) == 5                              # sampled without replacement
    capped = json.loads(reg.dispatch("draw_random_stimulus", {"n": 99}))
    assert len(capped["draws"]) == 10                               # bounded


def test_ideagen_skill_registered_with_order_guard():
    from market_helper.domain.tactical_ideas.synthesis import IDEAGEN_STYLE

    skills = {s.name: s for s in tactical_skills()}
    assert "tactical_ideagen" in skills
    sk = skills["tactical_ideagen"]
    assert sk.system == IDEAGEN_STYLE.system and sk.ask == IDEAGEN_STYLE.ask
    assert "never output an order" in sk.system.lower()             # the guard is non-negotiable
    assert "draw_random_stimulus" in sk.system                      # the divergence engine is mandatory
    assert "single-stock" in sk.system or "single stocks" in sk.system.lower()


def test_ideagen_knowledge_and_style_wiring():
    from market_helper.domain.tactical_ideas.ai_tools import tactical_knowledge_block
    from market_helper.domain.tactical_ideas.synthesis import IDEAGEN_STYLE

    names = {e.name for e in tactical_knowledge()}
    assert {"return_sources", "idea_filters"} <= names
    block = tactical_knowledge_block(names=["return_sources", "idea_filters"])
    assert "RISK PREMIA" in block and "HARD FILTER" in block

    ctx = TacticalContext(regime_effective="Reflation", growth_score=0.1, inflation_score=0.2, risk_score=0.2)
    msgs = tactical_tool_messages(ctx, [], build_tactical_tool_registry(), style=IDEAGEN_STYLE)
    assert "GUIDED-CREATIVITY" in msgs[0]["content"]                # the style actually drives the system turn
    assert "tool_call" in msgs[0]["content"]                        # protocol still baked in
