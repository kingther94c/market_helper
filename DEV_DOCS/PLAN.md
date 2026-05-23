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
- `market_helper/reporting/` owns the HTML report renderers (combined,
  performance, risk, regime). HTML is the deliverable; the dashboard is the
  interactive entry that embeds the rendered HTML in an iframe.
- `configs/security_universe.csv` is the manually maintained instrument source
  of truth; `data/artifacts/portfolio_monitor/security_reference.csv` is a
  generated lookup cache.
- `nav_cashflow_history.feather` is the canonical daily NAV + cashflow store.

## Active Tracks

### Portfolio Monitor

Goal: keep the GUI/report workflow reliable while shrinking old rendering paths.

Landed (one-liner summaries; full detail in
`DEV_DOCS/archive/landed/portfolio_monitor_landed.md`):
- Combined report restructured — slim KPI strip, single regime section, vol
  matrix absorbs risk assumptions.
- Performance Overview + Benchmark Comparison — TWR/MWR/Vol/Sharpe excess
  over BIL-cash across USD/SGD; cash-vs-SPY benchmark table in returns + $ PnL.
- FX history coverage fix — `DEFAULT_YAHOO_FX_PERIOD` `2y` → `max` (requires
  `nav_cashflow_history.feather` rebuild).
- EQ lookthrough redesign — per-symbol country mix via
  `country_lookthrough_manual.csv`, leaf-bucket taxonomy
  (`eq_country_lookthrough.csv`), DM/EM aggregates re-expand;
  `lookthrough-researcher` skill mirrored at `.claude/skills/` and
  `.agents/skills/`.
- Sector benchmark switched SPY → ACWI — policy key renamed
  `us_equity_sector_policy_mix` → `equity_sector_policy_mix` (old key still
  accepted).
- Country × Sector heatmap added to EQ panel — outer-product joint with
  marginals matching the 1D breakdowns; amber "approximate" disclaimer.
- Pytest workspace temp stability — project-local `.pytest_tmp`, deterministic
  commodity-cache timestamps, machine-independent local-env lookup in tests.
