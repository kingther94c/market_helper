# Backlog

Concise future-work items. One line each; expand into
[`current.md`](current.md) when work starts.

## Portfolio Monitor

- **Performance diagnostics — unsafe-metric slice**. Symmetric follow-on to
  the missing-history actionable warning that landed. Per-currency metric
  failures + partial NAV/cashflow series → structured warnings, with
  remediation buttons where one action can fix it.
- **Cached benchmark / proxy loaders beyond SPY**. AGG, 60/40, etc. —
  generalizes the Yahoo-cache pattern exercised by the new "Refresh
  Benchmark Cache" action.
- **Live TWS ergonomics**. Account/session metadata, account selection,
  broader contract fixtures.
- **Flex ergonomics**. Historical backfill validation, archive metadata,
  stale XML diagnostics.
- **Commodity spread risk treatment**. Config-driven CM multi-leg spread
  synthesis for NG first: collapse same-account/root/exchange futures legs
  into one risk row; EWMA-weighted Huber regression for front-contract beta;
  seven-day cache for beta/spread analytics.

## Cross-domain

- Lightweight portfolio/regime integration scenarios — only after portfolio
  and regime contracts stop moving.
- Workbook-style target report generation — after risk/report semantics
  stabilize.

## Keep for later, not active

These are useful but explicitly **not** on deck:
- Covariance-consistent marginal/component risk attribution.
- Richer derivatives normalization for options, inverse products, and
  unusual futures exposure.
- Broader country/sector/FI-tenor look-through coverage.
- Manual override layer for provisional account-specific universe entries.
- More real IBKR payload fixtures and contract edge cases.
- Random forest / gradient boosting training workflows.
- Allocation tilt suggestions / trading signals / portfolio optimization
  driven by regime — **execution** stays out of V1 scope (ADR 0001). The
  *advisory* carve-out (ranked option *ideas*, no orders) is now a designed
  track: see [ADR 0007](../docs/decisions/0007-option-advisor-advisory-scope.md)
  + [`option_advisor.md`](../docs/architecture/devplans/option_advisor.md).

## Do not reopen without a new requirement

- `performance_history.feather` — `nav_cashflow_history.feather` replaced it.
- Workbook-derived runtime mapping tables — universe/reference artifacts
  replaced them.
- Risk report as a standalone primary surface — combined report + dashboard
  are the product surfaces.
- Separate snapshot/Playwright pipeline for `combined-html-report` — see
  ADR 0002.
- Legacy renderer cleanup tied to the retired snapshot path — without the
  snapshot rewire, there is no "legacy" path to shrink.
