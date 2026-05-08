# Regime Engine Devplan

## Product Model

Two macro axes:
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

## Configuration

Every factor input is YAML-driven; adding, removing, or retuning a series
should never require a code change.

- `configs/regime_detection/fred_series.yml`
  - Top-level `engine:` block carries bucket weights, default normalization,
    rolling-z-score window / min_periods / clip, minmax and percentile default
    windows, hysteresis days, warmup.
  - Each entry in `series:` declares `axis` (`growth` | `inflation`),
    `bucket` (`fast` | `slow`), `transform` (`level`, `centered`, `yoy_pct`,
    `yoy_diff`, `inverted_yoy_diff`, `mom_pct`, `mom_diff`, `qoq_annualized`),
    `direction` (`positive` | `negative`), `normalization`
    (`none` | `centered` | `threshold` | `zscore` | `minmax` | `percentile`),
    `weight`, plus optional per-series overrides for the z-score window/clip,
    minmax bounds/window, percentile window, neutral level, and threshold.
- `configs/regime_detection/market_regime.yml`
  - `data_sources.symbols` enumerates the Yahoo aliases the panel needs.
  - `normalization:` block sets defaults for window sizes and clip.
  - `growth.signals`, `inflation.signals`, `risk_overlay.signals` use the
    decoupled (`transform`, `normalization`) pair. Legacy combined tokens
    (`level_zscore`, `change_zscore`, `realized_vol_zscore`) are still
    accepted.
- `configs/regime_detection/regime_engine.yml`
  - Layer enable flags + per-axis weights, regime quadrant thresholds,
    confidence/disagreement settings, and risk-overlay thresholds (single
    source of truth — `market_regime.yml` no longer carries them).

New factor inputs ship at `weight: 0.0` so they are wired but inactive: yield
curve (T10Y2Y, T10Y3M), 10y real yield, breakevens (T5YIE), PPI, M2 YoY,
initial claims, housing starts/permits, U. Michigan sentiment, manufacturing
employment, growth-vs-value (IWF/IWD), additional sector relatives (XLB, XLE,
XLV, XLF, AGG/SPY), USD strength (UUP), copper-vs-gold.

## Current State

Landed:
- Engine contracts, coordinator, `regime-detect`, `regime-calibrate`,
  `regime-run-report`, `regime-refresh-report` CLI.
- Standalone HTML report and calibration HTML + question-driven notebook.
- GUI operate-drawer actions for cached run and refresh run.
- Combined portfolio report includes the regime section when the artifact
  exists.
- All previous v1 (7-regime rulebook, multi-method service, JSON proxy/returns
  pipeline, `regime_config.yml`/`regime_policy.yml`) deleted.

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
