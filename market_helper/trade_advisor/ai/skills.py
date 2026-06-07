"""Skills + knowledge for the advisor AI — the extensible, listable home for the
*injected prompts per task* and the reference *knowledge* the AI should hold.

- A :class:`PromptSkill` is a named **injected prompt for a task** (system framing +
  response ask + when-to-use) — the generalization of the tactical
  ``TacticalPromptStyle`` variants. The harness-selected production prompt and the
  alternatives register here as skills, so "what prompt do we use for task X" lives
  in one place.
- A :class:`KnowledgeEntry` is a reference fact the AI is grounded on (the read-only
  invariant, the honesty / data-mode ladder, the Growth×Inflation quadrant
  definitions, the cockpit module map). :func:`knowledge_system_block` renders a
  selection into a system-prompt block, or a ``get_knowledge`` tool can serve them
  on demand.

Generic + domain-agnostic: domains register their own skills/knowledge (see
``domain/tactical_ideas/ai_tools.py``). The whole set is assembled + listed by
``trade_advisor.ai.capabilities``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable


@dataclass(frozen=True)
class PromptSkill:
    """A named injected prompt for a task (system framing + response ask)."""

    name: str
    task: str            # the task this prompt serves, e.g. "tactical_brief"
    when_to_use: str
    system: str
    ask: str
    notes: str = ""


@dataclass(frozen=True)
class KnowledgeEntry:
    """A reference fact the advisor AI is grounded on."""

    name: str
    topic: str
    content: str
    tags: tuple[str, ...] = ()


class SkillRegistry:
    """The advisor AI's skills — injected prompts keyed by name, grouped by task."""

    def __init__(self) -> None:
        self._skills: dict[str, PromptSkill] = {}

    def register(self, skill: PromptSkill) -> None:
        if not skill.name:
            raise ValueError("skill needs a name")
        if skill.name in self._skills:
            raise ValueError(f"skill {skill.name!r} already registered")
        self._skills[skill.name] = skill

    def get(self, name: str) -> PromptSkill | None:
        return self._skills.get(name)

    def all(self) -> list[PromptSkill]:
        return list(self._skills.values())

    def keys(self) -> list[str]:
        return list(self._skills)

    def for_task(self, task: str) -> list[PromptSkill]:
        return [s for s in self._skills.values() if s.task == task]

    def __len__(self) -> int:
        return len(self._skills)

    def __contains__(self, name: str) -> bool:
        return name in self._skills


class KnowledgeBook:
    """The advisor AI's reference knowledge — facts it should hold, by name/tag."""

    def __init__(self) -> None:
        self._entries: dict[str, KnowledgeEntry] = {}

    def register(self, entry: KnowledgeEntry) -> None:
        if not entry.name:
            raise ValueError("knowledge entry needs a name")
        if entry.name in self._entries:
            raise ValueError(f"knowledge {entry.name!r} already registered")
        self._entries[entry.name] = entry

    def get(self, name: str) -> KnowledgeEntry | None:
        return self._entries.get(name)

    def all(self) -> list[KnowledgeEntry]:
        return list(self._entries.values())

    def keys(self) -> list[str]:
        return list(self._entries)

    def by_tag(self, tag: str) -> list[KnowledgeEntry]:
        return [e for e in self._entries.values() if tag in e.tags]

    def __len__(self) -> int:
        return len(self._entries)


def knowledge_system_block(book: KnowledgeBook, *, names: Iterable[str] | None = None) -> str:
    """Render selected (or all) knowledge entries as a system-prompt block."""
    entries = [book.get(n) for n in names] if names is not None else book.all()
    lines = [f"### {e.topic}: {e.name}\n{e.content}" for e in entries if e is not None]
    return "## Reference knowledge (hold these as ground truth)\n" + "\n\n".join(lines) if lines else ""


# --------------------------------------------------------------------------- #
# Core, domain-agnostic knowledge — the invariants every advisor-AI task shares.
# --------------------------------------------------------------------------- #

def build_core_knowledge() -> KnowledgeBook:
    kb = KnowledgeBook()
    kb.register(KnowledgeEntry(
        "read_only_invariant", "Governance",
        "The Trade Advisor is READ-ONLY with respect to the broker (ADR 0001). You may research, "
        "synthesize, rank, and explain ideas, but you must NEVER output an order, ticket, position "
        "size, lot/contract count to execute, or any instruction to trade.",
        ("invariant", "safety"),
    ))
    kb.register(KnowledgeEntry(
        "data_mode_ladder", "Honesty",
        "Every idea carries a data_mode showing how real its inputs are: live_chain (real quotes) > "
        "live_anchored (synthetic strikes off a live spot/IV) > synthetic / user_override (model-only) > "
        "cached / regime (derived context). Never present model-only data as live.",
        ("invariant", "honesty"),
    ))
    kb.register(KnowledgeEntry(
        "triage_labels", "Honesty",
        "Labels are the operator's triage, not auto-actions: PROCEED (passes all hard filters, top-ranked), "
        "MONITOR (viable but soft-gated, e.g. model-only or naked-risk), REJECT (fails a hard filter), "
        "INFO (context, nothing to do). Model-only and naked premium-selling never reach PROCEED.",
        ("honesty",),
    ))
    kb.register(KnowledgeEntry(
        "regime_quadrants", "Macro",
        "Growth×Inflation quadrants: Goldilocks (growth up, inflation down/flat) → tech/growth; "
        "Reflation (growth up, inflation up) → energy/financials/materials; Stagflation (growth down, "
        "inflation up) → energy/materials/defensives + commodities, short duration; Deflationary Slowdown "
        "(growth down, inflation down) → defensives + long duration. Risk overlay = stress/crisis on top.",
        ("macro", "definitions"),
    ))
    kb.register(KnowledgeEntry(
        "cockpit_modules", "Product",
        "The cockpit has four modules: Option Strategy (structures on the base book — zero-cost collar, "
        "carry shorts), FX Carry (SGD-hedge FX-futures allocation + a bounded carry tilt), Tactical Trade "
        "Ideas (independent short-term macro/market trades — this AI's home), Roll & Carry Calendar (option "
        "+ futures rolls, GSCI-like commodity schedules).",
        ("product",),
    ))
    return kb


__all__ = [
    "PromptSkill",
    "KnowledgeEntry",
    "SkillRegistry",
    "KnowledgeBook",
    "knowledge_system_block",
    "build_core_knowledge",
]
