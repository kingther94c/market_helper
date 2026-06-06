# Portfolio Monitor Devplan

## Current Focus

The portfolio monitor is the primary operator surface. As of the latest
architectural review the stack is at a **stable shape** — no near-term scope
is open here. Further work moves through the PLAN.md Backlog as discrete asks
land.

Current ownership rules:
- `market_helper/application/portfolio_monitor/` owns GUI-triggered actions,
  artifact path resolution, progress events, and output contracts. All
  CLI / workflows / dashboard call-sites share one input-contract layer
  (`application/portfolio_monitor/contracts.py` — 9 `*Inputs` dataclasses
  including `BenchmarkRefreshInputs` for the actionable benchmark-cache
  warning).
- `market_helper/domain/portfolio_monitor/services/` owns reusable analytics:
  NAV/cashflow history, performance windows, risk math, Yahoo return cache,
  SPY/BIL benchmark attachment, fixed-income vol, and proxy logic.
- `market_helper/presentation/dashboard/` owns the live NiceGUI UI. The
  dashboard is the **interactive entry**; HTML is the **deliverable** — the
  dashboard embeds the rendered HTML in an iframe. No separate snapshot
  pipeline or ViewModel rewire is planned. `/portfolio` renders inside the
  shared dashboard shell (`shell.py`) alongside `/advisor` and the `/` landing —
  one of two parallel surfaces, not a platform ([ADR 0008](../../decisions/0008-unified-dashboard-shell.md)).
- `market_helper/reporting/` owns the HTML report renderers (combined,
  performance, risk, regime).

Canonical artifacts/config:
- `configs/security_universe.csv`: manually maintained semantic universe.
- `data/artifacts/portfolio_monitor/security_reference.csv`: generated lookup
  cache.
- `data/artifacts/portfolio_monitor/flex/nav_cashflow_history.feather`: daily
  NAV/cashflow store.
- `configs/portfolio_monitor/report_config.yaml`: tracked risk/report runtime
  config.
- `configs/portfolio_monitor/local.env`: gitignored account/provider secrets;
  set `MARKET_HELPER_GDRIVE_ROOT` and place `local.env` at `<ROOT>/local.env`
  to share one file across machines via GDrive sync. Process env always wins;
  `<ROOT>/local.env` is the canonical per-machine fallback;
  `configs/portfolio_monitor/local.env` is the final fallback. On Windows the
  `resolve_local_config_path` helper reads `MARKET_HELPER_GDRIVE_ROOT` from
  the User registry hive if `os.environ` is empty (see
  `memory/hot/operations.md` "Per-machine env vars" section).
- `configs/portfolio_monitor/us_sector_lookthrough.json`: tracked ETF sector
  look-through cache (auto-managed by `etf-sector-sync`).
- `configs/portfolio_monitor/country_lookthrough_manual.csv` +
  `sector_lookthrough_manual.csv`: per-symbol manual fallbacks populated by
  the `lookthrough-researcher` skill (mirrored at `.claude/skills/` and
  `.agents/skills/`).

## Near-Term Next Steps

(none — the portfolio-monitor stack is stable. PLAN.md's Backlog tracks the
items that may rotate in as discrete asks land.)

Reference, in priority order if any one becomes a real ask:

1. **Performance diagnostics — unsafe-metric slice**
   Symmetric follow-on to the missing-history actionable warning that already
   landed. Promote per-currency metric failures and partial NAV/cashflow series
   from silent `n/a` to structured warnings (with remediation buttons where one
   action can fix it).

2. **Cached benchmark/proxy loaders beyond SPY**
   AGG, 60/40, etc. — would generalize the Yahoo-cache pattern exercised by
   the new "Refresh Benchmark Cache" action.

3. **Live TWS ergonomics**
   Account/session metadata, account selection, broader contract fixtures.

4. **Flex ergonomics**
   Historical backfill validation, archive metadata, stale XML diagnostics.

5. **Commodity spread risk treatment**
   Config-driven CM multi-leg spread synthesis for NG first: collapse
   same-account/root/exchange futures legs into one risk row, estimate
   front-contract beta with EWMA-weighted Huber regression, cache beta/spread
   risk analytics for seven days, and combine cached spread diagnostics with
   each selected front-contract vol method behind the normal commodity
   position table.

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
- **Separate snapshot/Playwright pipeline for combined-html-report** — the
  architectural review confirmed CLI / workflows / dashboard already share one
  input-contract layer; the static HTML renderer in `market_helper/reporting/`
  stays the canonical render path. (This item was previously listed as the top
  near-term work; it is now retired by decision, not deferred.)
- **Legacy renderer cleanup tied to the retired snapshot path** — without the
  snapshot rewire, there is no "legacy" path to shrink.
