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
  - Optional `decay_half_life_bdays:` per series; otherwise resolved from
    `frequency_hint` (daily/weekly=5, monthly=22, quarterly=66, annual=252).
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

### Activating a Dormant Signal

The fetcher (`sync_fred_macro_panel`) already pulls every series declared in
`fred_series.yml`, but `data/interim/fred/` is created on first sync, so a
dormant series has no cached observations until you run it. To activate:

1. **Hydrate the FRED cache** (one-shot; ~10s cold for the full 23-series set):
   ```bash
   export FRED_API_KEY=...        # or put it in local.env (see below)
   python -m market_helper.cli.main fred-macro-sync
   ```
   Requires `FRED_API_KEY` from the process env (preferred), or from
   `<MARKET_HELPER_GDRIVE_ROOT>/local.env` (canonical multi-machine setup —
   set ROOT once in your shell profile; on Windows the resolver auto-reads
   from the User registry hive if the parent process didn't inherit it), or
   from `configs/portfolio_monitor/local.env`. Subsequent runs are incremental
   from the last cached date. Market signals (Yahoo) are lazy-loaded per call
   and need no separate sync step.

2. **Wire the series into a concept** in `fred_series.yml`
   (`growth_concepts:` / `inflation_concepts:`) or set `weight > 0` for a
   market signal in `market_regime.yml`.

3. **Rebuild the panel** — `build_panel()` only emits columns referenced by
   active concepts, so newly activated series need a panel rebuild
   (`regime-detect` or `regime-refresh-report`) before they contribute.

4. **Re-run calibration** (`regime-calibrate`) to verify the added signal
   does not destabilize axis state classification on anchor periods.

If FRED deprecates a dormant series between the time it shipped and the time
it is activated, the sync will fail loudly — swap to an active replacement
in `fred_series.yml`.

## Current State

Calibrated through **Q9** (inflation velocity layer + train/holdout
discipline) and stress-tested with a Q9 Phase 1+2 neighborhood-stability
audit. Engine + CLI baseline, concept aggregation on both layers, symmetric
tanh compression, beta-adjusted relative returns, label-level hysteresis,
anchor-period sanity harness (4 episodes pinned), auto-sync + historical
baseline (1984-2024 panel), per-frequency decay, multi-transform support
(same FRED series under YoY + qoq_annualized) all landed.

Round-by-round summary:
- **Q7** — risk overlay threshold 0.75 → 0.65, rcd 3 → 1 (same-day Lehman).
- **Q8** — macro blend 0.35/0.30 + 0.65/0.70 → balanced 0.50/0.50; growth
  deadband ±0.15 → ±0.10. Train (no holdout yet): +5pp overall.
- **Q9** — added `inflation_velocity` concept (CPI/CoreCPI/PCE 3m
  annualized) at weight 1.0; macro blend lifted to 0.6/0.4;
  `inflation_thresh` widened ±0.12 → ±0.15. **Train/holdout discipline
  introduced** (4 anchors held out: 2008 GFC, 2017 Goldilocks, 2024
  disinflation, 2025 tariff). Train +3.8pp, holdout +2.0pp, gap +0.3pp.
- **Q9 Phase 1+2** — neighborhood-stability audit on 522-config grid
  (original 360 + 162 half-step refinements). Q9 winner ranks #9 by
  robust-score; gap to top is +0.6pp but top-robust costs -1.9pp on
  holdout. **Verdict: keep Q9.** No config change.

Round catalog + reports: [`data/research_artifacts/README.md`](../../../data/research_artifacts/README.md).
Methodology rules (LEVEL framing, train/holdout, neighborhood check) are
canonicalized in [ADR 0004](../../decisions/0004-regime-calibration-discipline.md).

## Near-Term Next Steps

Open candidates parked in [`plan/current.md`](../../../plan/current.md):

1. **2025 tariff shock channel** — engine has no single-event /
   policy-shock signal; both axes failed clear-confidence on this anchor
   in Q8 and Q9.
2. **2022 H1 growth misread** — layer-disagreement case where macro_g
   says Up (correctly, payrolls YoY +5-6%) but market_g (-0.47, equity
   drawdown) drags the final to Neutral. Q9 60/40 blend lifted train
   g_match 11 → 53% but holdout misses persist; investigate
   concept-level rebalancing for the post-COVID base effect.
3. **Velocity layer 2nd-derivative** — current 3m annualized captures
   *rate*, not *acceleration*. A "deceleration" signal (velocity vs YoY
   divergence) could improve 2024 disinflation further.
4. **2020H2 catch-up anchor relabeling** — recurring LEVEL/DIRECTION
   tension. Q9 trade-off makes this anchor worse on inflation (-13pp);
   the level-honest framing may simply be wrong here. Re-label or move
   to holdout-only. See ADR 0004 open question.
5. **(Optional)** Pin per-anchor macro fixtures from
   `macro_scout_q9_after.json` into the anchor-period harness if a CI
   guardrail is desired. The full-history macro scout already serves as
   an offline measurement harness so this is not blocking.
6. **Standing guardrail** — Keep ML layers (`macro_truth_ml`,
   `return_truth_ml`) unavailable/zero-weight until model artifacts and
   feature schemas are explicit. Do not emit fake ML outputs.

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
