# ADR 0003: Layered memory + canonical knowledge homes

**Status**: Accepted.

## Context

This repository is an AI-native research and engineering workspace. Multiple
agents (Claude Code, Codex, future agents) operate on it. Without a strict
canonical layout, each agent rediscovers and re-summarizes the same facts,
documentation drifts, and onboarding cost grows with file count rather than
with project complexity.

Before this ADR, agent guidance was duplicated across `CLAUDE.md` (~101
lines) and `AGENTS.md` (~94 lines, 90%+ identical), and process rules were
split between `DEV_DOCS/RULES.md` and the per-agent guidance files. Plan
and architectural docs lived under `DEV_DOCS/`.

## Decision

Adopt a layered memory model with **one canonical home per knowledge type**:

| Knowledge type | Canonical home |
|---|---|
| Agent rules + governance | `AGENTS.md` |
| Compact operational knowledge | `memory/hot/` |
| System structure + dependency rules | `docs/architecture/` |
| Track-level architecture detail | `docs/architecture/devplans/` |
| Major design tradeoffs (this ADR + future) | `docs/decisions/` |
| Reusable runbooks | `docs/operations/` |
| Current initiatives | `plan/current.md` |
| Concise future work | `plan/backlog.md` |
| Inactive historical material | `memory/archive/` (gitignored) |

Default reading order for agents: `AGENTS.md` → `memory/hot/` → relevant
`docs/architecture/` → current plan → code. Archives are not read by
default.

`CLAUDE.md` becomes a thin redirect to `AGENTS.md`.

## Consequences

- Each knowledge fact has exactly one home. If a canonical fact already
  exists, agents **update** it instead of duplicating.
- Hot memory stays small. Maintenance passes (every ~10 meaningful commits
  or ~2 weeks) should **reduce** total docs size, not grow it.
- Cold memory (`*/archive/`) is gitignored — local-only context for
  agents that explicitly need history. Material that is not historically
  useful is **deleted**, not archived.
- Existing track-level devplans move under `docs/architecture/devplans/`
  rather than spawning a new top-level folder. They describe how a track
  works (architecture); short-horizon active work moves to `plan/current.md`.
- `DEV_DOCS/PLAN.md`, `DEV_DOCS/RULES.md`, and the rest of `DEV_DOCS/` are
  retired; their content redistributes into `plan/`, `AGENTS.md`,
  `docs/{architecture,decisions,operations}/`, and (for history) the
  gitignored `memory/archive/`.
