# Portfolio Monitor Devplan

## Current Focus
- Keep the new universe-first IBKR report flow stable while continuing to consolidate portfolio-monitor logic under `market_helper/domain/portfolio_monitor`.
- Treat `configs/security_universe.csv` as the manual semantic source of truth and keep `configs/portfolio_monitor/security_reference.csv` as the generated/cacheable lookup artifact exposed through `common/models/security_reference.py` and portfolio-monitor services.
- Continue splitting analytics from rendering so generated reference, position CSV, HTML risk report, and any future workbook renderer stay composable entrypoints.

## Near-Term Next Steps
1. Add cached proxy/return loaders and wire them into the universe-first risk flow so Yahoo/proxy retrieval is reproducible and not purely on-demand.
2. Extend the risk layer from summary vol contributions into covariance-consistent marginal/component attribution for securities and bucket rollups.
3. Improve universe gap handling with a local manual-override layer plus broader look-through/rule coverage for equities and futures.
4. Continue moving reusable risk/report helpers out of `reporting/risk_html.py` into portfolio-monitor services as the workbook path becomes clearer.
