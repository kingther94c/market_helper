# PLAN

## PR Non-Negotiable
**Every PR must update `DEV_DOCS/PLAN.md`. Missing that update is a serious PR mistake.**
**During every PR, we must explicitly review what has been completed, reassess whether the current plan is still optimal, tighten or simplify the implementation plan where needed, and refresh the future roadmap before merging.**
**Every PR must also update any relevant file under `DEV_DOCS/docs/devplans/` when scope, status, architecture, or next steps changed.**
**Every PR must sync `env.yml` for new packages, clear notebook outputs before commit, and do a private-info leak check before push.**
**Every PR should recheck whether touched content under `DEV_DOCS/` is still relevant and delete or refresh stale material instead of leaving it behind.**

## Process Rule
**Every PR must update `DEV_DOCS/PLAN.md` to reflect completed work, current status, and next steps.**

## Objective
Build a broker-agnostic, read-only IBKR integration layer for market monitoring and portfolio analytics, with IBKR Client Portal Web API as the primary path and clean extension points for future providers/services. The immediate delivery path is a reliable position-report workflow plus notebook-led live TWS / IB Gateway lookup tooling that can run from normalized snapshots, raw IBKR payloads, and live local TWS / IB Gateway sessions.

## In Scope
- Read-only provider adapters for:
  - Client Portal Web API (primary, custom wrapper)
  - TWS / IB Gateway via `ib_async` (default TWS implementation; only fall back to `ibapi` for confirmed gaps)
  - Flex Web Service (archival/reconciliation)
- Domain normalization before business logic.
- Allocation/risk/reporting services built on broker-agnostic models.
- Static HTML monitor output (non-interactive V1).

## Out of Scope
- Any order placement/cancel/modify capability in V1.
- Raw TWS socket client implementation.
- Full multi-user product frontend or any execution UI.

## Current Review (2026-04-19)
- The portfolio-monitor track is now the strongest and most coherent part of the repo: the live TWS path, Flex ingestion, combined-report pipeline, and NiceGUI dashboard all share the same artifact-driven workflow direction.
- The codebase is materially more advanced than some of the docs imply. In practice the architecture is now `cli -> workflows (compatibility) -> application -> domain -> data_sources/presentation`, with `market_helper/application/portfolio_monitor` acting as the dashboard orchestration seam.
- The main technical debt is not missing features so much as duplicated surfaces: legacy workflow shims, legacy HTML/reporting helpers, and the newer dashboard snapshot path all coexist. That keeps migration safe, but it slows simplification and raises parity risk.
- Testing depth is solid at the unit level, especially around portfolio-monitor services and UI contracts, but the highest-risk edges are still integration-heavy: provider variability, snapshot rendering parity, and artifact/config drift across CLI, scripts, and UI forms.
- The next phase should therefore prioritize consolidation over breadth: finish the rendering-path migration, formalize artifact/config contracts, then widen provider/e2e hardening.

