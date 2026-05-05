# Regime Engine v2 Devplan

## Product Model

Regime Engine v2 has two macro axes:
- Growth
- Inflation

Risk/stress is an independent overlay. It is dashboard context, not a third
macro axis and not an allocation engine.

Active layers:
- `macro_nowcast`: slower economic anchor from point-in-time macro panels.
- `market_implied`: faster market-pricing view from market proxies.
- `macro_truth_ml`: generic classification layer, disabled/unavailable unless
  valid artifacts exist.
- `return_truth_ml`: generic classification layer, disabled/unavailable unless
  valid artifacts exist.

## Current State

Landed:
- V2 contracts and coordinator.
- `regime-run-report` and `regime-refresh-report`.
- Standalone v2 HTML report.
- Calibration HTML + question-driven notebook.
- GUI operate-drawer actions for cached run and refresh run.
- Combined portfolio report can include the v2 regime section.

## Near-Term Next Steps

1. **Calibration decision pass**
   Review the calibration HTML and notebook observations. Decide whether each
   anchor-period mismatch is acceptable macro lag, market noise, or a config
   problem. Do not tune before this pass.

2. **Narrow config tuning**
   If the calibration review is clear, adjust only config-owned behavior:
   thresholds, confidence/disagreement settings, layer weights, normalization,
   market signal weights/lookbacks, or macro bucket weights.

3. **Backtest sanity harness**
   Add a small pinned-fixture harness for anchor periods such as GFC, COVID,
   2017 Goldilocks, 2022 inflation shock, 2023-24 soft landing, and April 2025
   tariff shock. This is a sanity harness, not a trading backtest.

4. **ML artifact lifecycle**
   Keep ML layers disabled/zero-weight until feature schemas, model selector
   inputs, model artifacts, and unavailable reasons are explicit. Do not emit
   fake ML outputs.

## Deferred

- Random forest / gradient boosting training workflows.
- Allocation tilt suggestions.
- Trading signal generation.
- Portfolio optimization based on regime.

## Guardrails

- Do not average risk into growth or inflation.
- Preserve macro/market disagreement as a first-class output.
- Ex-post macro data may be labels only, never features.
- Disabled or unavailable ML layers must not affect final scores.
