# RULES

- Start each development task by reviewing `DEV_DOCS/RULES.md` and `DEV_DOCS/PLAN.md`.
- Every PR must update `DEV_DOCS/PLAN.md` to reflect completed work, current status, and next steps.
- Update the relevant file under `DEV_DOCS/docs/devplans/` whenever scope, architecture, status, or follow-up work changed.
- Any newly required package must be added to `env.yml` in the same change.
- Clear notebook outputs before every commit.
- Check every commit for private-information leakage before pushing.
- Reassess whether touched content under `DEV_DOCS/` is still relevant on every PR; delete stale material or update it instead of leaving it to drift.
- Keep the project read-only for broker integrations in this phase. Do not add trading or order-entry behavior.
- Treat `configs/portfolio_monitor/local.env` and other local-secret files as gitignored local config only.
- Do not commit generated outputs under `data/artifacts/`; keep reusable fixtures under `tests/` instead.
