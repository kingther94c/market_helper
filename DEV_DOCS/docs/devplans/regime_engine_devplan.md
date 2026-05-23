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

Calibrated through **Q8** (macro-axis grid). Engine + CLI baseline, concept
aggregation on both layers, symmetric tanh compression, beta-adjusted
relative returns, label-level hysteresis, anchor-period sanity harness (4
episodes pinned), auto-sync + historical baseline (1984-2024 panel), and the
per-frequency decay structural change have all landed. Q7 lowered the risk
overlay threshold to fire same-day on Lehman; Q8 rebalanced the macro layer
blend to 50/50 and tightened growth_thresh to ±0.10. See
`DEV_DOCS/PLAN.md` "Regime Engine" landed list + the calibration reports
under `data/research_artifacts/` for the full record.

## Near-Term Next Steps

1. **Direction-honest velocity layer (Q9 candidate)**
   The engine's YoY + threshold scoring is structurally level-based: it
   cannot read "inflation is falling toward target" as Down while CPI YoY is
   still above 2.5%. The proposed remedy is a MoM-velocity or 6m-change
   transform / concept that captures the **direction** axis alongside the
   existing **level** axis. Concrete shape:
   - Pick the transform: probably a new `mom_zscore_*` or `change_6m`
     normalization spec on inflation-side series.
   - Add a "velocity" concept to `inflation_concepts:` with a modest blend
     weight against the existing level concepts.
   - Calibration question: does it help the 2022-H2 → 2023 disinflation
     anchor without breaking 2022-H1 (where YoY is still rising)?
   - Run as a Q9 grid against the existing macro anchors and the new ones
     from `macro_scout_after.json`.

2. **(Optional)** Pin per-anchor macro fixtures from `macro_scout_after.json`
   into the anchor-period harness if a CI guardrail for the macro layer is
   desired. The full-history macro scout already serves as an offline
   measurement harness so this is not blocking.

3. **Standing guardrail** — Keep ML layers (`macro_truth_ml`,
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
