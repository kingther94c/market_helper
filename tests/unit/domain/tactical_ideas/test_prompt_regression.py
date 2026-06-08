"""Safety validation — the production tactical prompt keeps its guardrails (hermetic).

A regression net so a future prompt edit can't quietly drop: the no-order/size guard,
the research-brief (not trade-candidate) framing, the WATCHLIST ceiling, scarcity, or
the forced 'Why NOT trade' section.
"""

from __future__ import annotations

from market_helper.domain.tactical_ideas.ai_tools import tactical_skills
from market_helper.domain.tactical_ideas.signals import TacticalContext, generate_tactical_ideas
from market_helper.domain.tactical_ideas.synthesis import (
    _ORDER_GUARD,
    DEFAULT_STYLE,
    build_tactical_messages,
)


def test_order_guard_forbids_orders_and_sizes():
    g = _ORDER_GUARD.lower()
    assert "never output an order" in g and "size" in g and "analysis only" in g


def test_production_prompt_is_research_not_trade():
    sys = DEFAULT_STYLE.system
    assert "RESEARCH-BRIEF GENERATOR" in sys
    assert "never trade candidates" in sys.lower() and "watchlist at most" in sys.lower()
    assert _ORDER_GUARD in sys
    assert "FEWER" in sys and "2-3 max" in sys            # scarcity


def test_ask_requires_a_why_not_trade_section():
    assert "Why NOT trade" in DEFAULT_STYLE.ask
    assert "research brief to critique, not a trade list" in DEFAULT_STYLE.ask
    assert "Never output an order" in DEFAULT_STYLE.ask


def test_all_tactical_skills_embed_the_order_guard():
    skills = tactical_skills()
    assert skills
    for sk in skills:
        assert "never output an order" in sk.system.lower()


def test_built_messages_embed_the_guard_and_why_not():
    ctx = TacticalContext(regime_effective="Reflation", growth_score=0.1, inflation_score=0.2, risk_score=0.2)
    msgs = build_tactical_messages(ctx, generate_tactical_ideas(ctx))
    assert msgs[0]["role"] == "system" and "never output an order" in msgs[0]["content"].lower()
    assert msgs[1]["role"] == "user" and "Why NOT trade" in msgs[1]["content"]
