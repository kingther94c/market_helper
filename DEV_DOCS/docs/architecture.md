# Architecture

Current package layout and ownership for `market_helper`.

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
  - NiceGUI app, pages, components, snapshot capture pipeline.
- `market_helper/presentation/exporters/`
  - CSV/security-reference export helpers.
- `market_helper/reporting/`
  - Shared risk/performance view-model builders and remaining legacy HTML glue.

Important current reality: the repo still has two rendering paths in play.

1. The NiceGUI dashboard plus Playwright snapshot path.
2. Remaining legacy HTML builder code under `reporting/`.

The project direction is clearly toward the dashboard-driven snapshot path, but
the legacy HTML helpers still exist for compatibility and parity gaps.

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

- Documentation still understates the application layer and snapshot pipeline.
- Legacy workflow/reporting shims remain broad, which keeps migration safe but
  leaves duplicate execution paths in the codebase.
- Artifact/config handling is still path-string heavy across CLI, workflows, and
  dashboard forms.
- Rendering ownership is split between dashboard snapshot code and older HTML
  builders, which increases parity and maintenance costs.

## Direction

The next architecture tightening should focus on:

1. Making the dashboard snapshot path the single report-rendering path.
2. Shrinking legacy `workflows`/HTML compatibility surfaces once parity is
   proven.
3. Replacing ad hoc path-string plumbing with explicit artifact/config
   contracts.
4. Keeping business logic in `domain/` and orchestration in `application/`,
   rather than letting either drift back into page components or provider code.
