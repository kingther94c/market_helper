# AGENTS.md

**Canonical** governance file for every AI agent (Claude Code, Codex, future
agents). `CLAUDE.md` is a thin redirect to this file. Operational knowledge
lives in `memory/hot/` — do not duplicate it here.

## Reading order (default)

1. `AGENTS.md` (this file) — rules + governance
2. `memory/hot/` — operations / architecture / gotchas
3. `DEV_DOCS/PLAN.md` — active initiatives + backlog
4. `DEV_DOCS/docs/devplans/` — track-level detail
5. Code

Do not scan the full repo by default. Do not read `DEV_DOCS/archive/` or
`memory/archive/` unless the task explicitly needs history.

## Memory model

- **Hot memory** (`memory/hot/`) — compact, high-signal, frequently-needed
  operational knowledge. Stays small.
- **Cold memory** (`DEV_DOCS/archive/`, `memory/archive/`) — historical
  context, superseded designs, retired plans. Both gitignored. Read on demand
  only.
- Each knowledge type has **one canonical home** — see the index in the
  reading-order list above. If a fact already exists canonically, update it;
  do not duplicate.

## Process rules

- **Conda `py313` (Python 3.13) for every run.** Never `conda base`.
- **Every commit AND every PR must update `DEV_DOCS/PLAN.md`** — not just
  PRs. A commit that lands meaningful behavior without a PLAN entry is a
  serious mistake; the next commit must add the missing entry. Update
  `DEV_DOCS/docs/devplans/` too when scope or architecture changes.
- Keep `DEV_DOCS/PLAN.md` brief. Past **300 lines** triggers a
  review-compact-archive pass before continuing other work: collapse
  landed-phase detail to one-liners with pointers into
  `DEV_DOCS/archive/landed/`, archive retired plans, refresh active sections.
- Clear notebook outputs before committing. `notebooks/dev_lab/` is scratch,
  out of version control.
- Audit every commit for **private-information leakage** before pushing.
- Reassess whether touched content under `DEV_DOCS/` and `memory/` is still
  relevant on every PR; delete stale material or update it instead of letting
  it drift.
- New runtime dependencies go into `env.yml` in the same change.
- Use **Feather** for maintained internal intermediate tables users are not
  expected to edit directly. Emit debug CSVs on demand only.
- Treat `configs/portfolio_monitor/local.env`, any
  `<MARKET_HELPER_GDRIVE_ROOT>/local.env`, and other local-secret files as
  gitignored local config only.
- Do not commit generated outputs under `data/artifacts/`. Keep reusable
  fixtures under `tests/` instead.
- Keep the project **read-only with respect to the broker** — no trading /
  order-entry code in V1.

## Memory maintenance loop

Run a memory maintenance pass after one of:
- every ~10 meaningful commits, or
- every ~2 weeks of active development, or
- major feature completion.

Tasks (a pass should usually *reduce* total docs size):

1. Compress verbose explanations in hot memory.
2. Remove duplicated knowledge across docs / plans / comments.
3. Archive superseded material; delete low-signal scratch.
4. Resync `DEV_DOCS/PLAN.md` and devplans so they don't contradict.
5. Re-check that each knowledge type still has one canonical home.

## Definition of success

Future agents onboard faster. Repository context is easier to understand.
Architectural ambiguity decreases. Retrieval precision improves. Future
AI-generated changes become safer. Project memory becomes denser and more
durable. Documentation entropy decreases.

Success is **not** measured by number of files, amount of documentation,
abstraction sophistication, or size of refactors.
