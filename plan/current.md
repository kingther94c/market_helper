# Current Plan

Active initiatives only. Future work lives in [`backlog.md`](backlog.md).
Track-level architecture detail lives in
[`../docs/architecture/devplans/`](../docs/architecture/devplans/). Cold
context is in `memory/archive/` (gitignored, not read by default).

## Portfolio Monitor

**State**: stable. No near-term scope open.

Recent landed work (one-liners; full detail in
`memory/archive/landed/portfolio_monitor_landed.md`):
- **FX Hedging Advisor (Risk → FX).** New advisor that converts a USD/SGD hedge
  amount (default = funded USD AUM, "full AUM exposure") into a target FX
  allocation across liquid CME FX futures (EUR/GBP/AUD/JPY/CNH vs USD). Weekly
  (W-FRI) log-return OLS of the SGD/USD spot return on the instruments' spot
  returns gives the hedge ratios (betas); these × notional → USD-per-contract →
  whole contracts (halves away from zero), with front-IMM-quarter expiry and
  indicative carry from configured ON rates. **Conventions** ([ADR 0006](../docs/decisions/0006-fx-hedge-regression-convention.md)):
  value-in-USD price basis (USD per unit; the inverse of `fx_usdsgd_eod`), so a
  positive beta ⇒ long the foreign future / short USD = the correct hedge for a
  USD-overexposed SGD investor. Live validation: R²≈0.88, all betas positive,
  CNH+EUR dominant (matches SGD's MAS basket). Yahoo has no long *daily* CNH
  history, so onshore `CNY=X` proxies the CNH-future beta (traded instrument is
  still the CME USD/CNH future). Owns a JSON artifact
  (`data/artifacts/portfolio_monitor/fx_hedge/fx_hedge_allocation.json`) behind
  a regime-style provider (`provide_fx_hedge_allocation`, modes cached /
  refresh-if-stale[30d] / force-refresh); `computed_fresh` drives the
  "Freshly computed / Loaded from cache (N days old)" badge. Renders as a card
  under the **Risk** section (`reporting/fx_hedge_html.py`), always-on
  (ok/stale/missing/error → explainer card), with an explicit conventions block.
  New CLI `fx-hedge-report` (force-refresh default); plain risk/report flows
  resolve the path to None and skip the provider (no side-effect Yahoo fetch).
  Files: `domain/portfolio_monitor/services/fx_hedge_advisor.py`,
  `reporting/fx_hedge_html.py`, `configs/portfolio_monitor/fx_hedge_advisor.yml`,
  wiring in `contracts.py` / `application/.../services.py` / `portfolio_html.py`
  / `cli/main.py` / `workflows/generate_report.py`. Devplan:
  `docs/architecture/devplans/fx_hedge_advisor.md`. Tests: new
  `test_fx_hedge_advisor.py` (24) + `test_fx_hedge_html.py` (4) + combined-html
  FX assertions; full unit suite green (601 passed, 1 skipped).
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

3. **Standing guardrail** — Keep ML layers (`macro_truth_ml`,
   `return_truth_ml`) unavailable / zero-weight until model artifacts and
   feature schemas are explicit. Do not emit fake ML outputs.

Detail: `docs/architecture/devplans/regime_engine.md`.

## Trade Advisor (AI+ — opt-in parallel layer)

**State**: landed (`market_helper/trade_advisor/ai/` + `/advisor` AI+ tab).

History: a first LLM `advise` **CLI** experiment (`e91d3ea`,
openclaw_thinking_partner) was reviewed and **removed** — a bare LLM advisory
bolted on as a CLI clashed with the umbrella's design (rule-based, explainable,
bounded controls). Its one design-aligned kernel — *use the live regime snapshot
as context* — was salvaged the rule-based way as
`application/trade_advisor/regime_seed.py` (no model in the loop).

On the operator's direction, AI was then **re-introduced the right way**: a
*parallel, opt-in* layer, never replacing the rule-based engine, selectable via a
**tab** on `/advisor`.
- `trade_advisor/ai/gateway.py` — OpenAI-compatible OpenClaw client (network
  boundary `post_chat_completion`, stdlib urllib). Config from env (defaults
  `http://127.0.0.1:18789/v1`, `openclaw/trade-advisor`); token resolves
  explicit → `OPENCLAW_GATEWAY_TOKEN` env → local.env, **never logged / never in
  a URL**. `GatewayAuthMissing` keeps AI+ off until a token is set.
