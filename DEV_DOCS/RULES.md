# RULES

- Start each development task by reviewing `DEV_DOCS/RULES.md` and `DEV_DOCS/PLAN.md`.
- **Do not read `DEV_DOCS/archive/` by default** — it holds historical context (long completed-work logs, retired plans, landed-phase detail) that wastes tokens for normal work. Only open it when the user explicitly asks for history, or when a current task genuinely needs to verify what shipped previously.
- **Keep `DEV_DOCS/PLAN.md` brief.** Whenever it grows past **300 lines**, do a review-compact-archive-update pass before continuing other work: move stale completed items / retired plans into a file under `DEV_DOCS/archive/`, collapse landed-phase detail down to one-line summaries with a pointer to the archive, and refresh the active sections so they only describe in-progress work and near-term next steps.
- All development, testing, scripts, notebooks, and local runs must use the conda `py313` environment (`Python 3.13`).
- Do not run project code from `conda base` or any other Python environment unless the rule is explicitly updated.
- Every PR must update `DEV_DOCS/PLAN.md` to reflect completed work, current status, and next steps.
- Update the relevant file under `DEV_DOCS/docs/devplans/` whenever scope, architecture, status, or follow-up work changed.
- Any newly required package must be added to `env.yml` in the same change.
- Use `Feather` as the canonical store for maintained internal intermediate tables that users are not expected to edit directly; only emit debug CSVs on demand.
- Clear notebook outputs before every commit.
- Check every commit for private-information leakage before pushing.
- Reassess whether touched content under `DEV_DOCS/` is still relevant on every PR; delete stale material or update it instead of leaving it to drift.
- Keep the project read-only for broker integrations in this phase. Do not add trading or order-entry behavior.
- Treat `configs/portfolio_monitor/local.env` and other local-secret files as gitignored local config only.
- Do not commit generated outputs under `data/artifacts/`; keep reusable fixtures under `tests/` instead.
