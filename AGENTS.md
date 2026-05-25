# AGENTS.md

**Canonical** governance file for every AI agent (Claude Code, Codex, future
agents). `CLAUDE.md` is a thin redirect to this file. Operational knowledge
lives in `memory/hot/` — do not duplicate it here.

## Reading order (default)

1. `AGENTS.md` (this file) — rules + governance
2. `memory/hot/` — operations / architecture / gotchas
3. `docs/architecture/` — system structure + track-level devplans
4. `plan/current.md` — active initiatives
5. `plan/backlog.md` — concise future work
6. Code

Do not scan the full repo by default. Do not read `memory/archive/` (or
the gitignored research output dumps) unless the task explicitly needs
history.

## Canonical homes (one per knowledge type)

| Knowledge type | Home |
|---|---|
| Agent rules + governance | `AGENTS.md` (this file) |
| Compact operational knowledge | `memory/hot/` |
| System structure + dependency rules | `docs/architecture/` |
| Track-level architecture detail | `docs/architecture/devplans/` |
| Major design tradeoffs (ADRs) | `docs/decisions/` |
| Reusable runbooks | `docs/operations/` |
| Current initiatives | `plan/current.md` |
| Concise future work | `plan/backlog.md` |
| Inactive historical material | `memory/archive/` (gitignored) |

If canonical knowledge already exists, **update it**; do not duplicate.
Hot memory must stay small — maintenance passes should *reduce* total docs
size, not grow it.

## Process rules

- **Conda `py313` (Python 3.13) for every run.** Never `conda base`.
- **Every commit AND every PR must update `plan/current.md`** — not just
  PRs. A commit that lands meaningful behavior without a plan entry is a
  serious mistake; the next commit must add the missing entry. Update
  `docs/architecture/devplans/` too when scope or architecture changes, and
  add a new ADR under `docs/decisions/` for major tradeoffs.
- Keep `plan/current.md` brief. Past ~150 lines triggers a
  review-compact-archive pass: collapse landed-phase detail to one-liners
  with pointers into `memory/archive/landed/`, retire stale items, refresh
  active sections.
- Clear notebook outputs before committing. `notebooks/dev_lab/` is scratch,
  out of version control.
- Audit every commit for **private-information leakage** before pushing.
- Reassess whether touched content under `docs/`, `plan/`, and `memory/` is
  still relevant on every PR; delete stale material or update it instead of
  letting it drift.
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

## Tests

The suite is the safety net for every refactor. Keep it green: failing
tests must not accumulate. If you discover a pre-existing failure while
working on something else, **fix or `@pytest.mark.skipif` it with a
written reason in the same change** — do not pretend you didn't see it.

### Required checks for common changes

| You did this | Then you must |
|---|---|
| Renamed / removed a public symbol (function, class, attribute, module-level constant) | `grep -r "old_name" tests/` — especially `monkeypatch.setattr(..., "old_name", ...)`, which silently fails to neutralize but raises `AttributeError` when the test runs. Then run the **full** suite, not just nearby tests. |
| Extended a canonical schema (`POSITION_REPORT_HEADERS`, an `*Inputs` dataclass, a `*ViewModel`, a JSON output shape) | Regenerate every fixture pinned to that schema. Prefer schema-derived assertions (`assert headers == POSITION_REPORT_HEADERS`) over hand-rolled golden files so the fixture can't silently drift. |
| Added a test that touches the host filesystem in a platform-specific way (NTFS-reserved chars, POSIX permissions, symlinks, fork semantics) | Add `@pytest.mark.skipif(sys.platform == "win32", reason="...")` (or the inverse) with a one-line reason. Do not rely on the test happening to pass on the developer's machine. |
| Added a test that needs an external resource (network, env var, registry, real GDrive mount, broker connection) | Neutralize it. The unit suite's `tests/unit/conftest.py` already isolates `MARKET_HELPER_GDRIVE_ROOT`, the Windows registry probe, and the OS-aware GDrive probe; extend that fixture rather than monkeypatching ad-hoc in each test. |

### Triage on every commit

Before pushing, scan the test run for:
- **New failures** — re-run any failing test you didn't recognize; do not assume "it was already broken".
- **Deprecation warnings** (especially Pandas, Python 3.14, library majors) — note them in `plan/backlog.md` if not in scope; fix when the production import is in the same diff.
- **Newly-skipped tests with no `reason=` argument** — every skip needs a written justification.

### Don't

- Don't delete a failing test to make the suite green. Fix it, skip it with a reason, or open a tracked task.
- Don't add `pytest.importorskip(...)` to mask an env problem you can fix.
- Don't use `pytest.skip()` inside the test body without an explicit reason argument.
- Don't `monkeypatch.setattr(module, "name", ...)` defensively when the conftest already provides hermetic isolation — dead monkeypatches are how refactor drift hides.

## Memory maintenance loop

Run a memory maintenance pass after one of:
- every ~10 meaningful commits, or
- every ~2 weeks of active development, or
- major feature completion.

Tasks (a pass should usually *reduce* total docs size):

1. Compress verbose explanations in hot memory.
2. Remove duplicated knowledge across docs / plans / comments.
3. Archive superseded material; delete low-signal scratch.
4. Resync `plan/current.md`, `plan/backlog.md`, and
   `docs/architecture/devplans/` so they don't contradict.
5. Re-check that each knowledge type still has one canonical home.

## Definition of success

Future agents onboard faster. Repository context is easier to understand.
Architectural ambiguity decreases. Retrieval precision improves. Future
AI-generated changes become safer. Project memory becomes denser and more
durable. Documentation entropy decreases.

Success is **not** measured by number of files, amount of documentation,
abstraction sophistication, or size of refactors.
