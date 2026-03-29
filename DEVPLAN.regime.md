# DEVPLAN — Regime Detection Track

## Mission
Deliver a policy-first regime engine:
market/macro data ingestion -> deterministic regime detection -> dashboard + allocation-tilt guidance.

## Scope
- Ingest market + macro proxies (Yahoo/FRED adapters as canonical input layer).
- Compute indicators and classify market regime with explicit rulebook behavior.
- Provide regime dashboard outputs and policy-based asset-class tilt suggestions.

## Completed baseline
- Deterministic regime v1 and CLI workflows are implemented.
- Policy mapping and initial regime evaluation scaffold exist.
- Regime snapshots can be injected into portfolio report context.

## Current priorities
1. Formalize ingestion adapters and cached data contracts for macro proxies.
2. Calibrate/validate thresholds with reproducible backtest slices.
3. Extend dashboard outputs for transition and persistence diagnostics.
4. Harden policy mapping so every tilt recommendation is test-backed.
5. Extract reused pure helpers to `market_helper/utils` while keeping regime semantics in-module.

## Exit criteria
- Regime output schema is stable and dashboard-ready.
- Policy recommendations have backtest evidence and documented assumptions.
- Integration APIs can consume regime outputs without custom glue code.
