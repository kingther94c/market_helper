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
3. `DEV_DOCS/docs/` — deeper architecture / decisions / operations
4. `DEV_DOCS/PLAN.md` — active initiatives + backlog
5. Code

Cold material lives under `DEV_DOCS/archive/` (gitignored) and
`memory/archive/`. Not read by default.
