# Current Plan

Active initiatives only. Future work lives in [`backlog.md`](backlog.md).
Track-level architecture detail lives in
[`../docs/architecture/devplans/`](../docs/architecture/devplans/). Cold
context is in `memory/archive/` (gitignored, not read by default).

## Portfolio Monitor

**State**: stable. No near-term scope open.

Recent landed work (one-liners; full detail in
`memory/archive/landed/portfolio_monitor_landed.md`):
- **Regime FRED empty-window no-op (root-cause fix for the recurring
  "Regime engine failed: FRED download failed for UNRATE" breakage).** The
  incremental macro sync sets `observation_start = last_cached_obs + 1 day`, so
  a monthly series (UNRATE, PAYEMS, CPIAUCSL, INDPRO) whose latest print is
  already cached has *zero* new observations until next month's release — the
  normal state for most of every month. The fredgraph CSV path raised "did not
  include usable observations" on that empty window; being a `DownloadError` it
  fell through to the JSON API, which then timed out → hard `RuntimeError` →
  the whole regime refresh failed. Now an empty *incremental* window is treated
  as "already current": `download_fred_series_csv(..., allow_empty=True)`
  returns an empty series instead of raising, and `sync_series` passes
  `allow_empty=True` only on the incremental branch (initial/forced full
  fetches still surface a genuinely-empty response). The JSON API is never
  touched for a no-op, so monthly series no longer depend on its timeout
  mid-month at all. Verified end-to-end against the live
  `refresh_data_and_run_regime_report` path on a temp cache copy: monthly
  UNRATE no-ops at 2026-04-01, daily/weekly series advance, the panel rebuilds
  fresh, and the engine runs `full_ensemble` (both primary layers available).
  Tests: `test_download_fred_series_csv_empty_window_respects_allow_empty`,
  `test_sync_series_incremental_empty_window_is_noop_without_api_call`.
- **FRED fetch resilience (configurable 60s timeout + backoff).** The regime
  refresh failed on a transient FRED `UNRATE` timeout — the report still showed
  the cached regime + a warning (graceful via the `engine_error`-with-data
  state), but the failure was avoidable. FRED API + fredgraph CSV fetches now
  default to a 60s HTTP timeout (was the global 20s), overridable via
  `FRED_HTTP_TIMEOUT_SECONDS`, with 2s/4s exponential backoff across the 3 API
  attempts. Monthly series (e.g. UNRATE) frequently fall through the
  empty-incremental-window CSV path to the API — now fixed at the root (see
  *Regime FRED empty-window no-op* above), so this generous timeout/backoff is
  the safety net for genuine transport failures, not the normal mid-month path.
- **Flex Web Service hardening (HTTP-timeout retry + token redaction).** The
  dashboard "Report Data" / Flex refresh failed outright on a single IBKR
  SendRequest HTTP timeout. `FlexWebServiceClient._download` now retries
  transient HTTP-layer failures (timeout / connection / 5xx `DownloadError`)
  with exponential backoff (`http_max_attempts=3`,
  `http_retry_backoff_seconds=2.0`, injectable `sleep`); Flex *protocol*
  "pending" errors are unaffected — they arrive as XML HTTP 200 and still flow
  through `fetch_statement`'s polling, never as `DownloadError`. Separately,
  the loader's `_redact_url_secrets` now masks the Flex token (`t=` / `token=`)
  alongside `api_key=`, so the token no longer leaks into the
  "Timeout while requesting …" error message / logs / dashboard warning surface.