## Completed
- Consolidated developer-facing docs under `DEV_DOCS/`, moving the former top-level `docs/` tree into `DEV_DOCS/docs/`.
- Added a readability pass across core workflow, provider, risk, and security-reference modules with higher-signal docstrings/comments to reduce maintenance friction during the ongoing refactor.
- Began the domain-driven refactor inside the existing top-level package without introducing a `src/` migration, preserving the VS Code notebook workflow.
- Added new package roots: `market_helper/app`, `market_helper/common`, `market_helper/data_sources`, `market_helper/domain`, and `market_helper/presentation`.
- Added compatibility wrappers so legacy `config`, `safety`, `utils`, `workflows`, and CLI entrypoints now resolve through the new domain-driven package structure.
- Added new domain/data-source/presentation package facades for portfolio monitor, regime detection, and integration scaffolding.
- Added `DEV_DOCS/docs/architecture/refactor_migration_map.md` plus module-specific devplans under `DEV_DOCS/docs/devplans/`.
- Added new config directories under `configs/{app,portfolio_monitor,regime_detection,integration}` and switched the default generated security-reference path to `data/artifacts/portfolio_monitor/security_reference.csv`.
- Added new artifact roots under `data/artifacts/{portfolio_monitor,regime_detection,integration}` and updated script defaults toward those paths.
- Added new notebook locations: `notebooks/dev_lab/current.ipynb`, `notebooks/dev_lab/archive/`, `notebooks/portfolio_monitor/`, and `notebooks/regime_detection/`.
- Phase 0 guardrail docs added (`requirements`, `read_only_policy`, `provider_matrix`).
- Foundation utilities/config loading with strict read-only mode validation.
- Domain models added: account/contract/position/quote/allocation/risk/monitor view.
- Provider base protocols and fake provider test seam added.
- Runtime read-only guards added in `safety/read_only_guards.py`.
- Web API skeleton client added with read-only guard checks.
- Web API mapping utilities added for account summary, positions, and quote snapshots.
- Generic retry helper (`with_retry`) added for transient Web API operations.
- Web API session/auth + account-summary/positions/snapshot wrappers added with injectable transport seams.
- Config fields and setup docs added for IBKR username/password vs OAuth consumer-key usage.
- Local position-report CSV path added for normalized snapshots.
- Raw IBKR payload to CSV workflow added, including CLI support for direct report generation from IBKR JSON dumps.
- Live local Client Portal Gateway to CSV workflow added for authenticated read-only IBKR sessions.
- Executable `scripts/run_report.sh` wrapper added for snapshot, raw-IBKR, and live report runs.
- Live report path switched to TWS / IB Gateway via `ib_async`, including a thin adapter and portfolio-to-report mappers.
- Script-level live-account defaults moved to local gitignored config, with explicit `--account` override support.
- Report CSV now includes instrument metadata columns such as `con_id`, `symbol`, `local_symbol`, `exchange`, and `currency`.
- Mock e2e coverage added for the live TWS report path, including futures-shaped rows such as `ZFM6` and `ZNM6` and fixture-based CSV format assertions.
- Added a first-pass HTML risk report workflow that computes per-position historical vol (1M/3M geomean), asset-class proxy estimate vol (VIX/MOVE/GVZ/OVX), historical and estimated correlation matrices, portfolio-level risk, and allocation summary from the generated position CSV plus returns/proxy inputs.
- Implemented deterministic regime detection v1 (`market_helper/regimes`) with explicit factor computation, rulebook hysteresis/persistence, JSON snapshot models, and service orchestration for latest/full-history outputs.
- Added CLI commands `regime-detect` and `regime-report`, plus workflow wrapper and script updates for reproducible local runs.
- Integrated optional regime banner + factor-score display into the HTML risk report (`--regime`), preserving backward compatibility when regime data is absent.
- Added a separate regime policy layer (`market_helper/suggest/regime_policy.py`) mapping regime labels to risk multipliers and target asset-class tilts (suggestion only, no execution).
- Added minimal regime evaluation scaffold (`market_helper/backtest/regime_eval.py`) for basic performance/turnover metrics on regime-conditioned targets.
- Added unit/e2e tests for indicator transforms, rulebook hysteresis/mutual exclusivity, policy mapping, CLI dispatch, and CLI regime output schema.
- Added first-pass IBKR Flex XML performance ingestion (`market_helper.data_sources.ibkr.flex.performance`) to extract daily NAV/cash events plus horizon-level performance, and export a dated performance report CSV (`performance_report_YYYYMMDD.csv`) covering MTD/YTD/1M across MWR/TWR and USD/SGD.
- Added live IBKR Flex Web Service fetching (`SendRequest` / `GetStatement` + polling) so `ibkr-flex-performance-report` and `./scripts/run_report.sh ibkr-flex` can run directly from `IBKR_FLEX_TOKEN` and `IBKR_PERFORMANCE_REPORT_ID`, while still supporting local XML input.
- Added parser + CLI unit coverage for the Flex XML-to-CSV path, including horizon matrix extraction/selection across section versions, env-backed query fetching, and dated report export for downstream HTML migration.
- Added a combined portfolio HTML report that renders `Performance` and `Risk` tabs in one page, with the performance tab driven from `nav_cashflow_history.feather` plus the dated `performance_report_YYYYMMDD.csv` artifact contract.
- Extended portfolio-monitor performance analytics with reusable windowed metrics for `MTD`, `YTD`, trailing `1Y/3Y/5Y`, full-history summaries, yearly summary rows, TWR/MWR reporting, and drawdown/cumulative-performance plot frames for HTML/UI reuse.
- Refactored the HTML risk report into reusable view-model and fragment rendering layers so the existing risk-only report can stay backward compatible while also embedding cleanly inside the new combined report shell.
- Added a new `combined-html-report` CLI/workflow entrypoint plus script support for `combined-html` and `ibkr-live-combined-html`, and switched `./scripts/run_report.sh risk-html` and `./scripts/run_report.sh ibkr-live-html` to generate the combined report by default.
- Replaced `performance_history.feather` with a richer `nav_cashflow_history.feather` store built by `market_helper/domain/portfolio_monitor/services/nav_cashflow_history.py`, capturing daily NAV snapshots and classified deposit/withdrawal cashflows from Flex XML so money-weighted returns and cashflow attribution can be computed accurately.
- Overhauled `performance_html.py` and `performance_analytics.py` to render separate USD and SGD currency tabs, each with a cumulative-return chart, drawdown chart, trailing-window metrics (MTD/YTD/1Y/3Y/5Y, TWR/MWR, annualized vol, Sharpe, max drawdown), and historical-year summary rows.
- Fixed Flex cashflow date extraction to use the statement `reportDate` field rather than `settleDate` so cashflow records are attributed to the correct accounting period.
- Added a NiceGUI-backed live dashboard (`market_helper/presentation/dashboard/`) served at `/portfolio` with a `scripts/launch_ui.sh` launcher that probes TCP readiness before browser auto-open and fails fast if the server process dies.

