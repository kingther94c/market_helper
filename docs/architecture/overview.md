# Architecture overview

Canonical system structure for `market_helper`. Compact retrieval-oriented
notes live in [`memory/hot/architecture.md`](../../memory/hot/architecture.md);
this file is the deeper reference.

## Objective

Build a broker-agnostic, **read-only** market monitoring stack around IBKR
data: live positions, Flex performance, portfolio risk, regime engine
context, static HTML reports, and the NiceGUI dashboard.

## Boundaries

**In scope**
- Read-only provider adapters: IBKR Client Portal, TWS / IB Gateway via
  `ib_async`, Flex Web Service, Yahoo/FRED/FMP data pulls.
- Artifact-driven portfolio monitor: position CSV, NAV/cashflow history,
  security reference cache, risk/performance/regime reports.
- NiceGUI dashboard as the operator surface.

**Out of scope**
- Order placement, cancel, modify, brokerage write actions (see ADR 0001).
- Trading signal generation or allocation execution from regime output.
- Multi-user SaaS frontend work.
- Rebuilding old workbook reports before the artifact/reporting model is stable.

## Current shape

The repo is no longer just a provider-and-report script collection. The active
portfolio-monitor stack now has five practical layers:

1. `market_helper/cli/`
   - Stable user-facing commands and script entrypoints.
   - Keeps command names stable while implementation moves underneath.
2. `market_helper/workflows/`
   - Backward-compatible facade layer used by the CLI, tests, notebooks, and
     older imports.
   - Delegates into the newer pipeline and service modules.
3. `market_helper/application/`
   - Application-service layer for UI/action orchestration.
   - Owns artifact-path resolution, progress bridging, and dashboard-facing
     action/query contracts.
4. `market_helper/domain/`
   - Business pipelines and reusable analytics logic.
   - Portfolio monitor, regime detection, and integration workflows live here.
5. `market_helper/data_sources/` and `market_helper/presentation/`
   - Provider adapters at the boundary.
   - Rendering/export/UI modules at the output edge.

This means the current architecture is best read as:

`CLI -> workflows (compatibility) -> application/domain -> data_sources + presentation`

## Portfolio Monitor Ownership

### Stable public surface

- `market_helper/cli/main.py`
- `market_helper/workflows/generate_report.py`
- `scripts/run_report.sh`
- `scripts/launch_ui.sh`

These are the compatibility-first entrypoints. They should remain stable even if
internal ownership moves again.

### Application layer

`market_helper/application/portfolio_monitor/`

- `PortfolioMonitorQueryService`
  - Resolves artifact inputs.
  - Builds the current dashboard snapshot from risk + performance artifacts.
  - Owns lightweight in-process caching for repeated dashboard refreshes.
- `PortfolioMonitorActionService`
  - Bridges UI actions into workflow calls.
  - Normalizes progress reporting and output-path handling for live refresh,
    Flex refresh, combined report generation, and ETF sync actions.

This layer is the right place for dashboard orchestration logic. It should keep
filesystem/path concerns out of page components as much as possible.

### Domain layer

`market_helper/domain/portfolio_monitor/`

- `pipelines/generate_portfolio_report.py`
  - Main portfolio-monitor execution flows.
  - Position report generation, live TWS pulls, Flex processing, report export,
    snapshot capture entrypoints.
- `services/`
  - Risk analytics, volatility/proxy helpers, security-reference logic,
    performance analytics, NAV/cashflow history rebuilding, ETF lookthrough.

This layer should stay renderer-agnostic and UI-agnostic wherever possible.

### Presentation layer

- `market_helper/presentation/dashboard/`
  - NiceGUI app + a thin shared **shell** (`shell.py`: chrome, cross-surface
    nav, `/` landing page) wrapping **two parallel surfaces** — `portfolio_monitor`
    (`/portfolio`) and `trade_advisor` (`/advisor`). The shell is a fixed pair,
    not a registry: research / backtest / screener surfaces are out of scope for
    this repo (see ADR 0008). Each surface is a `pages/<line>/` subpackage split
    by responsibility — `state`/`routes`/`actions`/`views`/`drawer`/`page` for
    portfolio_monitor, `inputs`/`cards`/`rule_based`/`ai`/`page` for trade_advisor
    (see ADR 0009); shared `components/` live alongside.
- `market_helper/presentation/exporters/`
  - CSV/security-reference export helpers.
- `market_helper/reporting/`
  - Shared risk/performance view-model builders and remaining legacy HTML glue.

**Rendering ownership** (see ADR 0002): the static HTML renderer in
`market_helper/reporting/` is the canonical render path. The dashboard
embeds that HTML in an iframe — there is no separate snapshot/Playwright
pipeline planned. New report sections land in the renderer first.

## Provider boundaries

### IBKR / TWS / Flex

- `market_helper/data_sources/ibkr/tws/`
  - Live TWS / IB Gateway client and normalization helpers.
- `market_helper/data_sources/ibkr/flex/`
  - Flex XML parsing and performance extraction.
- `market_helper/providers/flex/`
  - Flex Web Service polling/client behavior still used by the pipeline layer.

### Other providers

- `market_helper/data_sources/yahoo_finance.py`
- `market_helper/data_sources/fmp.py`

These remain boundary adapters and should not accumulate portfolio business
rules.

## Key architectural strengths

- Clear read-only boundary for broker integration work.
- Strong compatibility strategy while refactoring internals.
- Artifact-driven workflows make the dashboard, CLI, and tests composable.
- A real application layer now exists for UI orchestration instead of pushing
  everything into page code.

## Current architectural debt

- Legacy `workflows` shims remain broad, which keeps migration safe but
  leaves duplicate facade paths.
- Artifact/config handling shares one contract layer
  (`application/portfolio_monitor/contracts.py`) but still passes path
  strings through legacy entrypoints.

## Direction

Tightening focus:

1. Keep business logic in `domain/` and orchestration in `application/`.
   Avoid drift back into page components or provider code.
2. Shrink legacy `workflows` compatibility surfaces only as concrete asks
   land — no speculative cleanup (the snapshot/Playwright rewire that
   motivated earlier cleanup is retired; see ADR 0002).
3. Treat `application/portfolio_monitor/contracts.py` as the canonical
   input contract for CLI / workflow / dashboard call-sites; new entry
   points should reuse the existing `*Inputs` dataclasses.
