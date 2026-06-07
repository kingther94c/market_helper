"""Skills + knowledge registries + core knowledge (no network)."""

from __future__ import annotations

import pytest

from market_helper.trade_advisor.ai.skills import (
    KnowledgeBook,
    KnowledgeEntry,
    PromptSkill,
    SkillRegistry,
    build_core_knowledge,
    knowledge_system_block,
)


def test_skill_registry_by_task():
    reg = SkillRegistry()
    reg.register(PromptSkill(name="s1", task="tactical_brief", when_to_use="w", system="SYS", ask="ASK"))
    reg.register(PromptSkill(name="s2", task="other", when_to_use="w", system="x", ask="y"))
    assert reg.get("s1").system == "SYS"
    assert {s.name for s in reg.for_task("tactical_brief")} == {"s1"}
    with pytest.raises(ValueError):
        reg.register(PromptSkill(name="s1", task="t", when_to_use="w", system="x", ask="y"))  # dup


def test_knowledge_book_tags_and_block():
    book = KnowledgeBook()
    book.register(KnowledgeEntry("k", "Topic", "content body", ("a", "b")))
    assert book.by_tag("a") and not book.by_tag("z")
    assert "content body" in knowledge_system_block(book, names=["k"])


def test_core_knowledge_carries_the_invariant():
    kb = build_core_knowledge()
    assert kb.get("read_only_invariant") is not None
    assert kb.by_tag("invariant")
    block = knowledge_system_block(kb, names=["read_only_invariant"])
    assert "NEVER output an order" in block
