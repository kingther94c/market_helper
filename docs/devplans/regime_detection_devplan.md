# Regime Detection Devplan

## Current Focus
- Keep deterministic regime v1 behavior stable while regrouping code under `market_helper/domain/regime_detection`.
- Preserve the current processed-JSON workflow as the main runnable path.
- Introduce explicit `fred` and `yahoo_finance` source locations without forcing online retrieval into this refactor.

## Near-Term Next Steps
1. Wire `data_sources/fred/client.py` into a cached ingestion workflow.
2. Add a concrete Yahoo Finance retrieval adapter behind the current scaffold.
3. Expand dashboard and backtest outputs into dedicated presentation/domain artifacts.
