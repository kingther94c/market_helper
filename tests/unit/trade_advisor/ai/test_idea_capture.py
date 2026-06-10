"""Idea-block capture — the accumulate loop's parser + Suggestion mapping."""

from __future__ import annotations

from market_helper.trade_advisor.ai.idea_capture import (
    IDEA_BLOCK_INSTRUCTIONS,
    captured_suggestion,
    parse_idea_blocks,
)
from market_helper.trade_advisor.contracts import LABEL_WATCHLIST, TIER_RESEARCH

_REPLY = """Here is my read on the anchors.

```idea
TITLE: Short USD vs Asia FX basket
STANCE: short
SUBJECT: USD
THESIS: De-dollarization flows persist; DXY trend is rolling over
  while Asian CB demand stays firm.
EXPRESSION: long 6J / long CNH proxy via futures
CONFIDENCE: medium
RISK: A hawkish Fed repricing squeezes USD shorts.
INVALIDATION: DXY reclaiming its 200d with breadth.
HORIZON: 1-3 months
```

Some prose between blocks that should be ignored.

```idea
title: Long gold dips
stance: long
subject: GLD
thesis: Real-rate tailwind plus central-bank bid.
confidence: NOT_A_LEVEL
```

```idea
STANCE: long
THESIS: missing a title — must be skipped
```
"""


def test_parse_idea_blocks_extracts_and_tolerates():
    blocks = parse_idea_blocks(_REPLY)
    assert len(blocks) == 2                              # third block lacks TITLE → skipped
    first = blocks[0]
    assert first["title"] == "Short USD vs Asia FX basket"
    assert "DXY trend is rolling over while Asian CB demand" in first["thesis"]  # continuation line folded
    assert first["horizon"] == "1-3 months"
    assert blocks[1]["title"] == "Long gold dips"        # lowercase keys tolerated


def test_parse_idea_blocks_never_raises_on_garbage():
    assert parse_idea_blocks("") == []
    assert parse_idea_blocks("```idea\ngarbage no keys\n```") == []
    assert parse_idea_blocks(None) == []


def test_captured_suggestion_is_capped_and_honest():
    s = captured_suggestion(parse_idea_blocks(_REPLY)[0], as_of="2026-06-10")
    assert s.advisor == "tactical" and s.category == "TACTICAL"
    assert s.decision_tier == TIER_RESEARCH
    assert s.label == LABEL_WATCHLIST                    # T4 can never be RESEARCH_READY
    assert s.data_mode == "synthetic"                    # AI-asserted, unverified
    assert s.assessment.data_quality == "synthetic"
    assert s.assessment.confidence == "medium"
    assert s.detail["direction"] == "short" and s.detail["source"] == "ai_plus_capture"
    assert s.risk and s.invalidation                     # research fields carried through
    assert "tactical_ai:short_usd_vs_asia_fx_basket:2026-06-10" == s.suggestion_id


def test_captured_suggestion_defaults_to_speculative():
    s = captured_suggestion({"title": "Long gold dips", "thesis": "x", "confidence": "NOT_A_LEVEL"},
                            as_of="2026-06-10")
    assert s.assessment.confidence == "speculative"      # unknown level → most conservative


def test_protocol_bans_order_size_fields():
    # The capture protocol must never invite sizes/orders (read-only invariant):
    # the ban is stated, and no order-like field key exists in the template.
    up = IDEA_BLOCK_INSTRUCTIONS.upper()
    assert "NO ORDER/SIZE FIELDS" in up
    for banned_key in ("SIZE:", "QUANTITY:", "CONTRACTS:", "ORDER:", "NOTIONAL:"):
        assert banned_key not in up


_DISCIPLINED = """```idea
TITLE: OPEX gamma tide
STANCE: long
SUBJECT: VIX
THESIS: Negative dealer gamma amplifies the pre-OPEX window.
MECHANISM: flows/positioning -> dealer gamma hedging around monthly OPEX
EXPRESSION: long /VX front calendar via listed options
CONFIDENCE: low
RISK: positive-gamma pin kills the move
INVALIDATION: gamma flips positive on the rally
SKEPTIC: OPEX effects are well-known and mostly arbitraged at index level
CHEAPEST_TEST: paper-track VX1-VX2 into the next two OPEX weeks
HORIZON: 2-6 weeks
```"""


def test_ideagen_discipline_fields_parse_and_map():
    blocks = parse_idea_blocks(_DISCIPLINED)
    assert len(blocks) == 1
    s = captured_suggestion(blocks[0], as_of="2026-06-10")
    assert s.detail["mechanism"].startswith("flows/positioning")
    assert "arbitraged" in s.detail["skeptic"]
    assert "paper-track" in s.detail["cheapest_test"]
    # And the card body surfaces them (presentation contract).
    from market_helper.presentation.dashboard.pages.trade_advisor.cards import tactical_facts

    facts = dict(tactical_facts(s.detail))
    assert facts["Mechanism (return source)"].startswith("flows/positioning")
    assert facts["Skeptic's view"] and facts["Cheapest first test"]


def test_discipline_fields_optional():
    s = captured_suggestion({"title": "Bare idea", "thesis": "x"}, as_of="2026-06-10")
    assert "mechanism" not in s.detail and "skeptic" not in s.detail   # absent, not fabricated
