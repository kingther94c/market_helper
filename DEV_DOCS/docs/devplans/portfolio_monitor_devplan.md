# Portfolio Monitor Devplan

## Current Focus

The portfolio monitor is the primary operator surface. Keep it artifact-driven,
read-only, and reliable before adding new analytics breadth.

Current ownership rules:
- `market_helper/application/portfolio_monitor/` owns GUI-triggered actions,
  artifact path resolution, progress events, and output contracts.
- `market_helper/domain/portfolio_monitor/services/` owns reusable analytics:
  NAV/cashflow history, performance windows, risk math, Yahoo return cache,
  SPY benchmark attachment, fixed-income vol, and proxy logic.
- `market_helper/presentation/dashboard/` owns the live NiceGUI UI.
- Static report rendering remains in `market_helper/reporting/` until the
  snapshot pipeline fully replaces legacy HTML renderers.

Canonical artifacts/config:
- `configs/security_universe.csv`: manually maintained semantic universe.
- `data/artifacts/portfolio_monitor/security_reference.csv`: generated lookup
  cache.
- `data/artifacts/portfolio_monitor/flex/nav_cashflow_history.feather`: daily
  NAV/cashflow store.
- `configs/portfolio_monitor/report_config.yaml`: tracked risk/report runtime
  config.
- `configs/portfolio_monitor/local.env`: gitignored account/provider secrets.
- `configs/portfolio_monitor/us_sector_lookthrough.json`: tracked ETF sector
  look-through cache.

## Near-Term Next Steps

1. **Snapshot performance parity**
   Add the missing cumulative/drawdown Plotly views and benchmark traces to the
   NiceGUI Performance USD/SGD tabs so they match the static performance HTML.

2. **Combined report snapshot path**
   Rewire `combined-html-report` to use the same NiceGUI/Playwright snapshot
   pipeline that already backs `risk-html-report`.

3. **Legacy renderer cleanup**
   After combined snapshot parity, delete or shrink the obsolete HTML rendering
   branches and migrate brittle HTML-string tests toward view-model assertions.

4. **Artifact/config contract**
   Replace loosely coupled path strings across CLI/workflows/dashboard snapshot
   overrides with a small shared contract. Keep this narrow: paths, vol method,
   correlation assumption, regime artifact, output HTML.

5. **Performance diagnostics**
   Add explicit warnings/logging for missing or unsafe performance metrics
   instead of silent `n/a`, especially per-currency metric failures and
   incomplete NAV/cashflow histories.

## Deferred

These are useful but not next:
- Covariance-consistent marginal/component risk attribution.
- Options and unusual derivative exposure normalization.
- Manual override layer for account-specific provisional universe entries.
- Broader country/sector/FI-tenor look-through coverage.
- More real IBKR payload fixtures and contract edge cases.

## Do Not Reopen Without a New Requirement

- `performance_history.feather`; `nav_cashflow_history.feather` replaced it.
- Workbook-derived runtime mapping tables; universe/reference artifacts replaced
  them.
- Risk report as a standalone primary surface; combined report/dashboard are the
  product surfaces.
