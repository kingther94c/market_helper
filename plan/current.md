# Current Plan

Active initiatives only. Future work lives in [`backlog.md`](backlog.md).
Track-level architecture detail lives in
[`../docs/architecture/devplans/`](../docs/architecture/devplans/). Cold
context is in `memory/archive/` (gitignored, not read by default).

## Portfolio Monitor

**State**: stable. No near-term scope open.

Recent landed work (one-liners; full detail in
`memory/archive/landed/portfolio_monitor_landed.md`):
- Combined report restructured (slim KPI strip, single regime section).
- Performance overview + benchmark comparison vs cash + SPY (USD/SGD).
- FX history coverage fix (`DEFAULT_YAHOO_FX_PERIOD` `2y` → `max`).
- EQ lookthrough redesign (per-symbol country mix, DM/EM taxonomy).
- Sector benchmark switched SPY → ACWI.
- Country × Sector heatmap (with amber approximate disclaimer).
- Actionable warning surface complete — `pm-error` banners with inline
  "Run Flex Refresh" / "Refresh Benchmark Cache" buttons.
- Env-first secret resolution end-to-end + Windows agent-shell ROOT
  inheritance auto-recovery in `market_helper.config.local_env`.
- **Live Refresh + Flex Refresh CSVs auto-mirror to GDrive** —
  `PortfolioMonitorActionService.refresh_live_positions` and
  `rebuild_flex_performance` now call the new `_mirror_artifact_to_gdrive`
  helper after writing local artifacts, so the dashboard's "Live Refresh"
  / "Flex Refresh" buttons mirror their CSVs alongside the combined HTML
  (previously only the HTML mirrored; CSV mirrors only fired from the deep
  pipeline path and silently failed). Failure is non-fatal — local file
  stays the source of truth; the failure is surfaced as a UI sink event.
- **Windows scheduled task: daily report at 11:55 local** —
  `scripts/run_daily_report.bat` (→ `scripts/dev/run_daily_report.py`)
  runs end-to-end: live IBKR positions (graceful fall-through to cached
  CSV if TWS unreachable) → combined HTML → both CSV+HTML mirror to GDrive
  via Pattern B probe. Registered as Windows task `MarketHelperDailyReport`
  (`schtasks /Query /TN MarketHelperDailyReport` to inspect; `taskschd.msc`
  to edit). Logs land under `data/artifacts/scheduled/` (gitignored).
- **OS-aware GDRIVE_ROOT probe (zero-config Mac+Win)** —
  `market_helper.config.local_env.read_gdrive_root()` now resolves
  `MARKET_HELPER_GDRIVE_ROOT` via process env → Windows registry → OS-aware
  default probe of well-known Google Drive mount paths
  (`G:/My Drive/005 Portfolio` on Win;
  `~/Library/CloudStorage/GoogleDrive-<account>/My Drive/005 Portfolio`
  on Mac, with `GoogleDrive-*` glob + legacy-layout fallbacks). No
  per-machine env var setup needed for canonical layouts; env var still
  takes precedence as an override. Conftest neutralizes the probe for
  hermetic tests.
- **Combined report owns regime orchestration (ADR 0005)** —
  `GenerateCombinedReportInputs.regime_mode` (`cached` / `refresh-if-stale`
  / `force-refresh`, default `refresh-if-stale`) drives a new
  `RegimeReportProvider`
  (`market_helper/domain/regime_detection/services/regime_report_provider.py`)
  that owns load / refresh / fallback / staleness tagging in one place.
  `PortfolioReportData.regime_state: RegimeArtifactState` (always present)
  replaces the old `Optional[regime_view_model]` — the combined report's
  regime section, ribbon, KPI cell, and CSS are now always emitted, with
  `missing` / `engine_error` rendering an actionable explainer card instead
  of silently disappearing. The five `is None` branches that used to live
  in `portfolio_html.py` collapse to one switch on `regime_state.state`.
  Staleness uses the **same trading-day T-1 predicate**
  (`market_helper.common.datetime_display.is_as_of_stale`) that drives the
  report's overall `as_of_freshness_note` — single source of truth for what
  counts as out-of-date.
- Follow-up regression fix: `_load_regime_summary` in `risk_html.py` was
  reading the regime artifact unconditionally; once the combined-report
  pipeline started passing a path that may not exist yet (so the provider
  can refresh into it), the risk view-model build crashed with
  FileNotFoundError on fresh machines. Hardened with an `.exists()` guard
  and reordered `_assemble_report_data` so the regime provider runs before
  the risk view-model build (refresh has a chance to create the file before
  any consumer reads it).