- Added example configs: `configs/regime_detection/regime_config.example.yml` and `configs/regime_detection/regime_policy.example.yml`.
- Added a workbook-to-JSON mapping-table extraction path so stable portfolio metadata can be seeded from `target_report.xlsx` without making the HTML report depend directly on the workbook at runtime.
- Replaced the old in-memory / workbook-JSON mapping split with a generated wide `data/artifacts/portfolio_monitor/security_reference.csv` cache covering `ETF`, `EQ`, `FX_FUT`, `FI_FUT`, `OTHER_FUT`, and `CASH`.
- Reworked `market_helper/portfolio/security_reference.py` around CSV loading, provider indexes, and runtime `UNMAPPED` / `OUTSIDE_SCOPE` fallbacks while keeping compatibility helpers for existing report code.
- Updated IBKR normalization to resolve positions against the curated universe first (exact `conId`, then alias/family lookup, then cash), with futures canonicalized at family level rather than expiry-contract level.
- Moved the HTML risk report off workbook-derived runtime JSON so category/display/duration/expected-vol enrichment now comes from curated security reference rows.
- Downgraded workbook extraction into a bootstrap importer that exports a security-reference CSV seed instead of a runtime JSON mapping table.
- Promoted `configs/security_universe.csv` to the single manually maintained instrument source of truth and turned `data/artifacts/portfolio_monitor/security_reference.csv` into a generated materialized lookup table rebuilt from universe rows plus cached/live IBKR metadata.
- Replaced the old report/risk semantics (`report_category`, `risk_bucket`, `default_expected_vol`, provider-hint columns) with universe-native fields centered on `asset_class`, `eq_country`, `eq_sector`, `dir_exposure`, `fi_mod_duration`, and `fi_tenor`.
- Added universe-first generation/sync services, a dedicated `security-reference-sync` CLI path, and a `security_universe_PROPOSED.csv` review flow for unmapped runtime instruments.
- Updated raw IBKR JSON and live TWS report workflows so they rebuild the generated security reference first, preserve universe-stable `internal_id`s, and refresh runtime lookup fields without letting primary-exchange resolution destabilize IDs.
- Added explicit SMART-vs-primary-exchange alias handling so mapped equities such as `SPY` remain keyed as `STK:SPY:SMART` while still absorbing live `ARCA` contract details.
- Rebuilt the HTML risk workflow around universe-first semantics, with Yahoo-backed returns generation by default, asset-class summaries, EQ country look-through, US sector look-through, FI tenor breakdowns, and selectable vol/correlation modes.
- Added a reusable portfolio-monitor risk utility layer under `market_helper/domain/portfolio_monitor/services/`, covering generic realized-vol, EWMA, blend, proxy-vol, fixed-income-vol, and Yahoo return-cache helpers.
- Added dated Yahoo return caching under `data/artifacts/portfolio_monitor/yahoo_returns/`, storing per-symbol log-return series derived from adjusted close so repeated risk runs can reuse history instead of fetching everything on demand.
- Refactored `market_helper/reporting/risk_html.py` to consume the new risk utility services, support both legacy list-style and dated return overrides, and compute aligned correlations from date-indexed return series.
- Hardened Yahoo history retrieval for the risk flow so transient failures such as HTTP `429` now retry with backoff, honor `Retry-After` when present, reuse stale per-symbol cache files when refresh fails, and fall back to proxy-driven risk estimates when no dated return history can be refreshed in the current run.
- Split FI tenor semantics from duration bucketing so `fi_tenor` is now an explicit instrument classification rather than a derived `fi_mod_duration` range; workbook import, generated reference, and report rendering now preserve cases such as `ZT -> 1-3Y`, `ZF -> 3-5Y`, `ZN -> 7-10Y`, `LQD -> 7-10Y`, and `TLT -> 20Y+`.
- Updated FI tenor presentation so the risk report keeps the canonical bucket names while also showing readable labels (`Cash / ultra-short`, `Front end`, `Short belly`, `Belly`, `Long belly`, `Long end`, `Ultra-long`) in the breakdown table.
- Corrected funded-AUM semantics in the portfolio-monitor risk path so the denominator now includes only stock-like and cash exposures (`EQ` / `ETF` / `CASH`) and excludes futures, options, and outside-scope rows.
- Corrected fixed-income proxy-vol fallback semantics so unmapped or temporarily return-less FI rows no longer treat `MOVE` as direct price volatility; instead the report maps proxy yield-vol into price-vol through modified duration, producing realistic fallback vols for instruments such as `ZT`, `ZF`, `ZN`, and `LQD`.
- Cleaned up the HTML risk `Asset Class Summary` rendering so the section has a dedicated renderer, consistent column counts, and exposure-first row ordering rather than reusing the more verbose generic breakdown layout.
- Added FI 10Y-equivalent display normalization inside the HTML risk report: FI dollar-amount views now map raw FI notionals into `10Y-equivalent` exposure using `gross_exposure * mod_duration / FI_10Y_EQ_MOD_DURATION` with a default base duration of `8.0`, configurable from proxy JSON, while leaving volatility, loadings, correlations, and risk-contribution math unchanged.
- Added static look-through configs under `configs/portfolio_monitor/` for coarse equity country expansion and broad-US sector decomposition.
- Refreshed portfolio-monitor and provider tests around the new stable IDs and generated-reference flow, and fixed remaining Python 3.9 compatibility issues (`zip(..., strict=True)` and typing syntax) so the full repo test suite is green again in the active environment.
- Expanded the shared Python environment definitions to include Jupyter notebook support (`ipykernel`, `notebook`, `jupyterlab`) for exploratory work under `notebooks/`.
- Consolidated duplicate Conda environment files into a single repo-level `env.yml`, aligned to the active `py313` notebook stack and explicit `matplotlib` dependency.
- Synced additional top-level `py313` packages back into `env.yml` where they appear intentional and repo-relevant, specifically `pytest` for the test workflow and `yfinance` for notebook/data exploration.
- Added explicit notebook-analysis staples used in local project notebooks to `env.yml`, specifically `numpy` and `pandas`, so exploratory work is reproducible from the shared environment spec.
- Expanded `env.yml` further with common stats / quant-analysis packages (`scipy`, `scikit-learn`, `statsmodels`) so the shared environment covers typical research notebooks without ad hoc local installs.
- Formalized the TWS / IB Gateway path as `ib_async`-first for local live work and removed the unnecessary `ibapi` dependency from IBKR contract lookup.
- Extended `market_helper.providers.tws_ib_async.TwsIbAsyncClient` with primary-exchange-aware contract lookup, plus `search_securities()` for multi-match exploration and fail-fast `lookup_security()` for single-instrument lookups.
- Replaced the old offline/demo `derive_sec_table` notebook flow with a live, `market_helper`-only IBKR contract lookup notebook that pulls real raw contract details from local TWS / IB Gateway.
- Expanded TWS provider tests to cover `ib_async` contract construction, `primaryExchange` propagation, and explicit no-match / ambiguous-match lookup failures.
- Updated README and provider docs so the documented TWS strategy now matches the code: `ib_async` is the default TWS stack and the live notebook is part of the supported local workflow.
- Unit tests added and expanded across config, domain, providers, portfolio normalization, reporting, workflows, and read-only guard behavior.
- Hardened volatility pipeline in `reporting/risk_html.py`: `_security_vol` now emits a WARNING whenever it falls back to the proxy-vol branch (ticker, asset class, method, reason logged).
- Switched historical inter-asset correlation to use per-asset-class proxy tickers (`ACWI/AGG/GLD`) via `_load_asset_class_proxy_returns`; asset classes with no proxy (MACRO, CASH) are forced to 0 corr with others.
- Exposed `inter_asset_corr` end-to-end (contracts → services → workflows → pipelines → CLI → NiceGUI dashboard toggle) so users can compare portfolio vol under `historical / corr_0 / corr_1`.
- Added a new forward-looking vol method `_adjusted_proxy_security_vol`: `fwd(asset) = realized_5Y(asset) / realized_5Y(proxy) × simple_proxy_level`. The simple proxy-vol calc (`_proxy_fallback_security_vol`) is preserved as the last-resort fallback. Exposed via the `vol_method="forward_looking"` option in the dashboard, CLI, and risk HTML summary card.
- Started the dashboard refactor toward a unified current-state risk monitor: added a configurable label→key mapping for vol methods (`vol_method_labels` in `report_config.yaml`) with defaults `Long-Term → 5y_realized`, `Fast → geomean_1m_3m`, `Forward-Looking → forward_looking`; added `resolve_vol_method_key()` helper in `reporting/risk_html.py` that accepts either label or internal key so downstream pipelines can stay on internal keys. Also added `fx_excluded_asset_classes` config for the upcoming `FX excluded` portfolio-vol note.
- Added an in-process, date-keyed session cache for Yahoo return series in `domain/portfolio_monitor/services/yahoo_returns.py` so repeated risk-report refreshes within the same dashboard session (and same calendar day) skip both disk reads and network fetches for already-loaded symbols. Exposes `clear_session_yahoo_cache()` for tests / forced refresh.
- Renamed the NiceGUI dashboard vol-method selector to surface the human-readable labels (`Long-Term / Fast / Forward-Looking`) with `Fast` as the default; the dashboard now passes the selected label straight through to the risk view-model builder, which resolves it via the configurable mapping.
- Restructured the NiceGUI Risk tab into a **Main Overview + 5 detail sub-tabs** layout (`Equity`, `Fixed Income`, `Commodity`, `FX`, `Macro`) per the v1 Risk Dashboard spec. Main Overview now groups Portfolio Summary (with `FX excluded` note and Long-Term / Fast / Forward-Looking vol hero cards), Asset Class Summary (renamed columns: `Net Exposure ($)`, `Portfolio Allocation %`, `Vol Contribution %`), and an allocation-only Portfolio Drift chart/table. Detail tabs reuse existing view-model data: Equity surfaces country + US sector breakdowns plus EQ-filtered holdings; Fixed Income adds summary cards (total FI net exposure, weighted-avg duration, position count) above the existing FI tenor bucket table and FI-filtered instruments; FX/Macro are filtered-row views (FX with `Vol Contribution %` omitted per spec).
- Added a lightweight Commodity Sector Summary table in the Commodity detail tab, aggregating CM positions by `cm_sector` (PM / IM / EN / AG) loaded directly from `configs/security_universe.csv`. Full propagation of `cm_sector` through `SecurityReference` is still deferred to a future change.
- Added a Commodity cross-sector correlation heatmap (Plotly `RdBu`, `-1..1`) in the Commodity detail tab, computed from `commodity_sector_proxies` (config: `PM=GLD, IM=DBB, EN=USO, AG=DBA`) and `commodity_sector_correlation_lookback_days` via the existing session-cached Yahoo returns.
- Added an Equity DM/EM summary block to the Equity detail tab with a small table plus two 100% stacked bars (portfolio vs policy), deriving DM/EM classification from `configs/portfolio_monitor/eq_country_lookthrough.csv`.
- Landed Phase A of the Playwright snapshot retirement plan: added `snapshot_mode` to `PortfolioPageState`, a `?snapshot=1` query-param flag on `@ui.page("/portfolio")` that hides the Actions console, Run History, and artifact toolbar, and a `#snapshot-ready` sentinel element emitted after the snapshot finishes loading. Added a skeleton `market_helper/presentation/dashboard/snapshot.py` module that launches the NiceGUI dashboard in-process, drives it with Playwright (`async_playwright`), waits for the sentinel, and writes the captured HTML to disk. Playwright is not yet installed into the env.
- Propagated `cm_sector` through the security-reference layer: added an optional `cm_sector` column to `SECURITY_UNIVERSE_HEADERS` / `SECURITY_REFERENCE_HEADERS` with schema-detection tolerance for legacy CSVs that pre-date the column; wired it through `SecurityUniverseRow` / `SecurityReference` / `RiskInputRow` / `RiskMetricsRow` and the `load_position_rows` parser. The Commodity detail tab now reads `cm_sector` off the risk row directly, and the `@lru_cache`-backed `_load_cm_sector_map` CSV side-channel and `import csv` cleanup workaround have been removed from `presentation/dashboard/pages/portfolio.py`.
- Landed Phase B-1 of the Playwright snapshot pipeline: `playwright>=1.48` is in `env.yml`, `scripts/setup_python_env.sh` runs `python -m playwright install chromium` after env creation, and `capture_snapshot()` now smoke-passes end-to-end — launches NiceGUI on an ephemeral port, navigates to `/portfolio?snapshot=1`, waits for `#snapshot-ready` (switched to `state="attached"` since NiceGUI renders sentinel `ui.html` nodes as display:none), and writes the HTML to disk. Sentinel fires in snapshot mode regardless of whether a positions CSV is available (`data-has-snapshot="0"` vs `"1"`) so the Playwright wait is deterministic. Asset inlining is not yet done — the captured HTML still references `/_nicegui/...` URLs and requires a running NiceGUI server to fully render.
- Landed Phase B-2 of the Playwright snapshot pipeline via an **ossify-and-strip** strategy. `snapshot.py` now: captures every `/_nicegui/...` response during navigation via `page.on("response")`, strips all `<script>` tags (the DOM is already hydrated by Playwright before capture), inlines captured stylesheets as prepended `<style>` blocks, rewrites `url(/_nicegui/...)` references inside existing/inlined CSS to `data:` URIs (fonts included), converts captured favicon/icon references to `data:` URIs, and drops `<link rel="modulepreload">` / `<link rel="preload">` hints. The output is intentionally non-interactive: no JS runs when the snapshot is viewed offline, so Plotly charts / Quasar styling / tables are all baked into the DOM at capture time. Smoke verified end-to-end in `offline=True` Playwright context — no page errors, no failed network requests, styling preserved (gradient header, tabs with active underline, card shadows).
- Fixed a dashboard tab-persistence bug: toggling Percent/Dollar (or MTD/YTD/1Y/Full) on the Performance SGD tab snapped the view back to Performance USD, because the perf toggles trigger a full `@ui.refreshable` rebuild that re-created `ui.tab_panels` with the page-load default. The top-level `ui.tabs` now binds its value into `state.selected_top_tab` via `on_change`, so refreshes respect whichever tab the user is on.
- Fixed a live-TWS portfolio bug that caused `live_ibkr_position_report.csv` to drop every non-cash position, leaving the risk dashboard showing just the converted-SGD cash row. Root cause: `ib_async`'s `wrapper.portfolio[account]` dict is only populated by `reqAccountUpdates` (the single-account subscription), not by `reqAccountUpdatesMulti`. The startup `reqAccountUpdates` call in `IB.connectAsync` is skipped when no `account` is passed to `connect()` and more than one managed account is returned, and when it does run it is wrapped in `asyncio.wait_for(..., timeout)` with `raiseSyncErrors=False`, so a short `connect()` timeout silently leaves `wrapper.portfolio` empty. `ib.portfolio(account)` then returns `[]` while `ib.accountValues(account)` still returns the cash tags populated by `reqAccountUpdatesMulti`. `TwsIbAsyncClient.list_portfolio` now reads `ib.portfolio(account)` first, and only if the result is empty does it force a fresh subscription (unsubscribe via `client.reqAccountUpdates(False, account)` then re-subscribe via `reqAccountUpdatesAsync(account)` under `ib.run(..., timeout=30.0)`). Using the bounded async path matters because the blocking `ib.reqAccountUpdates` hangs forever when the subscription is already active — TWS does not re-send `accountDownloadEnd`, so the future never completes. Tests cover both the happy path (no re-subscribe when portfolio is populated) and the empty-portfolio path (unsubscribe + re-subscribe refills portfolio).
- Landed Phase C-risk of the Playwright snapshot pipeline: rewired the `risk-html-report` CLI to `generate_risk_snapshot_report`, which drives `/portfolio?snapshot=1&tab=risk` via `capture_snapshot()` instead of the legacy Jinja renderer. The dashboard page now accepts a `tab=` query arg (resolves to one of `performance_usd | performance_sgd | risk | artifacts`, with aliases for `perf`, `usd`, `sgd`), auto-loads the snapshot when `snapshot_mode=True` and the positions CSV exists, and honors a module-level `set_snapshot_overrides()` dict so the CLI can inject artifact paths + vol/correlation selections without query-string plumbing. `SnapshotRequest` gained an `overrides: Mapping[str, str] | None` field; `_start_dashboard()` calls `set_snapshot_overrides()` before `ui.run`. Also fixed a pre-existing broken import in `portfolio.py` (`market_helper.data_sources.yahoo` → `market_helper.data_sources.yahoo_finance`) surfaced by the first end-to-end snapshot smoke against `tests/e2e/fixtures/live_ibkr_position_report_mock.csv`. Smoke: 498 KB self-contained HTML, `data-has-snapshot="1"`, Portfolio Summary / Asset Class Summary / Vol Contribution content all populated. Migrated the CLI dispatch test to target `generate_risk_snapshot_report`; full `tests/unit` suite (233 tests) passes. Legacy `generate_risk_html_report` workflow + pipeline remain exported for parallel audits before D deletes them.

