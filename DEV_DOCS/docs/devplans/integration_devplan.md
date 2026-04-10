# Integration Devplan

## Current Focus
- Establish read-only scaffolding for portfolio/regime integration under `market_helper/domain/integration`.
- Keep this layer intentionally lightweight until portfolio and regime contracts stabilize.

## Near-Term Next Steps
1. Define the first concrete scenario/stress-test input contract using `RecommendationOutput` and `PortfolioSnapshot`.
2. Add tests for mapper/stress/recommendation scaffolds so future implementation can evolve safely.
3. Introduce a first combined report presentation layer once portfolio and regime outputs stop moving.