- `trade_advisor/ai/advisor.py` — summarizes the **rule-based ideas** + book +
  regime into a prompt (pinned to provided data, forbids order output) →
  `request_ai_advisory` → `AiAdvisory`. So AI+ is "+": it synthesizes the
  deterministic engine's output, which remains the source of truth.
- `/advisor` now has **Rule-based** (default) and **AI+** tabs. AI+ reuses the
  shared `build_run_context`, runs the rule-based advisors, then renders the
  gateway's advisory (`ui.markdown`, display-only) with model/token metadata and
  an "analysis only, not orders" banner. Graceful: no token / unreachable
  gateway → explainer card; the rule-based tab is unaffected. Controls stay
  bounded (model select + include-ideas switch; no free-text prompt).
- Tests: `tests/unit/trade_advisor/ai/` (gateway token precedence, bearer-not-in-
  URL, transport errors, prompt guards, advisory parse) + `build_run_context` /
  `AI_MODELS` page tests.
- **Live-verified** against the running OpenClaw gateway (loopback:18789, model
  `openclaw/trade-advisor`): a real advisory came back synthesizing the
  rule-based ideas + book + regime (positioning / which ideas matter / biggest
  risk / what the rules miss). Token read from the gateway's own config in
  the operator's machine; never persisted to the repo.

## Trade Advisor (umbrella)

**State**: **M1–M6 all landed** — umbrella hosts **four** advisors (Option,
Roll, FX Hedging + carry tilt, Trade Ideas) under one bounded-control UI;
decision journal + Inbox + cross-device snapshot; real-book seeding; CBOE cache;
how-to doc. Full unit suite green (672). Acceptance review:

| # | Bar item | Status | Evidence |
|---|---|---|---|
| 1 | Open & understand, no docs | ✅ | `/advisor` → Run → ranked cards (label/economics/why-now); browser-verified on live CBOE |
| 2 | Real book + live data; graceful | ✅ | "Use my portfolio" seeds held stk/opt + AUM; watchlist-only fallback w/ note; FX missing → actionable INFO |
| 3 | Fully explained + what-if==engine | ✅ | full per-idea fields; live what-if re-price; `what-if==engine` unit test |
| 4 | Decision journal → Inbox → snapshot | ✅ | Proceed persisted (JSONL), Inbox updated, snapshot HTML written — browser + headless |
| 5 | All advisors, one UI, zero-UI-to-add | ✅ | Option/Roll/FX(+carry)/Ideas via registry; INFO cards render; 5th = adapter only |
| 6 | Snapshot mirrors cross-device | ✅ | snapshot HTML + GDrive mirror helper; interactive stays localhost/Tailscale |
| 7 | Responsive; suite green | ✅ | async (no freeze) + CBOE cache + 12s timeout; 672 passed / 1 skipped, 71 TA tests |
| 8 | Docs current | ✅ | devplan + `docs/operations/trade_advisor_howto.md`; plan reflects reality |

Non-goals respected: no order entry; bounded controls (no free-form/NLP); no
opaque ML / optimizer; no new UI framework; single-operator; no tick infra.

**Polish pass (2026-06-04)** — four reviewable increments on top of M1–M6:
- **What-if spot ↔ chain skew (sticky-moneyness).** Each idea carries the
  chain's observed skew (`ChainSnapshot.atm_skew` → `OptionIdea.iv_skew`); a
  bounded "Link IV to chain skew" toggle (default on) makes the spot slider move
  each leg's IV along that skew (`Δiv = iv_skew·ln(base/spot)`) instead of holding
  it flat. `iv_skew=0` preserves the load-bearing `what-if == engine` invariant.
- **Earnings feed → EventRisk.** `domain/option_advisor/earnings.py` (pure
  `event_risk_from_dates` core + graceful yfinance wrapper) finally populates the
  long-dormant `EventRisk`; wired through `signals`/`service`/adapter with a
  `fetch_events` flag, a per-symbol `earnings=` override, a dashboard "Check
  earnings" switch, and a `--events` CLI flag. Surfaces in the card headline
  (days-to-earnings), the `event_risk` audit filter, and the ranking event-safety
  term.
