# memory/hot/

Compact, high-signal operational knowledge agents read first.

| File | Use when |
|---|---|
| [operations.md](operations.md) | running tests, dashboard, CLI, env setup |
| [architecture.md](architecture.md) | finding code, layer ownership, data flows |
| [gotchas.md](gotchas.md) | non-obvious project rules before touching code |

Reading order (per `AGENTS.md`):

1. `AGENTS.md` — agent rules and governance
2. `memory/hot/` — this folder
3. `docs/architecture/`, `docs/decisions/`, `docs/operations/` — deeper
   architecture / ADRs / runbooks
4. `plan/current.md` — active initiatives
5. `plan/backlog.md` — concise future work
6. Code

Cold material lives under `memory/archive/` (gitignored). Not read by default.