- Long-term consolidation (SSOT): the risk sidebar's `RegimeReportSummary`
  is now **derived from the provider's view-model** via
  `derive_regime_summary_from_view_model`, not from a second independent
  file read. `build_risk_report_view_model` accepts a `regime_summary`
  param (preferred over the legacy `regime_path` for combined-report
  callers). The regime artifact is now parsed exactly once per combined
  report — by the provider — so the regime section and the risk sidebar
  can never disagree about what data they're showing. Legacy file-read
  path stays for standalone risk-only flows (CLI, ad-hoc).
- Test-suite hygiene: cleared 6 pre-existing failures unrelated to the
  regime work (4 mirror-dir tests carrying a stale
  `read_local_config_value` monkeypatch from the
  GDRIVE_ROOT refactor; 1 e2e position-report fixture missing 8 columns
  added after the schema extension; 1 Windows-incompat probe test skipped
  on `win32`). Full suite is now **472 passed, 11 skipped, 0 failed**.
- AGENTS.md gained a **Tests** section codifying maintenance rules
  derived from the three rot-classes above (refactor drift, schema drift,
  platform incompat). Required checks for refactor / schema-extension /
  platform-specific changes; per-commit triage checklist; explicit don'ts
  (no test-deletion to make suite green, no defensive monkeypatches when
  conftest already provides isolation).
- Cleared ~129 `Pandas4Warning: Timestamp.utcnow is deprecated` warnings
  by migrating 4 call sites in `yahoo_returns.py` + `commodity_spread_risk.py`
  to `pd.Timestamp.now("UTC")`. Suite now produces zero warnings.
- **Overview landing tab** — `build_overview_section_body` adds a new
  first section to the combined report carrying the headline KPIs plus
  the regime body inline. New KPI exclusive to Overview: **YTD $ PNL
  (SGD)** (TWR-windowed absolute P&L from
  `BenchmarkComparisonRow.twr_pnl` on the SGD perf view-model). The
  sticky topline strip keeps its 6-cell compact layout; Overview adds the
  $ PNL cell to its 7-cell grid.
- **Ex-ante Vol KPI** — renamed from the hard-coded "Target Vol (Fast)"
  label to a dynamic `Ex-ante Vol ({display_label})` that reads from
  `risk.vol_method` via `VOL_METHOD_DISPLAY_LABELS`, so the topline KPI
  follows the report's actual vol-method choice instead of always
  showing the Fast (geomean_1m_3m) snapshot. Sub-line gained
  `{method} · {corr} corr` for full transparency.
- Documented the misleading **NiceGUI "Your browser does not support
  ES modules"** dashboard fallback in
  [`memory/hot/gotchas.md`](memory/hot/gotchas.md) — confirmed
  reproducibly on the local install that NiceGUI serves the Vue module
  correctly (`200 OK · text/javascript · 164KB`), so when the fallback
  shows it's a client-side cache / extension / CSP issue, not a code
  bug. Static HTML report is unaffected.
- **Daily cron self-sufficiently refreshes regime** —
  `scripts/dev/run_daily_report.py` now passes
  `regime_mode="refresh-if-stale"`. The Windows scheduled task no longer
  produces reports missing the Regime section just because nobody clicked
  the separate "Refresh Regime" button. The dashboard's manual button
  remains as a `force-refresh` shortcut.
- Architectural route confirmed (no separate snapshot/Playwright pipeline —
  see ADR 0002).
- **System-design pass (Plans 1+2 from review; additive, no behaviour change)**:
  - Test coverage backfill — 5 new/extended test files, ~58 unit tests
    covering previously integration-only gotchas
    (`_extract_cashflow_date` precedence, `_compound_window_benchmark`
    NaN→0, `vol_proxies` validators raising on negative/zero,
    `risk_analysis` wrapper paths, `security_reference_table` re-export
    guard).
  - Dead-shim deletion: `market_helper/{utils,safety,ui}/` removed (53 LOC).
    Active importers in `providers/web_api/{client,mappers}.py` + 2 tests
    migrated to canonical `common.{read_only,time}`; README updated.
  - CLI now consumes `application/portfolio_monitor/contracts.py` —
    `PortfolioReportInputs.from_namespace(args)` /
    `GenerateCombinedReportInputs.from_namespace(args)` own Path/None
    coercion; `risk-html-report` and `combined-html-report` branches no
    longer inline per-arg coercion. Flags and facade signatures unchanged.
  - Documented the YAML/code layering in `reporting/risk_html.py` —
    `DEFAULT_*` constants are fallback defaults; canonical values live in
    `report_config.yaml` and are merged via `_parse_*_config`. Audit
    showed the original "lift constants to YAML" framing was wrong (already
    lifted); only the relationship was undocumented.

Further portfolio-monitor work rotates in through [`backlog.md`](backlog.md)
as discrete asks land.

