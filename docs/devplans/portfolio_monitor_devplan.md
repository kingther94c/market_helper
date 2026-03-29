# Portfolio Monitor Devplan

## Current Focus
- Keep the working IBKR report flow stable while moving portfolio monitor logic under `market_helper/domain/portfolio_monitor`.
- Keep `SecurityReferenceTable` and the curated CSV workflow intact, but standardize access through `common/models/security_reference.py` and portfolio-monitor services.
- Continue splitting analytics from rendering so HTML/CSV remain presentation-only entrypoints.

## Near-Term Next Steps
1. Move more of `reporting/risk_html.py` internals out of the legacy module into portfolio-monitor services.
2. Promote `PortfolioSnapshot` from a lightweight compatibility model into the main output of report/risk pipelines.
3. Add more explicit bucket/exposure/risk decomposition tests under `tests/unit/domain/portfolio_monitor/`.