- **Report restructure (Regime own tab + Performance merge + slim Overview +
  clearer wording).** Regime's 11 deep panels moved out of the Overview dump
  into a dedicated **Regime** top-level tab with an in-section chip sub-nav
  (Verdict & Disagreement / Axes & Layers / Risk Overlay / Contributors /
  History) over anchored, eyebrow-labelled groups; Overview keeps only a
  compact regime *summary* (hero + status cards) with a "View full regime
  analysis →" deep-link, so the deep panels render exactly once (no
  double-render — the trap that retired the previous standalone Regime tab).
  `regime_html` split into `render_regime_overview_summary` (hero) +
  `render_regime_detail_section` (grouped panels + sub-nav);
  `render_regime_section_body` kept as the full hero+detail body for the
  standalone CLI artifact (`render_regime_html_report`). The duplicate,
  non-sticky topline KPI strip was dropped (`build_topline_html` +
  `_regime_kpi_cell` removed) — the Overview KPI grid is the single headline
  row (regime cell dropped; ribbon + summary carry regime). **Performance USD /
  SGD** collapsed from two identical top-level sections into one **Performance**
  section with a USD/SGD `.segmented-control` toggle
  (`build_performance_section_body`); both charts init on load (unique
  `perf-plot-{usd,sgd}` ids) and the initially-hidden SGD chart is
  `__marketHelperResizePerformancePlots`-resized on first show. Nav 6→5 tabs
  (Overview / Performance / Risk / Regime / Artifacts — regime later moved to
  sit after Risk), fixing mobile nav-truncation. **Wording:** disagreement panel → "Method disagreement: …"
  with a per-axis "macro-layer vs market-layer alignment — a finer view than
  the overall verdict" note + a "Macro vs Market" column, so the overall
  verdict no longer reads as contradicting a per-axis "disagrees"; the
  crisis/overlay status reads **Overlay Active/Inactive** (hero card, risk
  overlay panel, and ribbon) instead of "Risk overlay on/off" sitting next to a
  "Risk State: Risk On" posture. Tests: `test_combined_html` (#regime present,
  merged-performance toggle, Overview summary vs full card) + new perf-merge
  test; `test_regime_html` "Method disagreement" assertion. Full unit suite
  green.
- **Mobile / responsive framework centralised in `_design_tokens.py`** —
  every HTML surface (dashboard chrome, combined report shell, regime ribbon,
  perf/risk/regime sections) consumes one shared `--app-bar-height{,-mobile}`
  / `--shell-max` / `--content-pad{,-mobile}` / `--bp-{phone,mobile,tablet}`
  var set, one `@media (max-width: 768px)` primitive-override block (covers
  `.app-bar`, `.section-nav`, `.kpi-strip`, `.metrics`, `.card`, `.chart-row`,
  `.report-shell`, `.report-section`, `.regime-ribbon`, `.report-table*`,
  `.segmented-control`), opt-in utility classes (`.responsive-grid-{2,3,4}`,
  `.responsive-cluster`, `.scroll-x-on-narrow`, `.responsive-hide-sm`,
  `.responsive-stack-sm`), and a `@media (pointer: coarse)` 40px touch-target
  floor. Magic `top: 49px` / `scroll-margin-top: 64px` / `max-width: 1540px` /
  `padding: 16px 24px` literals replaced with the shared vars across
  `_design_tokens`, `report_document`, `portfolio_html`, and
  `presentation/dashboard/components/common`. Standalone mobile `.app-bar__row`
  uses `grid-template-areas` so brand+meta share row 1 and section-nav drops
  to row 2 (height ≈ 96px under the 108px var). The dashboard iframe
  (`_inject_embedded_overrides`) re-declares `--app-bar-height{,-mobile}` to
  48/56px because hiding brand+meta collapses the iframe `.app-bar` to just
  the section-nav. Legacy 720 / 760 per-section `@media` breakpoints
  re-aligned to the canonical 768. Contract pinned by 36 assertions in
  `tests/unit/reporting/test_responsive_framework.py` (covers var declarations
  + breakpoint lock-step + utility classes + touch-target floor + sticky-top
  invariant + iframe cascade order + section-wide breakpoint conformance +
  `_MOBILE_OVERRIDES_CSS` non-resurrection). Future HTML inherits responsive
  behavior by reusing existing primitives or adding a utility class — no
  per-section `@media` block needed for shared primitives.
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
- GDrive Portfolio_Report mirror is now **strictly date-less**: the Flex
  performance CSV (locally `performance_report_YYYYMMDD.csv` for snapshot
  history) and the live positions CSV both mirror as
  `performance_report.csv` / `live_ibkr_position_report.csv` regardless of
  the caller-supplied local name. `_mirror_artifact_to_gdrive` gained a
  `target_name` override; the Flex caller (which previously inherited
  `output_path.name` and dragged the date over) now passes the canonical
  date-less name explicitly. Combined HTML mirror was already canonical.
  Two regression tests pin both call sites.
