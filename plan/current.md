# Current Plan

Active initiatives only. Future work lives in [`backlog.md`](backlog.md).
Track-level architecture detail lives in
[`../docs/architecture/devplans/`](../docs/architecture/devplans/). Cold
context is in `memory/archive/` (gitignored, not read by default).

## Portfolio Monitor

**State**: stable. No near-term scope open.

Recent landed work (one-liners; full detail in
`memory/archive/landed/portfolio_monitor_landed.md`):
- Combined report restructured (slim KPI strip, single regime section).
- Performance overview + benchmark comparison vs cash + SPY (USD/SGD).
- FX history coverage fix (`DEFAULT_YAHOO_FX_PERIOD` `2y` → `max`).
- EQ lookthrough redesign (per-symbol country mix, DM/EM taxonomy).
- Sector benchmark switched SPY → ACWI.
- Country × Sector heatmap (with amber approximate disclaimer).
- Actionable warning surface complete — `pm-error` banners with inline
  "Run Flex Refresh" / "Refresh Benchmark Cache" buttons.
- Env-first secret resolution end-to-end + Windows agent-shell ROOT
  inheritance auto-recovery in `market_helper.config.local_env`.
- Architectural route confirmed (no separate snapshot/Playwright pipeline —
  see ADR 0002).

Further portfolio-monitor work rotates in through [`backlog.md`](backlog.md)
as discrete asks land.

## Regime Engine

**State**: calibrated through **Q9** (inflation velocity layer + train/holdout
discipline). Engine + concept aggregation + symmetric tanh + beta-adjusted
returns + label hysteresis + anchor-period sanity harness + auto-sync +
historical baseline + per-frequency decay all landed. See
`memory/archive/landed/regime_engine_landed.md` and
`data/research_artifacts/` for the calibration record.

Q9 landing summary (2026-05-23):
- New `inflation_velocity` concept (CPI/CoreCPI/PCE 3m annualized via the
  existing `qoq_annualized` transform), weight **1.0**.
- `macro_nowcast` layer weight 0.50 → **0.60**, `market_implied` 0.50 →
  **0.40**.
- Inflation deadband widened ±0.12 → **±0.15** (prevents over-rotation when
  YoY-level and 3m-velocity both read ~3% as Up).
- Growth velocity concept added but kept at weight 0 (grid showed no win).
- Mechanical: `SeriesSpec` gained optional `name` field so the same FRED
  `series_id` can produce multiple panel columns (e.g. CPIAUCSL yoy_pct +
  CPIAUCSL_velocity_3m). Backwards-compatible (name defaults to series_id).
- **Train/holdout split** introduced: 9 training anchors + 4 holdout (2008,
  2017, 2024, 2025). Grid selects on train only; holdout is hard
  non-regression constraint. Validation-aware selection (not selection
  pressure on holdout). Result: train +3.8pp, holdout +2.0pp vs Q8 — gap
  +0.3pp (almost zero).
- Reports: `data/research_artifacts/macro_calibration_q9_{en,cn}.html`.

Q9 neighborhood-stability addendum (2026-05-23, follow-up to user critique
"grid argmax can sit on noise spikes"):
- **Phase 1**: L1-neighborhood re-analysis of the original 360-config grid.
  Q9 ranked #9 by `robust_train = mean(self, neighbor median)`. Top robust
  (ivw=0.7, it=0.10) gained +0.6pp robust but lost -1.9pp holdout vs Q9.
- **Phase 2**: 162-config half-step refinement around contenders →
  augmented 522-config grid. Q9 ranked #35 of 136 eligible. Top robust
  unchanged; intermediate refined points (e.g. it=0.13) trade marginal
  robust gain (+0.4pp) for holdout loss (-0.6pp) — within noise.
- **Verdict: keep Q9 unchanged**. The trade-off curve runs along
  `inflation_thresh`: tighter it (0.10) wins HIGH-CPI anchors (2023:
  +18pp on i_match, 2020H2: +24pp) but loses NORMAL/AMBIGUOUS-CPI anchors
  (2017 Goldilocks holdout: -20pp, 2024 disinflation holdout: -12pp,
  2019 H2: -15pp, 2018 Q4: -14pp). Q9's wider it=0.15 handles 5 anchors
  better including 2 of 4 holdouts.
- Reports: `data/research_artifacts/macro_q9_neighborhood_addendum_{en,cn}.html`.
- Scripts: `scripts/research/macro_neighborhood_stability{,_v2}.py`,
  `macro_calibration_grid_q9_phase2.py`,
  `generate_q9_neighborhood_addendum.py`.

Open near-term work:

1. **(Optional)** Pin per-anchor macro fixtures from
   `macro_scout_q9_after.json` into the anchor-period harness for a CI
   guardrail on the macro layer. Not blocking — the full-history macro
   scout is the offline measurement harness today.

2. **Q10 candidates (parked, not active)**:
   - 2025 tariff shock channel — engine still has no single-event-shock
     signal; both axes failed clear-confidence on this anchor in Q8 and Q9.
   - 2022 H1 growth misread — macro_g says Up (correctly, YoY payrolls
     strong post-COVID) but market_g says Down (equity drawdown); Q9 60/40
     blend lifted train g_match from 11% to 53% but holdout misses persist.
     Investigate concept-level rebalancing for post-COVID base-effect
     handling.
   - Velocity layer 2nd-derivative refinement — current 3m annualized
     captures *rate*, not *acceleration*. A separate "deceleration" signal
     (velocity vs YoY divergence) could improve 2024 disinflation further.

3. **Standing guardrail** — Keep ML layers (`macro_truth_ml`,
   `return_truth_ml`) unavailable / zero-weight until model artifacts and
   feature schemas are explicit. Do not emit fake ML outputs.

Detail: `docs/architecture/devplans/regime_engine.md`.

## Repository governance

Canonical layered-memory layout landed in ADR
[0003](../docs/decisions/0003-layered-memory-canonical-homes.md). See
[`AGENTS.md`](../AGENTS.md) for governance rules and reading order.
