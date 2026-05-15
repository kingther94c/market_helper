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

Landed:
- Combined report restructured: KPI strip slimmed to NAV USD/SGD, MTD/YTD
  return (SGD), Target Vol (Fast), and a regime summary cell; Regime Snapshot
  removed from the Risk tab (the dedicated Regime section is canonical); Risk
  Assumptions merged into the Portfolio Vol Matrix card.
- Performance Overview (USD + SGD) now shows Total Return MTD/YTD/1Y plus 1Y
  Excess Return, Vol, and Sharpe — all excess-over-BIL-cash, with Vol and Sharpe
  sharing the same daily excess-return series. Missing BIL observations inside a
  window are treated as a 0% daily cash return rather than dropped.
- Performance section adds a Benchmark Comparison table (MTD/YTD/1Y) — portfolio
  TWR/MWR vs Cash (BIL) and SPY, in returns and $ PnL.
- **FX history coverage fix**: `DEFAULT_YAHOO_FX_PERIOD` was `2y`, so
  `_lookup_fx_rate` froze USD/SGD constant for all NAV dates older than ~2 years
  and collapsed SGD returns onto USD returns for the bulk of history. Now `max`.
  Requires a `nav_cashflow_history.feather` rebuild to take effect.

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
- **Concept-level aggregation on both layers** — macro
  (`growth_concepts:` / `inflation_concepts:` in `fred_series.yml`) and market
  (`growth_concepts:` / `inflation_concepts:` / `risk_concepts:` in
  `market_regime.yml`). Signals → concept (within-concept weights compensate
  for redundancy) → axis (concept weight expresses semantic importance).
- **Symmetric tanh compression** on macro and market layers so both occupy the
  same (-1, 1) latent space — weights now express semantic importance, not
  magnitude compensation.
- **Beta-adjusted relative returns** for equity-style and sector-rotation
  market signals (`r_num - β·r_den`, β = 60-day EWMA rolling regression slope,
  clipped ±3). Strips out market-beta exposure so signals measure genuine
  regime preference rather than volatility ride.
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
1. ~~Dashboard: surface per-concept contributions, internal disagreement,
   and confidence degradation~~ — landed in Q5. The standalone regime HTML
   report now shows the per-layer concept table, per-axis macro-vs-market
   disagreement breakdown, and a confidence-reasoning blurb. Engine emits
   `concept_weights` alongside `concept_scores` in `layer_outputs.diagnostics`
   and `confidence_strength` / `confidence_thresholds` /
   `disagreement_penalty_active` on `FinalRegimeResult`.
2. Propagate the same concept panel into the combined portfolio report (the
   regime ribbon there still shows only the summary card).
3. Sync the dormant FRED series so they can be activated via config flip.
4. Add a small backtest sanity harness with pinned fixture snapshots for
   anchor periods.
5. Keep ML layers as unavailable/zero-weight until model artifacts and feature
   schemas are explicit.

Calibration session record:
`notebooks/regime_detection/regime_v2_calibration_index.ipynb` (TOC) +
per-round notebooks: Q1+Q2 (macro scale fix and concept aggregation), Q3
(market tanh, lower thresholds, label hysteresis), Q4 (market concept
aggregation, beta-adjusted returns, S&P GSCI), Q5 (calibration workflow
macro-config fix; rebuilt the post-Q4 baseline before the next tuning pass),
Q6 (market-heavier blend and narrower deadband to improve recovery-window
responsiveness).

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
