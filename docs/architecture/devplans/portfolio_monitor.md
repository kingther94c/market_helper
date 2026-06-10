# Portfolio Monitor Devplan

## Current Focus

The portfolio monitor is the primary operator surface. A **full-stack
redesign pass (2026-06-10)** re-audited every layer (domain analytics,
pipeline, application, dashboard, HTML reporting) and landed the items below;
the stack is again at a **stable shape** with no near-term scope open.
Further work moves through the PLAN.md Backlog as discrete asks land.

### Redesign pass (2026-06-10) — what changed and why

- **Risk attribution is now covariance-consistent (Euler).** The
  `risk_contribution_*` columns previously held standalone `|weight x vol|`
  mass — correlation-blind, always positive, never summing to portfolio vol
  (an FX-hedge short *added* "contribution"). They now hold signed Euler
  component contributions under the snapshot inter-asset correlation:
  ``l_i * sum_D rho(C_i,D) L_D / sigma_p``. They sum exactly to the portfolio
  vol per method; hedges show negative. The breakdown tables keep a parallel
  `standalone_risk_*` mass so their per-bucket "Vol" column still means
  standalone vol (`standalone / |dollar_weight|`), not a correlation-scaled
  hybrid. Pinned by `tests/unit/reporting/test_risk_euler_attribution.py`.
- **Concentration + tail stats on the summary card**: effective positions
  (1/HHI on gross shares), top-5 gross share, and 1-day 95% VaR (normal,
  selected vol method).
- **Position tables sort by |contribution| desc** (excluded rows last) — the
  risk drivers lead instead of CSV file order.
- **Commodity correlation heatmap uses a diverging palette** (blue negative /
  white zero / red positive) with signed values — negative correlation is the
  diversification signal and used to be clamped to white.
- **Dead toy risk API removed**: `portfolio_volatility` (unsigned weights —
  wrong for shorts), `build_historical_correlation`, and
  `build_estimated_correlation` had zero production/test call sites but were
  re-exported by `domain/.../risk_analysis.py` as if canonical. Deleted; the
  group-loadings model (`_build_group_loadings` →
  `_portfolio_vol_from_group_loadings`, signed exposures) is the only vol
  aggregation path.
- **Degraded completions are warnings, not successes**: the TWS-unreachable →
  cached-snapshot fallback now sets a `warning` action status (amber chip +
  persistent toast) and the message carries the snapshot's mtime + age via
  `_snapshot_age_label`. Drawer job history renders the amber state.
- **Dashboard freshness**: the `as_of_freshness_note` the application layer
  always computed is now rendered in the Report Data status card; drawer
  action buttons disable while a job runs (previously only the app-bar
  Refresh did).
- **Silent failure hygiene**: commodity-spread risk computation logs a
  warning with root/exchange/legs before degrading to per-leg vol (was a bare
  `except Exception: None`); performance analytics document the TWR
  fillna(0) convention and the observed-days annualization basis inline.

### Pipeline structure (seam map for the future split)

`domain/portfolio_monitor/pipelines/generate_portfolio_report.py` (~2k lines)
audited 2026-06-10; behavior fine, structure mixed. Natural seams, in extract
order: Flex archive ops (lines ~150-1090: fetch/parse/promote/batch-poll) →
`flex_archive.py`; live security enrichment (~1640-1860: contract details +
runtime remap, the densest block) → `live_security_enrichment.py`; row field
mapping (~1915-2040). Risk/config facades stay. Keep the module re-exporting
so CLI/test imports survive. Tracked in backlog; do not split casually — the
suite pins import paths.

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

## Deferred

These are useful but not next:
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
