# DEVPLAN — Portfolio Monitor Track

## Mission
Build a reliable portfolio-monitor pipeline:
IBKR data ingestion -> normalized/enriched security reference -> portfolio risk/allocation reporting.

## Scope
- Provider ingestion for read-only IBKR account and position data.
- Security reference enrichment and mapping quality controls.
- Portfolio report outputs for allocation and risk diagnostics.

## Completed baseline
- IBKR live/report workflows and CSV outputs are in place.
- Security reference table migrated to curated CSV source-of-truth.
- HTML risk report path exists and can optionally include regime context.

## Current priorities
1. Finalize enriched security-reference output contract (fields + quality flags).
2. Improve derivatives and cash treatment in exposure/risk aggregation.
3. Add provider-hint-driven market/FX fetch interfaces tied to security-reference rows.
4. Stabilize report schema for downstream regime-integration/stress modules.
5. Extract reused pure helpers to `market_helper/utils` while keeping portfolio semantics in-module.

## Exit criteria
- Stable portfolio output schema with versioned fields.
- Mapping gaps are explicit (`UNMAPPED` / `OUTSIDE_SCOPE`) and actionable.
- Portfolio report can be consumed directly by integration stress-test workflows.
