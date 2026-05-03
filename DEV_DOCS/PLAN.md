# PLAN

> Process gates live in `DEV_DOCS/RULES.md`. Historical detail lives in `DEV_DOCS/archive/` (gitignored, do not read by default).

## Objective

Build a broker-agnostic, **read-only** IBKR integration layer for market monitoring and portfolio analytics. Primary path: IBKR Client Portal Web API + TWS / IB Gateway via `ib_async` + Flex Web Service. Delivery surfaces: position reports, performance analytics, risk reports, regime detection, and a NiceGUI live dashboard.

## In / Out of scope

**In**: read-only provider adapters (Web API, `ib_async`, Flex), domain normalization, allocation/risk/reporting services, static HTML monitor + live dashboard.
**Out**: any order placement / cancel / modify capability in V1; raw TWS socket client; full multi-user product frontend or execution UI.

## Architecture (current state)

`cli → workflows (compatibility shims) → application → domain → data_sources / presentation`. `market_helper/application/portfolio_monitor` is the dashboard orchestration seam. The portfolio-monitor track (live TWS, Flex ingestion, combined-report pipeline, NiceGUI dashboard) shares one artifact-driven workflow direction.

## In Progress

- **Headless UI snapshot pipeline** (Phases A / B-1 / B-2 / C-risk landed). Remaining: **perf-parity** (cumulative/drawdown Plotly charts on the NiceGUI Performance USD/SGD tabs to reach parity with `render_performance_tab()`); **C-combined** (rewire `combined-html-report` after perf parity); **D** (delete the legacy `render_html` / `render_risk_tab` / `_render_*` template code in `risk_html.py` keeping the view-model builders, the re-export shim in `presentation/html/portfolio_risk_report.py`, and the HTML half of `combined_html.py`); **E** (replace HTML-string assertions in `tests/unit/reporting/test_risk_html.py` with view-model-level assertions).
- **Live TWS / `ib_async` ergonomics** — better account/session ergonomics, broader contract coverage, richer real-world fixtures.
- **Universe-first risk workflow** — cached proxy ingestion, more robust derivatives, deeper attribution math, tighter alignment between target-report semantics and HTML/notebook summaries.

## Next Steps

1. Cached benchmark-proxy loaders wired into the same artifact flow as Yahoo return histories (extends the SPY benchmark layer to AGG / 60-40 etc.).
2. Extend the performance tab with richer windows / benchmarks once the core combined layout is stable.
3. Risk attribution: covariance-consistent marginal/component risk attribution at security and bucket levels (current view is vol-contribution only).
4. Derivatives handling — options, `OUTSIDE_SCOPE` rows, inverse products, futures-specific exposure normalization.
5. Manual-override layer for provisional / account-specific universe entries (gitignored until reviewed).
6. Broaden look-through coverage for country/sector decomposition; expand explicit FI tenor mappings.
7. Account-selection ergonomics + account/session metadata surfacing for live TWS / IB Gateway runs.
8. More real IBKR payload fixtures and live-contract edge cases.

## UI / Reports Redesign

Phases P1-P7 + post-P7 polish (drift dumbbell, SPY benchmark trace) all **landed**. Detail in `DEV_DOCS/archive/ui_redesign_landed_phases.md`.

**Remaining phase:**

- **P8 — Legacy template deletion + test migration.** Delete `_render_summary_card` decorative gradient CSS in `performance_html.py`, redundant `<style>` blocks across the three reporting modules, the standalone `regime_html.py` shell (keep view-model builders), the `_styles()` function, and the duplicated segmented-control / chart-row CSS. Migrate `tests/unit/reporting/test_*.py` HTML-string assertions to view-model-level assertions; add CSS-presence tests against the shared token module. Pairs with snapshot-retirement Phase D.

**Out of scope for this track:** dark mode, multi-user variations, print stylesheet, replacing Plotly. Mobile-only table polish landed in commit `522ccc8` (minimal `@media (max-width: 768px)`, no desktop impact).

## Regime v2 — Multi-Method 2D Framework

Detection / policy / CLI / HTML / operator entry points all landed. Detail in `DEV_DOCS/archive/historical_plans.md` (M1-M7 detail) and `DEV_DOCS/archive/completed_history.md`.

**Active methodology:** 2D `(growth × inflation)` quadrant taxonomy — Goldilocks / Reflation / Stagflation / Deflationary Slowdown — with an orthogonal risk-on/risk-off overlay. Two methods ship today: `macro_regime` (FRED panel, fast/slow buckets, raw signed aggregation, `fast=0.70 / slow=0.30` default per axis) and `market_regime` (Yahoo panel, equity/credit/vol proxies). Ensemble aligns on common dates, votes per axis with confidence weighting, ORs the risk-off flag, reports `method_agreement`. Policy resolution: quadrant table + crisis overlay (`equity_shift_pct * crisis_intensity` from EQ into CASH/GOLD/FI, vol multiplier reduced).

**Outstanding:**

1. **GUI action integration** — call `regime-refresh-report` / `regime-run-report` from NiceGUI, mirroring the performance/risk action pattern.
2. **Calibration notebook pass** — run macro/market notebook over GFC, COVID, 2022 inflation, 2023 disinflation, current data; adjust YAML weights before changing code.
3. **ML method skeleton** — supervised classifier + unsupervised clustering drop-in under `market_helper/regimes/methods/` conforming to `RegimeMethod`.
4. **Backtest sanity harness** — 15-year window, validate against GFC, COVID, 2017 Goldilocks, 2022 Reflation/Stagflation turn; commit fixture snapshots.
5. **Calibration notebook** — walk-forward tuning of `zscore_window_bdays`, `min_consecutive_days`, crisis-overlay magnitudes.

## Backlog

- Extend the TWS `ib_async` adapter beyond client/portfolio/report/contract-lookup (market-data, richer account/session tooling).
- Deepen the Flex path around historical backfill ergonomics, archive validation, statement/account metadata.
- Continue shrinking compatibility shims as application/domain ownership clarifies.
- Add e2e workflow coverage across Web API, TWS, and Flex.
- Workbook-style report generation (target_report.xlsx parity) — practical sequence: stabilize mapping/exposure → bucket/risk calculations → workbook generation/formatting. Detail in `DEV_DOCS/archive/historical_plans.md` (Target Report Gap).

## Domain gotchas

- FI tenor bucketing is explicit mapping (`ZT → 1-3Y`, `ZN → 7-10Y`), not derived from duration.
- Flex XML cashflow attribution uses `reportDate`, not `settleDate`.
- Portfolio AUM denominator excludes futures/options (stock-like + cash only).
- FI proxy-vol applies a modified-duration adjustment rather than using MOVE price vol directly.
- `security_reference.csv` is regenerated by tooling; `security_universe.csv` is manually maintained.
- `nav_cashflow_history.feather` `fx_usdsgd_eod` is **SGD per 1 USD**. Benchmark SGD return uses `(1 + r_usd) * (fx_t / fx_{t-1}) - 1`.
- Yahoo return cache stores **log returns**; `expm1` to convert to simple when compounding for chart cumulative.

## Testing

`PYTHONPATH=. PYTHONPYCACHEPREFIX=/tmp/pycache pytest -q tests/unit` — full unit suite green. Coverage is solid at the unit level (portfolio-monitor services, UI contracts, regime methods, benchmark math). Integration risk is concentrated at provider variability, snapshot rendering parity, and artifact/config drift across CLI / scripts / UI forms.
