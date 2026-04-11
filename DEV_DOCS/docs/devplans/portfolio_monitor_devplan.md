# Portfolio Monitor Devplan

## Current Focus
- Keep the new universe-first IBKR report flow stable while continuing to consolidate portfolio-monitor logic under `market_helper/domain/portfolio_monitor`.
- Treat `configs/security_universe.csv` as the manual semantic source of truth and keep `data/artifacts/portfolio_monitor/security_reference.csv` as the generated local lookup cache exposed through `common/models/security_reference.py` and portfolio-monitor services.
- Treat `configs/portfolio_monitor/report_config.yaml` as the canonical tracked runtime entrypoint for risk-report lookthrough, proxy, and policy settings.
- Treat `configs/portfolio_monitor/local.env` as the canonical gitignored local-only config for account defaults and provider secrets.
- Treat `configs/portfolio_monitor/us_sector_lookthrough.json` as the canonical ETF sector lookthrough store, including per-symbol timestamps and shared API-usage metadata, rather than extending the older CSV as the primary source.
- Treat `fi_tenor` as an explicit instrument-semantic field rather than as a derived duration bucket, while keeping `fi_mod_duration` available as a separate analytics/display attribute.
- Keep funded-AUM calculations aligned with report intent by counting only stock-like and cash exposures, not futures/options notionals.
- Continue splitting analytics from rendering so generated reference, position CSV, HTML risk report, and any future workbook renderer stay composable entrypoints.
- Treat the combined portfolio HTML report as the new default static-report surface, with `Performance` and `Risk` tabs sharing reusable rendering primitives rather than duplicating page-specific logic.
- Keep the new risk utility layer under `market_helper/domain/portfolio_monitor/services/` as the reusable home for realized-vol, proxy-vol, fixed-income-vol, and Yahoo return-cache logic rather than letting that logic drift back into `reporting/risk_html.py`.
- Keep performance analytics under `market_helper/domain/portfolio_monitor/services/` reusable enough for future UI/workbook renderers, especially window slicing, yearly summaries, TWR/MWR metrics, and plot-frame generation.

## Near-Term Next Steps
1. Deepen the combined report with richer performance analytics only after the current `Performance + Risk` tab shell remains stable through a few real account runs.
2. Replace the current heuristic US-ETF discovery used by report-time sector refresh with an explicit `is_etf` / `instrument_kind` semantic field in the security universe or generated reference cache.
3. Add cached proxy loaders and wire them into the same artifact-driven risk flow now used for dated Yahoo return caches.
4. Extend the risk layer from summary vol contributions into covariance-consistent marginal/component attribution for securities and bucket rollups.
5. Improve universe gap handling with a local manual-override layer plus broader look-through/rule coverage for equities and futures, including explicit tracked FI tenor mappings when product semantics differ from modified-duration ranges.
6. Keep moving reusable risk/report helpers out of `reporting/risk_html.py` as the workbook/UI path becomes clearer, while preserving backward-compatible CLI/report entrypoints.

## Recently Completed
- Added a combined static HTML portfolio report with `Performance` and `Risk` tabs, using `USD` as the primary performance view, `SGD` as auxiliary display, and `TWR` as the headline return basis while preserving `MWR` alongside key metrics.
- Added reusable performance-report rendering under `market_helper/reporting/performance_html.py`, covering cumulative-performance and drawdown charts plus `MTD / YTD / 1Y / 3Y / 5Y` and historical-year summary tables.
- Extended `performance_analytics.py` with reusable history-window slicing, yearly summary rows, trailing-window metrics, TWR/MWR calculations, annualized return/vol, Sharpe, and max-drawdown helpers.
- Refactored `risk_html.py` so the existing risk-only report now builds through reusable view-model and fragment layers, enabling the combined report without breaking the existing `build_risk_html_report(...)` API.
- Added `combined-html-report` to the CLI/workflow layer and added `combined-html` plus `ibkr-live-combined-html` to `./scripts/run_report.sh`.
- Switched `./scripts/run_report.sh risk-html` and `./scripts/run_report.sh ibkr-live-html` to generate the combined report by default, while keeping the old names as compatibility-friendly script entrypoints.
- Added a first-pass IBKR Flex XML performance path (`ibkr-flex-performance-report`) that parses downloaded Flex statements into a dated `performance_report_YYYYMMDD.csv` with MTD/YTD/1M, money/time-weighted, USD/SGD, plus dollar-PnL/return columns; this is the CSV contract for the upcoming HTML layer and policy-portfolio overlays.
- Consolidated tracked risk-report config under `configs/portfolio_monitor/report_config.yaml`, including canonical `lookthrough`, `proxy`, and policy sections used by the HTML risk flow.
- Consolidated gitignored local-only settings under `configs/portfolio_monitor/local.env`, including account defaults and `FMP_API_KEY`.
- Added an FMP-backed `etf-sector-sync` workflow plus `market_helper.data_sources.fmp` client support so ETF sector lookthrough can be refreshed through a first-class CLI/script entrypoint.
- Switched canonical US sector lookthrough storage from CSV to `configs/portfolio_monitor/us_sector_lookthrough.json`, including per-symbol `updated_at`, cached normalized sector weights, refresh status, and shared daily API-usage tracking.
- Added automatic ETF sector lookthrough registration/refresh during `risk-html-report`, with new symbols seeded at `2000-01-01`, stale symbols refreshed after 30 days, and refreshes capped by the shared `250` calls/day budget.
- Made US sector expansion prefer canonical ETF lookthrough over single-name `eq_sector` fields, so ETFs like `SOXX`, `QQQ`, `TQQQ`, and `SQQQ` no longer inherit misleading single-sector labels from security metadata.
- Added CLI, workflow, e2e, and reporting regression coverage for the unified local config path, FMP ETF sync flow, JSON lookthrough loading, and report-time refresh behavior.
- Added reusable `volatility.py`, `vol_proxies.py`, `fixed_income_vol.py`, and `yahoo_returns.py` service modules for generic portfolio risk math and dated Yahoo return caching.
- Switched the default no-`--returns` risk path to per-symbol cached Yahoo log-return series built from adjusted close under `data/artifacts/portfolio_monitor/yahoo_returns/`.
- Updated `risk_html.py` to consume the service-layer utilities, align dated return series for correlations, and accept both legacy list-style and dated-object return overrides.
- Hardened Yahoo risk-history retrieval so HTTP `429` / transient failures now retry with backoff, respect `Retry-After`, reuse stale symbol caches when refresh fails, and skip transiently unavailable symbols so the report can still fall back to proxy-risk estimates.
- Corrected fixed-income proxy fallback semantics so `MOVE` is no longer treated as direct FI price volatility; the report now maps proxy yield-vol through `fi_mod_duration`, producing realistic fallback vols for treasury and bond exposures.
- Cleaned up the HTML risk `Asset Class Summary` table with a dedicated renderer and exposure-first ordering so the section no longer inherits the generic breakdown-column mismatch.
- Added report-only FI 10Y-equivalent exposure normalization for HTML dollar views, using `fi_mod_duration / FI_10Y_EQ_MOD_DURATION` with default base duration `8.0` from the unified risk-report config, while keeping volatility and contribution math on the original raw-risk basis.
- Expanded unit coverage for volatility helpers, proxy/fixed-income helpers, Yahoo cache behavior, and risk-report regressions.