- **Dedicated detail bodies for FX / Roll.** Card detail now dispatches on
  `body_kind`: FX alloc → hedge-legs table + totals; FX carry → ranking table;
  Roll → position facts grid; option → existing payoff/Greeks. Previously FX/Roll
  cards opened to an empty body (the generic loop only read option `legs`). Pure
  row/fact builders are unit-tested; ui.* wrappers stay thin.
- **Coverage + review.** +35 tests (skew, earnings incl. ranking event-safety,
  body builders, an adapter→body **contract** test pinning detail keys). Code
  review found the structure already well-layered — no large refactor needed;
  fixed a `_num` integer-spec sign-drop bug found while adding the FX table.
  Full unit suite green.
- **Regime auto-seed (`application/trade_advisor/regime_seed.py`).**
  `current_regime_seed()` reads the latest regime snapshot and defaults the
  `/advisor` *Regime* / *Confidence* / *Crisis* controls (`base_regime` →
  dropdown, `confidence` → High/Medium/Low, `risk_overlay_on` → crisis), still
  user-overridable. Rule-based, no model in the loop — the explainable
  counterpart to "have the LLM read the regime". Best-effort: missing/malformed
  artifact or an unrecognised label → empty seed (manual entry). 7 tests.

Earlier milestone notes (umbrella **M1 landed** = shared contract + registry + option adapter);
two component engines **built** — Option Advisor + FX Hedging Advisor.

- **M1 landed** — `market_helper/trade_advisor/`: `Advisor` protocol, shared
  `Suggestion`/`AdvisorResult`/`AdvisorContext` contracts, `AdvisorRegistry`, and
  the option-advisor adapter (registered in place, zero behavior change). The
  option engine now speaks the umbrella's uniform suggestion shape. 8 tests;
  full unit suite green (635 passed).
- **M2 landed** — interactive **NiceGUI `/advisor` page** (wired into
  `create_app`): bounded-control inputs (selects / number / switches — **no free
  text**) → Run → ranked idea cards (PROCEED→MONITOR→REJECT) → expandable
  **Plotly payoff** + Greeks + sizing + full **audit trail** + **live what-if**
  (bounded qty / IV / spot controls re-price via Black–Scholes;
  `whatif`/`whatif_from_detail` in `option_advisor.structures`). Orchestration in
  `application/trade_advisor/` (cross-advisor inbox, graceful per-advisor
  failure). **Browser-verified** end-to-end on **live CBOE** data: 9 SPY/QQQ
  ideas, `data mode: live_chain`, cards + payoff chart + audit all render, no
  server errors. `what-if == engine` unit test passes. Full suite green (646).
- **M3 landed** — decision journal (`trade_advisor/journal.py`, append-only JSONL
  under `data/artifacts/trade_advisor/`): `/advisor` cards carry
  Proceed/Monitor/Reject + note → persist → cross-advisor **Inbox**; each
  decision regenerates a static **snapshot HTML**
  (`reporting/trade_advisor_html.py`) written + mirrored cross-device via the
  existing GDrive helper. Persist→inbox→snapshot verified end-to-end (unit +
  headless). Full suite green (654).
- **M4 landed** — **Roll Reminder** advisor (`trade_advisor/adapters/roll.py`):
  reads `context.held_options` → DTE / ITM / short-ITM assignment flags + roll
  suggestions; registered so it shows up in `/advisor` + the Inbox with **zero
  advisor-specific UI** (page runs all registered advisors). Proves "adding an
  advisor needs no UI work" (#5). 5 tests; full suite green (659).
- **Real-book seeding (#2) landed** — `context_from_positions_csv`
  (`application/trade_advisor/portfolio.py`) derives real held stocks + held
  options + funded AUM from the live positions CSV (classify by `internal_id`
  prefix; AUM = stock + cash, excl. options/futures; held options parsed from
  `option_*` cols + OSI `local_symbol`). `/advisor` gains a **"Use my portfolio
  (live positions)"** toggle (default on) → Option + Roll run on the real book;
  degrades gracefully to a watchlist-only scan when no live CSV. Also fixed a
  latent run()-render arity bug from the M3 signature change. 2 tests; full
  suite green (661).
- **M5 landed** — **FX Hedging** advisor folded into the umbrella
  (`trade_advisor/adapters/fx_hedge.py`): wraps the existing FX hedge engine,
  cached-by-default (no network; on-demand `refresh=True` force-recomputes) →
  emits a hedge-target suggestion + an **FX Carry Tilt** sub-module (rank ccys by
  overnight-rate carry). Third advisor, zero advisor-specific UI; INFO fallback
  when no allocation cached. 5 tests; full suite green (666).
- **M6 landed** — **Trade Ideas** advisor (4th; regime-aligned sleeve tilt via
  `suggest.quadrant_policy`, advisory per ADR 0006) → all four advisors under one
  UI. Plus #7 a short-TTL **CBOE response cache** + tighter timeout (re-runs
  instant; throttled CDN fails fast to fallback) and #8 a **how-to doc**
  (`docs/operations/trade_advisor_howto.md`). 6 tests; full suite green (672).

