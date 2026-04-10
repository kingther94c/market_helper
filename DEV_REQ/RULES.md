# RULES

- Start each development task by reviewing `DEV_REQ/RULES.md` and `DEV_REQ/PLAN.md`.
- Every PR must update `DEV_REQ/PLAN.md` to reflect completed work, current status, and next steps.
- Update the relevant file under `docs/devplans/` whenever scope, architecture, status, or follow-up work changed.
- Keep the project read-only for broker integrations in this phase. Do not add trading or order-entry behavior.
- Treat `configs/portfolio_monitor/local.env` and other local-secret files as gitignored local config only.
- Do not commit generated outputs under `data/artifacts/`; keep reusable fixtures under `tests/` instead.