## In Progress
- Tightening the live TWS / `ib_async` report path with better account/session ergonomics, broader contract coverage, and richer real-world fixture coverage.
- Hardening the universe-first risk workflow with cached proxy ingestion, more robust derivatives treatment, deeper attribution math, and tighter alignment between target-report semantics and the HTML/notebook summaries.
- Tightening the new combined `Performance + Risk` report so the current static HTML can evolve toward a fuller UI/workbook replacement without reintroducing workbook runtime dependencies.
- Retiring the bespoke HTML risk renderer in `reporting/risk_html.py` in favor of a **headless UI snapshot** of the NiceGUI dashboard (Playwright). Phases A + B-1 + B-2 + C-risk landed: `?snapshot=1&tab=risk` URL flag, `#snapshot-ready` sentinel, Playwright in `env.yml` / `setup_python_env.sh`, ossify-and-strip self-contained HTML, and the `risk-html-report` CLI now drives `capture_snapshot()` via `generate_risk_snapshot_report` using module-level snapshot overrides. Remaining work: **perf-parity** (add cumulative/drawdown Plotly charts to the NiceGUI Performance USD/SGD tabs so snapshotting reaches parity with `render_performance_tab()`); **c-combined** (rewire `combined-html-report` after perf parity); (d) delete the `render_html` / `render_risk_tab` / `_render_*` template code in `risk_html.py` (keeping the view-model builders intact), the thin re-export shim in `market_helper/presentation/html/portfolio_risk_report.py`, and the HTML half of `market_helper/reporting/combined_html.py`; (e) replace the HTML-string assertions in `tests/unit/reporting/test_risk_html.py` with view-model-level assertions.
- Risk Dashboard v1 MVP polish is complete. Follow-ons still open are the Playwright snapshot Phases B/C/D above and deepening risk attribution (see Next Steps).

