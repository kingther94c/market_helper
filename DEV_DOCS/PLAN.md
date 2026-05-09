# PLAN

> Process gates live in `DEV_DOCS/RULES.md`. Historical detail lives in
> `DEV_DOCS/archive/` (gitignored, do not read by default).

## Objective

Build a broker-agnostic, **read-only** market monitoring stack around IBKR data:
live positions, Flex performance, portfolio risk, regime engine context,
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

### Regime Engine

Goal: keep regime as market context: growth and inflation axes plus independent
risk/stress overlay. The legacy 7-regime rulebook has been removed; the engine
is the only path.

Landed:
- Engine coordinator, CLI (`regime-detect`, `regime-calibrate`), HTML report.
- GUI actions for cached run and input-refresh run.
- Combined report includes regime context when the artifact exists.
- **Concept-level macro aggregation** (`growth_concepts:` and
  `inflation_concepts:` blocks in `fred_series.yml`). Series → concept (with
  within-concept weights compensating for redundancy) → axis (with concept
  weight expressing semantic importance). No more raw per-series voting on
  the macro side.
- **Symmetric tanh compression** on macro and market layers so both occupy the
  same (-1, 1) latent space — weights now express semantic importance, not
  magnitude compensation.
- **Label-level hysteresis** on axis-state transitions
  (`regime_thresholds.min_consecutive_days` in `regime_engine.yml`); cut
  median regime run length from 3 bdays to 18.
- Per-series normalization options: none/centered/threshold/zscore/minmax/
  percentile, with per-spec window/clip overrides and post-normalization
  smooth bound (`compression: tanh`).
- New macro and market signals shipped dormant (declared but absent from any
  concept block, or `weight: 0.0` for market signals): curve / breakeven /
  DXY / ISM proxy / housing / consumer sentiment / growth-vs-value / extra
  sector pairs. Flip a series into a concept (or set weight > 0) to activate.

Near-term work:
1. Mirror the concept-aggregation pass for the market layer
   (`market_regime.yml` is still flat per-signal; group VIX/MOVE/realized-vol
   into a `risk_volatility` concept, HYG/LQD into `credit_appetite`, sector
   relatives into `cyclical_rotation`, etc.).
2. Sync the dormant FRED series so they can be activated via config flip.
3. Add a small backtest sanity harness with pinned fixture snapshots for
   anchor periods.
4. Keep ML layers as unavailable/zero-weight until model artifacts and feature
   schemas are explicit.

Calibration session record:
`notebooks/regime_detection/regime_v2_calibration_index.ipynb` (TOC) +
per-round notebooks (Q1+Q2 macro scale fix and concept aggregation; Q3
market tanh, lower thresholds, label hysteresis).

Detail: `DEV_DOCS/docs/devplans/regime_engine_devplan.md`.

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
landed, superseded by regime engine, or too speculative for near-term work:

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
- Risk/stress is not a macro axis in regime engine.

## Testing

Default unit command:

```bash
PYTHONPATH=. PYTHONPYCACHEPREFIX=/tmp/pycache pytest -q tests/unit
```

Integration risk is concentrated in provider variability, snapshot rendering
parity, and artifact/config drift across CLI, scripts, and GUI forms.
