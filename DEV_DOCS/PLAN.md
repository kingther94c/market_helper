# PLAN

> Process gates live in `DEV_DOCS/RULES.md`. Historical detail lives in
> `DEV_DOCS/archive/` (gitignored, do not read by default).

## Objective

Build a broker-agnostic, **read-only** market monitoring stack around IBKR data:
live positions, Flex performance, portfolio risk, Regime Engine v2 context,
static HTML reports, and the NiceGUI dashboard.

## Boundaries

**In scope**
- Read-only provider adapters: IBKR Client Portal, TWS / IB Gateway via
  `ib_async`, Flex Web Service, Yahoo/FRED/FMP data pulls.
- Artifact-driven portfolio monitor: position CSV, NAV/cashflow history,
  security reference cache, risk/performance/regime reports.
- NiceGUI dashboard as the operator surface.

**Out of scope**
- Order placement, cancel, modify, brokerage write actions.
- Trading signal generation or allocation execution from regime output.
- Multi-user SaaS frontend work.
- Rebuilding old workbook reports before the artifact/reporting model is stable.

## Architecture

Current ownership:

`cli -> workflows -> application -> domain -> data_sources / reporting / presentation`

Important seams:
- `market_helper/application/portfolio_monitor/` owns dashboard-triggered
  orchestration, artifact resolution, progress events, and action contracts.
- `market_helper/domain/portfolio_monitor/services/` owns reusable risk,
  performance, benchmark, volatility, fixed-income, and Yahoo-cache logic.
- `market_helper/presentation/dashboard/` owns live NiceGUI interaction.
- `market_helper/reporting/` owns static HTML fragments until the snapshot
  pipeline fully replaces legacy renderers.
- `configs/security_universe.csv` is the manually maintained instrument source
  of truth; `data/artifacts/portfolio_monitor/security_reference.csv` is a
  generated lookup cache.
- `nav_cashflow_history.feather` is the canonical daily NAV + cashflow store.

## Active Tracks

### Portfolio Monitor

Goal: keep the GUI/report workflow reliable while shrinking old rendering paths.

Near-term work:
1. Finish dashboard Performance USD/SGD parity for the snapshot path.
2. Rewire `combined-html-report` to the NiceGUI/Playwright snapshot pipeline.
3. Delete or shrink obsolete legacy HTML renderers after combined snapshot parity.
4. Formalize an artifact/config contract shared by CLI, workflows, dashboard
   forms, and snapshot overrides.
5. Add focused performance-data warnings for missing/unsafe metrics.

Keep for later, not active:
- Covariance-consistent marginal/component risk attribution.
- Richer derivatives normalization for options, inverse products, and unusual
  futures exposure.
- Broader country/sector/FI-tenor look-through coverage.
- Manual override layer for provisional account-specific universe entries.

Detail: `DEV_DOCS/docs/devplans/portfolio_monitor_devplan.md`.

### Regime Engine v2

Goal: keep regime as market context: growth and inflation axes plus independent
risk/stress overlay.

Landed:
- V2 contracts, engine coordinator, CLI/report paths, calibration workflow.
- GUI actions for cached run and input-refresh run.
- Combined report includes Regime Engine v2 when the artifact exists.

Near-term work:
1. Calibration decision pass: review the HTML report and notebook questions,
   then decide config changes before writing more code.
2. Apply a narrow config tuning pass if calibration decisions are clear.
3. Add a small backtest sanity harness with pinned fixture snapshots for anchor
   periods.
4. Keep ML layers as unavailable/zero-weight until model artifacts and feature
   schemas are explicit.

Detail: `DEV_DOCS/docs/devplans/regime_engine_v2_devplan.md`.

## Backlog

- Live TWS ergonomics: account/session metadata, account selection, broader
  contract fixtures.
- Flex ergonomics: historical backfill validation, archive metadata, stale XML
  diagnostics.
- Cached benchmark/proxy loaders beyond SPY, such as AGG and 60/40 benchmark
  support.
- Lightweight portfolio/regime integration scenarios only after portfolio and
  regime contracts stop moving.
- Workbook-style target report generation after risk/report semantics are stable.

## Archived Active Plans

The following files were retired from active planning because they were either
landed, superseded by Regime Engine v2, or too speculative for near-term work:

- `regime_detection_devplan.md` -> `DEV_DOCS/archive/devplans/regime_detection_devplan_retired.md`
- `ui_redesign_devplan.md` -> `DEV_DOCS/archive/devplans/ui_redesign_devplan_retired.md`
- `integration_devplan.md` -> `DEV_DOCS/archive/devplans/integration_devplan_retired.md`

## Domain Gotchas

- The app is read-only. Do not add brokerage write actions.
- FI tenor bucketing is explicit mapping (`ZT -> 1-3Y`, `ZN -> 7-10Y`), not
  derived from duration.
- Flex XML cashflow attribution uses `reportDate`, not `settleDate`.
- Portfolio AUM denominator excludes futures/options; it is stock-like + cash.
- FI proxy-vol maps yield-vol through modified duration; do not treat MOVE as
  direct bond price volatility.
- `fx_usdsgd_eod` is SGD per 1 USD.
- Yahoo return cache stores log returns; use `expm1` when compounding simple
  chart returns.
- Risk/stress is not a macro axis in Regime Engine v2.

## Testing

Default unit command:

```bash
PYTHONPATH=. PYTHONPYCACHEPREFIX=/tmp/pycache pytest -q tests/unit
```

Integration risk is concentrated in provider variability, snapshot rendering
parity, and artifact/config drift across CLI, scripts, and GUI forms.