## Next Steps
1. Add cached loaders for benchmark proxies and wire them into the same reproducible artifact flow now used for Yahoo return histories.
2. Extend the performance tab beyond the current standard report with richer windows/benchmarks only after the core combined layout is stable.
3. Extend risk attribution from the current vol-contribution view to covariance-consistent marginal/component risk attribution at both security and bucket levels.
4. Improve derivatives handling, especially options / `OUTSIDE_SCOPE` rows, inverse products, and futures-specific exposure normalization.
5. Add a local manual-override layer for provisional or account-specific universe entries that should not be committed until reviewed.
6. Broaden look-through coverage for country/sector decomposition and continue expanding explicit FI tenor mappings where product semantics do not align with simple duration ranges.
7. Add richer account-selection ergonomics and account/session metadata surfacing for live TWS / IB Gateway runs.
8. Add more real IBKR payload fixtures and live-contract edge cases to harden normalization compatibility.
9. Keep evolving the combined HTML/workbook layer toward the target portfolio view without coupling runtime rendering to `data/artifacts/portfolio_monitor/target_report.xlsx`.
10. Optionally add a broader Client Portal Web API wrapper layer if we need more endpoints beyond position reporting.

## Instrument Mapping Plan
- Treat `configs/security_universe.csv` as the manual semantic source of truth and `data/artifacts/portfolio_monitor/security_reference.csv` as a generated/cacheable materialized view rather than as the business-authoritative mapping file.
- Keep `internal_id` as a system-owned canonical key; do not let Yahoo, Bloomberg, Google, or IBKR identifiers become the system primary key.
- Treat ETF and stock mappings as mostly direct instrument aliases, but treat futures, options, and other derivatives as two-layer mappings: product family first, concrete contract second.
- Use strong provider-native IDs when available, especially IBKR `conId`, and store weaker vendor tickers as aliases rather than as the canonical identity.
- For derivatives, normalize and persist fields such as root symbol, local symbol, expiry, exchange, currency, multiplier, and other contract metadata needed to reconcile vendor naming differences.
- Store common cross-vendor futures symbology knowledge, such as IBKR-vs-Bloomberg root-symbol differences, in tracked rules rather than one-off code branches.
- Keep local, provisional, or account-specific mapping exceptions in gitignored override files until they are verified and worth promoting into tracked shared rules.