- **Actionable warning surface complete** — dashboard `_render_feedback`
  promotes the three flex warnings ("history not found / empty", "dated CSV
  missing") to `pm-error` banners with inline "Run Flex Refresh", and the
  benchmark-cache warning gets a "Refresh Benchmark Cache" button (new `yahoo`
  action backed by `BenchmarkRefreshInputs`). Remaining warnings
  (history-path-not-configured, regime-artifact-missing) stay informational —
  no single button can remediate them.
- First-run CLI helper `scripts/dev/bootstrap_flex_history.py` resolves Flex
  creds env-first (matches `etf_sector_lookthrough`, `sync_fred_macro_panel`,
  and dashboard `_resolve_local_env_value`). User-facing wording across
  `generate_regime.py`, `run_fred_sync.sh`, regime devplan runbook, and
  `perf_report.ipynb` reordered: env-var → `<MARKET_HELPER_GDRIVE_ROOT>/local.env`
  → checked-in fallback.
- **Architectural route confirmed** — dashboard is the interactive entry, HTML
  is the deliverable. CLI / workflows / dashboard already share one
  input-contract layer (`application/portfolio_monitor/contracts.py` — 9
  `*Inputs` dataclasses); no separate snapshot pipeline or ViewModel rewire is
  planned.
- **Agent-shell ROOT inheritance gotcha — docs + code fix** —
  CLAUDE.md/AGENTS.md carry a "Per-machine env vars (Windows gotcha)" section;
  `market_helper.config.local_env.resolve_local_config_path` transparently
  falls back to reading `MARKET_HELPER_GDRIVE_ROOT` from the `HKCU\Environment`
  registry hive when `os.environ` is empty. Fallback is no-op on non-Windows
  and on explicit `environ=` call-sites; tests stay hermetic via a `conftest.py`
  autouse fixture.

Near-term work:
- (none open) Portfolio-monitor stack is at a stable shape. Further work moves
  through the Backlog as discrete asks land.

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

Landed (one-liner summaries; full detail in
`DEV_DOCS/archive/landed/regime_engine_landed.md`):
- Engine + CLI baseline (`regime-detect`, `regime-calibrate`,
  `regime-run-report`, `regime-refresh-report`), standalone HTML, GUI actions,
  combined report regime section. v1 rulebook deleted.
- Concept-level aggregation on both layers (macro + market). Signals → concept
  → axis; within-concept weights handle redundancy, concept weights express
  semantic importance.
- Symmetric tanh compression, beta-adjusted relative returns (60-day EWMA β),
  label-level hysteresis (median run length 3 → 18 bdays).
- Per-series normalization: `none/centered/threshold/zscore/minmax/percentile`,
  per-spec window/clip overrides, post-norm `compression: tanh`.
- Dormant signals shipped (config-flip activation): curve, breakeven, DXY, ISM
  proxy, housing, consumer sentiment, growth-vs-value, extra sector pairs.
  Activation runbook in `regime_engine_devplan.md`.
- Concept panel propagated to BOTH the standalone regime HTML and the combined
  report's regime section via shared `render_regime_section_body()`. Combined
  sticky ribbon stays minimal by design.
- **Anchor-period sanity harness** — `tests/unit/regimes/test_anchor_periods.py`
  pins regime output across COVID 2020, GFC 2008-09, 2022 inflation, 2025
  tariff shock. 11 pinned assertions; ~400 KB fixtures under
  `tests/unit/regimes/fixtures/`. Two structural market-only limitations
  documented (risk overlay 1-3 bday lag on shocks; commodity-vs-CPI decoupling
  in 2022 mid-year).
- **Auto-sync + historical baseline** — `regime-detect` auto-syncs the Yahoo
  market panel; pre-2025 panel (1984-2024, ~1 MB) checked into
  `data/external/regime_detection/historical/`. FRED auto-sync requires
  `FRED_API_KEY`; missing key disables macro layer gracefully. Cold-sync ~10s.
- **Per-frequency macro decay (structural)** — `SeriesSpec.decay_half_life_bdays`
  resolves via override → `frequency_hint` derivation → engine default. Behind
  the existing `recency_weighting` enable flag; Q8 confirmed engaging it does
  not materially shift anchors (decay-relevant series are too small a within-
  concept share).
- **Q7 risk-overlay calibration** — `enter_threshold` 0.75 → 0.65,
  `min_consecutive_days` 3 → 1. Same-day Lehman detection; benign FP rate 3.0%
  → 6.4%. Report: `data/research_artifacts/calibration_report.html`.
- **Q8 macro-axis calibration (FRED-hydrated)** — 162-config grid across
  1921-today. Layer blend balanced **0.50/0.50 + 0.50/0.50**, growth_thresh
  **±0.10**. Overall consensus 51% → 56%; growth axis 35% → 46% (+11pp). Risk
  overlay unchanged (Q7 still optimal). Report:
  `data/research_artifacts/macro_calibration_report.html`. Full grid +
  reproducer scripts under `data/research_artifacts/` and `scripts/research/`.
- **Q8 audit addendum (provisional → ship)** — Four-question audit on the
  shipped Q8: robustness sweep (21/21 perturbations win baseline, top-1 in
  16/21), label-ambiguity taxonomy (clear / defensible / definition-dependent;
  2 genuine "FAIL (clear)" cases isolated: 2022 H1 inflation growth + 2025
  tariff), real-latency probes (Q8 +3bd mean vs baseline; worst 2021 reflation
  +11bd — disclosed trade-off), concept attribution (2022 H1 inflation
  flip is the flagship blend win; 2024 disinflation Up is a CPI threshold-
  semantics artifact). Q8 ships unchanged with explicit "what would make Q8
  final" checklist (Q9 velocity layer, CPI neutral_level revisit,
  train/holdout split, concept-level tuning). Reports:
  `data/research_artifacts/macro_calibration_audit_en.html` +
  `macro_calibration_audit_cn.html`. Reproducer scripts:
  `scripts/research/macro_{robustness,label_ambiguity,latency_probes,concept_attribution}.py`
  + shared `anchors.py`.

Near-term work:
1. **Direction-honest velocity layer (Q9 candidate)** — Engine's YoY +
   threshold scoring is structurally level-based: it cannot read "inflation is
   falling toward target" as Down while CPI YoY is still above 2.5%. Add a
   MoM-velocity or 6m-change transform / concept to capture the direction axis.
   Calibration question: does it help 2022-H2 → 2023 disinflation without
   breaking 2022-H1 (where YoY is still rising)? Run as Q9 grid against the
   existing macro anchors.
2. **Optional**: pin per-anchor macro fixtures from `macro_scout_after.json` if
   a CI guardrail for the macro layer is desired (the full-history macro scout
   already serves as an offline measurement harness).
3. **Standing guardrail**: keep ML layers unavailable/zero-weight until model
   artifacts and feature schemas are explicit. Do not emit fake ML outputs.

Detail: `DEV_DOCS/docs/devplans/regime_engine_devplan.md`.

## Backlog

- Live TWS ergonomics: account/session metadata, account selection, broader
  contract fixtures.
- Flex ergonomics: historical backfill validation, archive metadata, stale XML
  diagnostics.
- Cached benchmark/proxy loaders beyond SPY, such as AGG and 60/40 benchmark
  support.
- Performance diagnostics — unsafe-metric slice (per-currency metric failures,
  partial NAV/cashflow series). Symmetric follow-on to the missing-history
  actionable warning that landed.
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
