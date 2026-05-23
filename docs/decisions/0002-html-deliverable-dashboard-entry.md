# ADR 0002: HTML is the deliverable; dashboard is the interactive entry

**Status**: Accepted. Confirms a route choice made during 2026 portfolio
monitor work after rejecting a snapshot/Playwright pipeline rewire.

## Context

The portfolio monitor produces a static HTML report (`combined-html-report`)
and a live NiceGUI dashboard. There were two candidate routes for unifying
the two:

1. Treat the dashboard as the canonical view and snapshot it (via Playwright)
   to produce the HTML report.
2. Keep the static HTML renderer (`market_helper/reporting/`) as the
   canonical render path; embed the rendered HTML in the dashboard via
   iframe.

## Decision

Route (2). The static HTML renderer is the canonical render path. The
dashboard is the **interactive entry** that embeds the rendered HTML.

CLI / workflows / dashboard already share one input-contract layer at
`market_helper/application/portfolio_monitor/contracts.py` (9 `*Inputs`
dataclasses including `BenchmarkRefreshInputs`). No separate snapshot
pipeline or ViewModel rewire is planned.

## Consequences

- Report renderers stay in `market_helper/reporting/`.
- No Playwright runtime dependency.
- The dashboard's iframe is the integration point; new report sections land
  in the renderer first.
- The portfolio-monitor near-term backlog drops "snapshot performance
  parity", "combined report snapshot path", and "legacy renderer cleanup"
  (these are retired by decision, not deferred). See
  `docs/architecture/devplans/portfolio_monitor.md` under "Do Not Reopen
  Without a New Requirement".