## Target Report Gap
- Current runtime output is still split between a normalized position CSV and a separate HTML risk report, while `data/artifacts/portfolio_monitor/target_report.xlsx` remains a structured workbook with at least two sheets: `Position` and `Risk`.
- Current runtime output now includes a combined static HTML artifact with `Performance` and `Risk` tabs, but it still remains separate from the target workbook layout and formatting model.
- We should treat the workbook as a source for seed mappings and reporting assumptions, not as a runtime dependency for the HTML report.
- The new universe-first stack now computes asset-class summaries plus EQ country, US sector, and FI tenor breakdowns, but it still does not render the workbook-style `Position` and `Risk` sheets as a single formatted artifact.
- The `Position` sheet still includes presentation-oriented sections and summaries that we do not compute yet in workbook form, including target-style bucket subtotal layouts and final display conventions for every instrument family, even though funded-AUM semantics are now aligned more closely with the intended "funded capital" denominator.
- The current risk output now has signed exposure handling, explicit tenor/country/sector semantics, readable FI tenor labels, and selectable vol/correlation modes, but it still lacks full target-style covariance attribution, workbook formatting, and some derivatives-specific exposure treatments.
- FI dollar views in the HTML report now use a hybrid display basis where fixed-income rows are shown in 10Y-equivalent notional and non-FI rows remain in raw dollars; this improves cross-tenor readability but is still a presentation/reporting layer rather than a full cross-asset normalization framework.
- The risk flow is now materially more robust under Yahoo throttling because it can reuse cached return history or fall back to proxy vols instead of aborting the whole report, but proxy inputs themselves are still file-based and not yet ingested through a dedicated cached benchmark-data pipeline.
- The `Risk` sheet in the target workbook still introduces an additional analytics layer we only partially cover today: richer regime panels, benchmark proxy history presentation, and portfolio risk-attribution summaries under multiple explicit scenario assumptions.
- The target workbook is not just a data export; it is a formatted report artifact with multiple sections, derived metrics, and workbook-level layout concerns. We therefore need an explicit workbook-rendering layer instead of treating the current CSV as the final output format.
- A practical delivery sequence is: stabilize instrument mapping and exposure normalization first, add bucket/risk calculations second, then implement workbook generation and formatting last.