## Regime Engine

**State**: calibrated through **Q9** (inflation velocity layer + train/holdout
discipline). Engine + concept aggregation + symmetric tanh + beta-adjusted
returns + label hysteresis + anchor-period sanity harness + auto-sync +
historical baseline + per-frequency decay all landed. See
`memory/archive/landed/regime_engine_landed.md` and
`data/research_artifacts/` for the calibration record.

Q9 landing summary (2026-05-23):
- New `inflation_velocity` concept (CPI/CoreCPI/PCE 3m annualized via the
  existing `qoq_annualized` transform), weight **1.0**.
- `macro_nowcast` layer weight 0.50 → **0.60**, `market_implied` 0.50 →
  **0.40**.
- Inflation deadband widened ±0.12 → **±0.15** (prevents over-rotation when
  YoY-level and 3m-velocity both read ~3% as Up).
- Growth velocity concept added but kept at weight 0 (grid showed no win).
- Mechanical: `SeriesSpec` gained optional `name` field so the same FRED
  `series_id` can produce multiple panel columns (e.g. CPIAUCSL yoy_pct +
  CPIAUCSL_velocity_3m). Backwards-compatible (name defaults to series_id).
- **Train/holdout split** introduced: 9 training anchors + 4 holdout (2008,
  2017, 2024, 2025). Grid selects on train only; holdout is hard
  non-regression constraint. Validation-aware selection (not selection
  pressure on holdout). Result: train +3.8pp, holdout +2.0pp vs Q8 — gap
  +0.3pp (almost zero).
- Reports: `data/research_artifacts/macro_calibration_q9_{en,cn}.html`.

Q9 neighborhood-stability addendum (2026-05-23, follow-up to user critique
"grid argmax can sit on noise spikes"):
- **Phase 1**: L1-neighborhood re-analysis of the original 360-config grid.
  Q9 ranked #9 by `robust_train = mean(self, neighbor median)`. Top robust
  (ivw=0.7, it=0.10) gained +0.6pp robust but lost -1.9pp holdout vs Q9.
- **Phase 2**: 162-config half-step refinement around contenders →
  augmented 522-config grid. Q9 ranked #35 of 136 eligible. Top robust
  unchanged; intermediate refined points (e.g. it=0.13) trade marginal
  robust gain (+0.4pp) for holdout loss (-0.6pp) — within noise.
- **Verdict: keep Q9 unchanged**. The trade-off curve runs along
  `inflation_thresh`: tighter it (0.10) wins HIGH-CPI anchors (2023:
  +18pp on i_match, 2020H2: +24pp) but loses NORMAL/AMBIGUOUS-CPI anchors
  (2017 Goldilocks holdout: -20pp, 2024 disinflation holdout: -12pp,
  2019 H2: -15pp, 2018 Q4: -14pp). Q9's wider it=0.15 handles 5 anchors
  better including 2 of 4 holdouts.
- Reports: `data/research_artifacts/macro_q9_neighborhood_addendum_{en,cn}.html`.
- Scripts: `scripts/research/macro_neighborhood_stability{,_v2}.py`,
  `macro_calibration_grid_q9_phase2.py`,
  `generate_q9_neighborhood_addendum.py`.

Open near-term work:

1. **(Optional)** Pin per-anchor macro fixtures from
   `macro_scout_q9_after.json` into the anchor-period harness for a CI
   guardrail on the macro layer. Not blocking — the full-history macro
   scout is the offline measurement harness today.

2. **Q10 candidates (parked, not active)**:
   - 2025 tariff shock channel — engine still has no single-event-shock
     signal; both axes failed clear-confidence on this anchor in Q8 and Q9.
   - 2022 H1 growth misread — macro_g says Up (correctly, YoY payrolls
     strong post-COVID) but market_g says Down (equity drawdown); Q9 60/40
     blend lifted train g_match from 11% to 53% but holdout misses persist.
     Investigate concept-level rebalancing for post-COVID base-effect
     handling.
   - Velocity layer 2nd-derivative refinement — current 3m annualized
     captures *rate*, not *acceleration*. A separate "deceleration" signal
     (velocity vs YoY divergence) could improve 2024 disinflation further.

3. **Standing guardrail** — Keep ML layers (`macro_truth_ml`,
   `return_truth_ml`) unavailable / zero-weight until model artifacts and
   feature schemas are explicit. Do not emit fake ML outputs.

Detail: `docs/architecture/devplans/regime_engine.md`.

## Repository governance

Canonical layered-memory layout landed in ADR
[0003](../docs/decisions/0003-layered-memory-canonical-homes.md). See
[`AGENTS.md`](../AGENTS.md) for governance rules and reading order.