- **Plan** at [`docs/architecture/devplans/trade_advisor.md`](../docs/architecture/devplans/trade_advisor.md):
  a `market_helper/trade_advisor/` umbrella that turns portfolio + market +
  regime context into ranked, read-only trade *ideas* across a family of
  advisors (Option [built]; FX Hedging [built] — spans report + interactive,
  with an FX Carry Tilt sub-module; Roll Reminder; general Trade Ideas; + a
  registry for more) behind **one shared suggestion contract** and **one
  interactive GUI**. Goal-altitude: fixes objective / hard constraints / UI +
  interaction design; leaves mechanics to per-milestone passes. Key UX: an
  interactive NiceGUI "Advisor" page (inputs → run → ranked cards → **live
  what-if** payoff/greeks/sizing recompute → Proceed/Monitor/Reject journal)
  plus a static snapshot in the combined report. Milestones M1–M6.

### Option Advisor (component #1)

**State**: MVP **landed and runnable** (M1+M2). Advisory-only, read-only.
Design memo: [`docs/architecture/devplans/option_advisor.md`](../docs/architecture/devplans/option_advisor.md).

- **Module** `market_helper/domain/option_advisor/`: pure-stdlib Black–Scholes
  (`pricing.py`, `statistics.NormalDist` — **zero new deps**), frozen-dataclass
  contracts, a multi-provider data layer (`providers.py`), and the
  `signals → candidates → filters → ranking → service` pipeline. Runnable CLI:
  `python -m market_helper.domain.option_advisor SYM... [--aum --hold SYM:QTY
  --regime --override SYM:spot=..,iv=.. --json out.json]`. YAML rules at
  `configs/option_advisor/advisor_rules.yaml` (no-code tuning, mirrors
  `quadrant_policy.yml`).
- **Real option-chain data, not just a fallback**: community research (15+
  sources) + live IBKR probe. Primary = **CBOE delayed JSON** (free, no key,
  full greeks+IV+OI via stdlib `urllib`) — verified live on SPY/QQQ/AAPL.
  Fallback = yfinance (greeks computed locally). Final fallback = **synthetic
  vol-surface** from spot + ATM IV with research-backed skew/term defaults
  (skew ≈ −0.12 index, 1/√T decay); **user can override spot and IV**. IBKR
  underlying snapshot (spot / ATM-IV / IV-rank) verified via MCP; in-repo
  `ib_async` chain adapter is M5.
- **Honesty tagging**: `data_mode` (live_chain / live_anchored / synthetic /
  user_override); model-only ideas are capped at MONITOR and never PROCEED.
  PROCEED/MONITOR/REJECT labels carry a per-idea filter audit trail; sizing caps
  to a % of funded AUM (excludes options/futures, per the AUM gotcha).
- 26 hermetic unit tests (pricing/greeks, synthetic skew, structure payoff,
  filters/sizing, ranking, regime gate). **Full unit suite green (611 passed).**
- **Scope**: [ADR 0007](../docs/decisions/0007-option-advisor-advisory-scope.md)
  (advisory in scope; broker execution out, per ADR 0001) — **Accepted** on the
  user's directive to build a runnable version. Read-only invariant intact: the
  advisor only fetches public data and emits ideas, never orders.
- **Next (M3+)**: combined-report HTML section + dashboard (ReportSection
  wiring); M4 historical backtest vs buy-and-hold / covered-call / protective-put
  baselines + cost/assignment sensitivity; M5 `ib_async` live chain + IV-rank
  cache. **Earnings feed landed** (polish pass, 2026-06-04): a best-effort
  yfinance next-earnings lookup populates `EventRisk` → audit + ranking
  event-safety; the synthetic-only `MONITOR`→`PROCEED` promotion remains a
  deliberate honesty gate (model data never auto-proceeds).

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