## Backlog / Future Phases
- Extend the TWS `ib_async` adapter surface beyond the current client/portfolio/report/contract-lookup coverage, especially market-data and richer account/session tooling.
- Deepen the Flex path around historical backfill ergonomics, archive validation, and surfaced statement/account metadata.
- Continue shrinking compatibility shims as stable application/domain ownership becomes clearer.
- Finish dashboard snapshot parity for all report surfaces and retire the remaining legacy HTML-only rendering path.
- Add e2e workflow coverage across Web API, TWS, and Flex.

## Risks / Blockers / Assumptions
- IBKR payload/field variability (especially market-data field codes) requires robust fixtures.
- Session/auth behavior may vary by account configuration and runtime environment.
- Existing legacy modules and new provider layer will coexist temporarily during migration.
- Read-only policy must remain explicit in config + runtime guards to avoid accidental drift.
- Initial report output favors correctness and inspectability over presentation polish.

## Testing Status
- Full repo test suite passes in the active local environment: `PYTHONPATH=. PYTHONPYCACHEPREFIX=/tmp/pycache pytest -q`
- The universe-first portfolio-monitor refactor is covered by targeted report/risk/provider tests, including raw IBKR normalization, live TWS report generation, generated security-reference sync, mapping-table import, generic volatility/proxy/fixed-income helpers, Yahoo return-cache loading, and risk HTML rendering.
- Live smoke validation succeeded against local TWS / IB Gateway for `XLK` contract lookup through `market_helper.providers.tws_ib_async`, and the `derive_sec_table` notebook cells executed successfully end to end from `notebooks/portfolio_monitor`.

## Notes
- Execution/trading support remains intentionally unimplemented.
- Plan remains incremental; unrelated repo areas were not refactored.

## Next Suggested PRs (Core / Portfolio Monitor)
1. Finish rendering-path consolidation.
   Move `combined-html-report` fully onto the dashboard snapshot path after performance-tab parity is complete, then start deleting legacy HTML-only rendering code that no longer owns unique behavior.
2. Introduce explicit artifact/config contracts.
   Replace the current spread of path-string plumbing across CLI args, workflow kwargs, dashboard form state, and snapshot overrides with typed request objects or manifest-style config resolution shared by CLI, scripts, and UI.
3. Tighten the application-layer boundary.
   Keep dashboard pages thin by moving more input normalization, action status assembly, and artifact discovery into `market_helper/application/portfolio_monitor`, making it the single orchestration seam for UI-triggered work.
4. Expand high-value integration coverage.
   Add end-to-end tests around snapshot capture, combined-report generation, and failure-path handling for missing/stale artifacts so the next round of cleanup can delete shims with confidence.
5. Improve security-universe and override workflows.
   Add a clearer manual-override/review path for provisional mappings and broaden explicit instrument semantics (`instrument_kind`, ETF detection, derivatives handling, FI tenor exceptions) before pushing further into workbook-style reporting.

