"""The single, discoverable place that lists what the advisor AI can do.

`build_advisor_ai_capabilities()` assembles, from the generic core + every domain
contributor, the three things the AI has:

- **tools** — read-only local functions it can call (name + schema + description),
- **skills** — the injected prompts per task (the harness-selected production prompt
  + alternatives),
- **knowledge** — reference facts it is grounded on (invariants, honesty ladder,
  regime quadrants, module map).

`as_dict()` / `describe()` render the manifest for docs, a UI panel, or a CLI
dump. **To extend:** a domain registers tools/skills/knowledge in its own
``ai_tools`` module and is wired in below — nothing else changes.
"""

from __future__ import annotations

from dataclasses import dataclass

from .skills import KnowledgeBook, SkillRegistry, build_core_knowledge
from .tools import AiToolRegistry


@dataclass(frozen=True)
class AdvisorAiCapabilities:
    tools: AiToolRegistry
    skills: SkillRegistry
    knowledge: KnowledgeBook

    def as_dict(self) -> dict:
        return {
            "tools": [
                {"name": t.name, "description": t.description,
                 "parameters": sorted((t.parameters.get("properties") or {}).keys()), "read_only": t.read_only}
                for t in self.tools.all()
            ],
            "skills": [
                {"name": s.name, "task": s.task, "when_to_use": s.when_to_use} for s in self.skills.all()
            ],
            "knowledge": [
                {"name": e.name, "topic": e.topic, "tags": list(e.tags)} for e in self.knowledge.all()
            ],
        }

    def describe(self) -> str:
        lines = ["# Advisor AI capabilities", "", f"## Tools ({len(self.tools)})  — read-only functions the AI can call"]
        for t in self.tools.all():
            args = ", ".join((t.parameters.get("properties") or {}).keys())
            lines.append(f"- {t.name}({args}): {t.description}")
        lines += ["", f"## Skills ({len(self.skills)})  — injected prompts per task"]
        for s in self.skills.all():
            lines.append(f"- [{s.task}] {s.name}: {s.when_to_use}")
        lines += ["", f"## Knowledge ({len(self.knowledge)})  — facts the AI is grounded on"]
        for e in self.knowledge.all():
            lines.append(f"- ({e.topic}) {e.name}: {', '.join(e.tags)}")
        return "\n".join(lines)


def build_advisor_ai_capabilities() -> AdvisorAiCapabilities:
    """Assemble the full capability set: generic core + each domain's contributions."""
    tools = AiToolRegistry()
    skills = SkillRegistry()
    knowledge = build_core_knowledge()

    # Domain contributors (lazy import so trade_advisor.ai stays free of domain deps).
    try:
        from market_helper.domain.tactical_ideas.ai_tools import (
            build_tactical_tool_registry,
            tactical_knowledge,
            tactical_skills,
        )

        for tool in build_tactical_tool_registry().all():
            tools.register(tool)
        for skill in tactical_skills():
            skills.register(skill)
        for entry in tactical_knowledge():
            knowledge.register(entry)
    except Exception:  # noqa: BLE001 — a missing/broken domain contributor must not break the manifest
        pass

    return AdvisorAiCapabilities(tools=tools, skills=skills, knowledge=knowledge)