- **Combined report → Dashboard report rename**: literal substring
  `portfolio_combined_report` → `portfolio_dashboard_report` across the
  whole repo (output filename, GDrive mirror target, dashboard form
  default, daily-cron output, README, scripts/run_report.sh, tests,
  gotchas). Internal symbols like `GenerateCombinedReportInputs` keep
  the ‟combined" concept-word (still accurate — it combines perf+risk+
  regime view-models).
- **Duplicate Regime tab dropped**: previously the report rendered the
  full regime body twice (in Overview and in a standalone Regime tab).
  Overview is now the sole deep-link target for regime content; the
  ribbon + KPI cell stay as cross-tab summaries.
- **Timezone display simplified**: `format_local_datetime` no longer
  emits the OS-supplied tz name (‟Malay Peninsula Standard Time", ‟Pacific
  Daylight Time", etc.) — those vary by OS locale + DST and add visual
  noise. The UTC offset alone unambiguously pins the local zone.
- **Local Flex CSV no longer accumulates history**: `export_flex_horizon_report_csv`
  now writes the canonical date-less `performance_report.csv` and
  overwrites on every refresh (previously
  `performance_report_YYYYMMDD.csv` accumulated forever in
  `data/artifacts/portfolio_monitor/flex/`). The CSV's `as_of` column
  still records the report's report-as-of date. Resolver in
  `PortfolioMonitorQueryService` looks up the canonical name directly
  (no glob). Old dated files left on disk become harmless leftovers —
  delete manually if desired. New overwrite-pinning test prevents this
  from drifting back.
- **Pretty URL for the combined report**: the dashboard now serves the
  report at `http://<host>:<port>/portfolio/portfolio_dashboard_report.html`
  (no `?path=` query, no absolute-path leak). The legacy
  `?path=<abs-path>` route still handles any other artifact under
  `DATA_DIR`. `_served_artifact_url` prefers the pretty alias when the
  target IS the canonical combined report. Both routes return
  `Cache-Control: no-cache` so cross-device refresh works.
- **Cross-device access via Tailscale Serve**, not a broad bind. The
  launchers default `HOST=127.0.0.1` (loopback-only); Tailscale Serve
  is the recommended path for reaching the dashboard from another
  tailnet device. One-shot setup
  (`tailscale serve --bg http://127.0.0.1:18080`) writes config into
  tailscaled's persistent state — survives reboots, auto-issues a
  HTTPS cert. Tailnet URL: `https://<host>.<tailnet>.ts.net/portfolio/portfolio_dashboard_report.html`.
  The earlier 0.0.0.0 default was a security regression on hosts where
  Windows misclassifies a home Wi-Fi as "Public" — even with that
  classification, a broad python.exe inbound rule allows LAN devices to
  reach the dashboard. Loopback-only bind + Tailscale Serve removes
  that vector entirely. Subsequent services can mount at sub-paths
  (`--set-path=/foo`) under the same tailnet hostname.
- **Dashboard auto-starts on user login (Windows)** via a Startup-folder
  shortcut. Wrapper `scripts\launch_ui_startup.bat` is tracked in git;
  the .lnk itself lives in the user profile and isn't tracked. To
  recreate on a clean machine:
  ```pwsh
  $target  = 'D:\projects\git_projects\market_helper\scripts\launch_ui_startup.bat'
  $workdir = 'D:\projects\git_projects\market_helper'
  $shortcut = Join-Path ([Environment]::GetFolderPath('Startup')) 'Market Helper Dashboard.lnk'
  $ws = New-Object -ComObject WScript.Shell
  $sc = $ws.CreateShortcut($shortcut)
  $sc.TargetPath = $target; $sc.WorkingDirectory = $workdir
  $sc.WindowStyle = 7  # Minimized
  $sc.Save()
  ```
  Combined with Tailscale Serve's persistent tunnel, the dashboard is
  reachable from any tailnet device any time the user is logged in.
- **Default port 8080 → 18080**. 8080 is the most frequently-claimed
  port on dev machines (Tomcat / Jenkins / Spring Boot / Docker port
  maps all default there); 18080 is in the same memorability bucket
  with effectively zero collision risk. Updated Python defaults +
  both launchers + README env-var table + gotchas + operations doc.
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

3. **ML layers → unified `ML predictor` (new track).** The two gated SVM slots
   (`macro_truth_ml`, `return_truth_ml`) are superseded by a single **ML
   predictor at the allocation layer** — see *Regime-Aware Policy-Expert
   Allocation Model* below. Until that predictor's feature schema + trained
   artifacts are explicit, keep both slots unavailable / zero-weight and emit no
   fake ML outputs; the new track is what legitimately un-gates them.

Detail: `docs/architecture/devplans/regime_engine.md`.

## Regime-Aware Policy-Expert Allocation Model (research, new track)

**State**: **Phases 1–4 built this session (clean-room)** — prior-session harnesses
deliberately NOT reused; only task + lessons kept. P1–2 = monthly panel + 4 robust
experts; P3 = forward labels (3/6/12M; winner / margin / softmax / direct excess);
P4 = ex-ante ML predictor (21 ex-ante features, walk-forward, embargoed-CV Ridge →
**OOS rank-IC +0.20 at 6M**, predicted-best beats equal-weight 63%; heavy shrinkage
essential — naive low-alpha overfits); P5 = soft mixture-of-experts allocation
(blend → sleeves, turnover smoothing, vol-target ≤30% cap, cash-on-low-confidence);
P6 = walk-forward backtest vs 8 baselines + **HTML research report**
(`policy_expert_report.html`). **Verdict: MONITOR** — MoE Sharpe 0.65 vs 0.58
best-static (beats 6/7 baselines), but a simple cash-in-stagflation rule (0.79) is
competitive → ML's edge is risk-adjusted crisis-tilting, advisory-only. **MACRO sleeve
removed from the experts (2026-06-06, user request)** — it was a uniform +10 overlay
(trend is positive every regime), so it does not differentiate the experts and cancels
in the cross-sectional allocation (mixture + predictor skill unchanged: IC +0.20).
Experts are now EQ/CM/FI; dropping MACRO lowered every expert-based strategy uniformly
(MoE Sharpe 0.69→0.65) while preserving the ranking + verdict. **Phase 7 DONE** — the ML predictor runs live in the
**dashboard Regime tab**: a new "Policy-Expert Allocation (ML)" panel (allocation-layer
overlay, spec choice (b)) via `portfolio_html._attach_policy_allocation` →
`market_helper/regimes/policy_expert_predictor.predict_latest` (pure-Python, graceful,
advisory / read-only; the dormant `macro_truth_ml` / `return_truth_ml` slots are left
gated — see ADR 0006). **Both goal deliverables shipped**: `policy_expert_report.html`
(research report) + the live dashboard panel (preview:
`policy_expert_dashboard_preview.html`). **Verdict: MONITOR.** Optional follow-ups:
futures-financing/transaction-cost audit; live feature refresh on a schedule; reassess
vs the simple cash-in-stagflation rule. Full spec via the session goal + auto-memory
(`inflation_tilt_v0_research.md`).

**Idea**: 4 economically-interpretable **policy experts** from the Growth×Inflation
quadrants (Goldilocks / Reflation / Stagflation / Recession), then an **ML
predictor** that forecasts which expert outperforms forward (3/6/12M) from ex-ante
macro+market features → soft allocation across experts. The oracle regime study is
the **teacher / expert-discovery** step, not the tradable strategy; target =
expert attractiveness, not regime naming. Sleeves EQ/CM/FI/MACRO/CASH; FI & MACRO
as futures excess overlays (`R = cash·100% + Σ exposure·(sleeve−cash)`); portfolio
vol ≤ 30% **cap** (not floor).

**Lessons (do not rediscover)**: use **consensus-dated** regimes (the project
engine's growth score lags/inverts — do not use its labels here); directional
priors validated independently this session — Goldilocks EQ+long-dur, Reflation
EQ+CM/low-FI, **Stagflation zero-EQ + CM + short-FI + trend** (NOT cash; the
uniform **p10-floor** max-mean rule keeps CM), Recession low-EQ + long-dur + trend;
MACRO trend is crisis alpha (EQ-diversifying in stress); **select on p10 across
boundary-perturbed windows** (directional picks not date-overfit, only magnitudes
shrink); **stagflation is data-thin** (2022 + 1990; no 1970s in 1985+ data) →
heaviest caveat / most shrinkage.

**ML predictor** = realization of the gated `macro_truth_ml` + `return_truth_ml`
slots collapsed into one allocation-layer predictor (uses macro AND market/return
features; predicts expert attractiveness, not regime truth; engine
`macro_nowcast` / `market_implied` axes feed it as features). Reuse
`engine_v2.py` / `ml.py` / `regime_engine.yml`; arch choice (a) third blended
axis-layer vs (b) level-up allocation driver — spec points to **(b)**. Build at the
Phase-4 milestone.

**Artifacts (this session, clean-room)**: `scripts/research/policy_expert_data.py`
(monthly EQ/CM/FI/MACRO/CASH panel + synthetic-10Y FI + TSMOM MACRO + futures-excess
accounting) and `policy_expert_study.py` (consensus regimes + oracle + 400-draw
boundary-perturbation robustness + uniform p10-floor expert selection → stagflation
lands on the attack template). Records in
`data/research_artifacts/policy_experts.{json,md}`; the 4 experts' full-sample
monthly return series (the Phase-3 input) in `policy_expert_returns.csv`.

## Trade Advisor (integration)

**State**: MVP landed. Read-only (no order entry).

- **`advise` CLI → markdown advisory.** New `market_helper.cli.main advise`
  command reads the latest position report CSV + (optional) regime snapshot
  JSON, asks an OpenAI-compatible advisor endpoint (a local OpenClaw gateway
  backed by Codex/ChatGPT OAuth, model `openclaw/trade-advisor`) for a
  structured advisory (thesis / biggest risk / drift / actionable
  considerations), and writes a markdown artifact. Thin facade
  `workflows/generate_trade_advisory.py` → domain service
  `domain/integration/services/trade_advisor.py`. The network boundary is
  `post_chat_completion` (stdlib `urllib`, no new dependency), monkeypatched
  in tests. The prompt tells the model to use only the provided
  portfolio/regime and ignore remembered account facts (mitigates ChatGPT
  account-memory bleed into advisories). Token resolves arg → `OPENCLAW_GATEWAY_TOKEN` env → local.env;
  endpoint defaults to `http://127.0.0.1:18789/v1`; `--model` selects the
  shared (`openclaw/trade-advisor`) or isolated/panel
  (`openclaw/trade-advisor-panel`) agent; `--session-key` opts into
  server-side memory continuity. Tests: `tests/unit/cli/test_advise_command.py`,
  `tests/unit/domain/integration/services/test_trade_advisor.py`.

## Repository governance

Canonical layered-memory layout landed in ADR
[0003](../docs/decisions/0003-layered-memory-canonical-homes.md). See
[`AGENTS.md`](../AGENTS.md) for governance rules and reading order.

- **Agent skills + memory consolidation (2026-05-30)**: collapsed three skill
  trees to two canonical homes — `.claude/skills/` (Claude) + `.agents/skills/`
  (Codex) — and deleted the redundant root `skills/` mirror, whose symlinks
  were dead text-stubs under `core.symlinks=false` on Windows.
  `repo-onboarding-skill` became a real file under `.agents/skills/`; the
  misleading `conventional-commit` skill (Copilot boilerplate) was pruned.
  Migrated durable conda/env-setup facts (two roots, invocation patterns,
  Anaconda `defaults` ToS accept, `.condarc` D-drive pinning) into
  `memory/hot/operations.md`; distilled the personal auto-memory notes to tight
  pointers (~6.2 KB dup → one 27-line block). Untracked the leaked
  `.claude/worktrees/intelligent-shannon` gitlink. `lookthrough-researcher`
  stays a deliberate Claude/Codex copy-mirror — keep in sync, do **not**
  symlink (that is what just broke on Windows).