## Known Limitations (Regime v1)
- Inputs currently rely on local JSON artifacts; direct FRED pull-through adapters are not yet wired into the regime service.
- Threshold defaults are practical heuristics and require calibration/validation across longer history.
- Backtest scaffold uses simple periodic target application and does not model execution costs/slippage/futures carry.
- Risk report regime integration is intentionally lightweight (banner + scores), without regime-conditioned covariance modeling yet.

## Regime v2 — Multi-Method 2D Framework (In Progress)
Redesigns regime detection around a pluggable multi-method architecture that classifies each date into a 2D `(growth × inflation)` quadrant — Goldilocks, Reflation, Stagflation, Deflationary Slowdown — with an orthogonal crisis overlay flag, and lets methods vote through an ensemble layer. v1 ships two methods (macro rule-based + existing legacy 7-regime wrapper); ML and market-voting methods are designed-in but deferred.

### Completed
- **M1 FRED macro panel pipeline**: `market_helper/data_sources/fred/macro_panel.py` with per-series feather caches, publication-lag-aware forward-fill, `configs/regime_detection/fred_series.example.yml`, `scripts/run_fred_sync.sh`, and the `fred-macro-sync` CLI subcommand.
- **M2 2D axis engine + macro_rules method**: `market_helper/regimes/axes.py` (quadrant constants, `GrowthInflationAxes`, `QuadrantSnapshot`, sign hysteresis, duration, quadrant mapping) and `market_helper/regimes/methods/macro_rules.py` (rolling z-score per series, per-axis weighted aggregation, hysteresis).
- **M3 Legacy wrapper + ensemble**: `market_helper/regimes/methods/legacy_rulebook.py` projects each of the 7 legacy regimes onto the 4 quadrants plus a crisis flag; `market_helper/regimes/ensemble.py` aligns method results by common dates, confidence-weighted per-axis voting, OR'd crisis flag with max intensity, reports method agreement.
- **M4 Quadrant policy + orchestration + serialization**: `market_helper/suggest/quadrant_policy.py` (4-quadrant policy table + crisis overlay that redistributes `equity_shift_pct * intensity` of EQ to CASH/GOLD/FI and reduces vol multiplier), `configs/regime_detection/quadrant_policy.example.yml`, `MultiMethodRegimeSnapshot` dataclass with JSON roundtrip, and `market_helper/regimes/multi_method_service.py` orchestrator.
- **M5 CLI wire-up**: `regime-detect-multi` subcommand runs enabled methods and writes the ensemble snapshot array; `regime-report-multi` prints ensemble quadrant, per-method verdicts, method agreement, crisis state, and the resolved quadrant policy decision. Legacy `regime-detect` / `regime-report` commands remain untouched for back-compat.

### Outstanding
- HTML risk-report banner (`market_helper/reporting/risk_html.py`) and NiceGUI dashboard still consume the legacy `RegimeSnapshot` JSON. Next PR should teach both surfaces to auto-detect a multi-method payload and render the ensemble quadrant as the primary banner with a collapsible per-method detail row.
- Regime v2 schema is covered by unit tests (`tests/unit/regimes/test_axes_quadrant.py`, `test_macro_rules.py`, `test_ensemble.py`, `test_legacy_wrapper.py`, `test_quadrant_policy.py`, `test_multi_method_service.py`) and a CLI e2e (`tests/e2e/test_cli_regime_detect_multi.py`). No manual 15-year backtest sanity check has been run yet (GFC / COVID / 2022 inflation) — to be done once the FRED panel is actually synced on a host with a `FRED_API_KEY`.
- Known design risks still open: macro series reliance on revised values (no ALFRED vintages — we use `publication_lag_days` per series as a pragmatic proxy); z-score saturation on long-trending inflation series (capped at ±3 by default but worth revisiting); ensemble crisis double-counting is avoided by not applying the quadrant-policy overlay on top of the legacy method's native 7-regime policy.

### Next Suggested PRs (Regime v2)
1. **HTML + dashboard banner migration** — detect `version="regime-multi-v1"` and render ensemble quadrant + method-agreement chip in the risk report and NiceGUI home.
2. **Market-voting method** — add a third method driven by multi-asset trend rules (bond↑/stock↑ → inflation↓, copper↑ → growth+inflation, etc.) to diversify the ensemble beyond the current two methods.
3. **ML method skeleton** — supervised classifier + unsupervised clustering drop-in under `market_helper/regimes/methods/` conforming to the `RegimeMethod` protocol.
4. **Backtest sanity harness** — rerun the 15-year window and validate against GFC, COVID, 2017 Goldilocks, 2022 Reflation/Stagflation turn; commit fixture snapshots.
5. **Calibration notebook** — walk-forward tuning of `zscore_window_bdays`, `min_consecutive_days`, and crisis-overlay magnitudes against out-of-sample periods.

## Next Suggested PRs (Regime v1, legacy track)
1. Add explicit FRED adapter wiring + cached ingestion path for VIX-like, MOVE-like, HY OAS, and Treasury yield series.
2. Add calibration notebook/tests for threshold sensitivity and persistence settings by market episode.
3. Extend policy schema with DM_EQ/EM_EQ split and defensive bucket sub-allocation overlays.
4. Expand backtest scaffold into scenario validation with walk-forward windows and robustness checks.
5. Add report panels for regime transition history and drawdown behavior by regime segment.
