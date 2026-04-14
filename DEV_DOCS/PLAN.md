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
- Full interactive frontend app in this phase.

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

## In Progress
- Tightening the live TWS / `ib_async` report path with better account/session ergonomics, broader contract coverage, and richer real-world fixture coverage.
- Hardening the universe-first risk workflow with cached proxy ingestion, more robust derivatives treatment, deeper attribution math, and tighter alignment between target-report semantics and the HTML/notebook summaries.
- Tightening the new combined `Performance + Risk` report so the current static HTML can evolve toward a fuller UI/workbook replacement without reintroducing workbook runtime dependencies.

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
- Extend the new Flex XML parse/map flow to direct Flex Web Service fetch using query-id/token and asynchronous statement download polling.
- Build broker-agnostic business services (portfolio/quote/allocation/risk/monitor).
- Build HTML monitor rendering and snapshot tests.
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

## Known Limitations (Regime v1)
- Inputs currently rely on local JSON artifacts; direct FRED pull-through adapters are not yet wired into the regime service.
- Threshold defaults are practical heuristics and require calibration/validation across longer history.
- Backtest scaffold uses simple periodic target application and does not model execution costs/slippage/futures carry.
- Risk report regime integration is intentionally lightweight (banner + scores), without regime-conditioned covariance modeling yet.

## Next Suggested PRs (Regime Track)
1. Add explicit FRED adapter wiring + cached ingestion path for VIX-like, MOVE-like, HY OAS, and Treasury yield series.
2. Add calibration notebook/tests for threshold sensitivity and persistence settings by market episode.
3. Extend policy schema with DM_EQ/EM_EQ split and defensive bucket sub-allocation overlays.
4. Expand backtest scaffold into scenario validation with walk-forward windows and robustness checks.
5. Add report panels for regime transition history and drawdown behavior by regime segment.
