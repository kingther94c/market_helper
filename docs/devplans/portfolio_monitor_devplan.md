# Portfolio Monitor Devplan

## Current Focus
- Keep the new universe-first IBKR report flow stable while continuing to consolidate portfolio-monitor logic under `market_helper/domain/portfolio_monitor`.
- Treat `configs/security_universe.csv` as the manual semantic source of truth and keep `configs/portfolio_monitor/security_reference.csv` as the generated/cacheable lookup artifact exposed through `common/models/security_reference.py` and portfolio-monitor services.
- Treat `fi_tenor` as an explicit instrument-semantic field rather than as a derived duration bucket, while keeping `fi_mod_duration` available as a separate analytics/display attribute.
- Keep funded-AUM calculations aligned with report intent by counting only stock-like and cash exposures, not futures/options notionals.
- Continue splitting analytics from rendering so generated reference, position CSV, HTML risk report, and any future workbook renderer stay composable entrypoints.
- Keep the new risk utility layer under `market_helper/domain/portfolio_monitor/services/` as the reusable home for realized-vol, proxy-vol, fixed-income-vol, and Yahoo return-cache logic rather than letting that logic drift back into `reporting/risk_html.py`.

## Near-Term Next Steps
1. Add cached proxy loaders and wire them into the same artifact-driven risk flow now used for dated Yahoo return caches.
2. Extend the risk layer from summary vol contributions into covariance-consistent marginal/component attribution for securities and bucket rollups.
3. Improve universe gap handling with a local manual-override layer plus broader look-through/rule coverage for equities and futures, including explicit tracked FI tenor mappings when product semantics differ from modified-duration ranges.
4. Keep moving reusable risk/report helpers out of `reporting/risk_html.py` as the workbook path becomes clearer, while preserving backward-compatible CLI/report entrypoints.

## Recently Completed
- Added reusable `volatility.py`, `vol_proxies.py`, `fixed_income_vol.py`, and `yahoo_returns.py` service modules for generic portfolio risk math and dated Yahoo return caching.
- Switched the default no-`--returns` risk path to per-symbol cached Yahoo log-return series built from adjusted close under `data/artifacts/portfolio_monitor/yahoo_returns/`.
- Updated `risk_html.py` to consume the service-layer utilities, align dated return series for correlations, and accept both legacy list-style and dated-object return overrides.
- Expanded unit coverage for volatility helpers, proxy/fixed-income helpers, Yahoo cache behavior, and risk-report regressions.
