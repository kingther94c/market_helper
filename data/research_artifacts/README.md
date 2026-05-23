# Research artifacts — regime calibration record

Chronological log of the regime engine's calibration rounds. Each round
ships a frozen config commit + a paired HTML research report explaining
methodology, decisions, evidence, and trade-offs.

**Canonical methodology**: see
[ADR 0004 — regime calibration discipline](../../docs/decisions/0004-regime-calibration-discipline.md).

## How to read this folder

- Reports are **HTML, self-contained** (no JS/CSS dependencies). Open in
  any browser. EN + CN versions of each round.
- Underlying data is in companion `.json` files — useful for re-running
  analysis with different filters / metrics. Schema is stable across
  rounds.
- Each round corresponds to one or more commits on the regime engine
  config or methodology; commit SHAs are in the round summary table.
- Older rounds (Q1–Q6) predate this index and are documented inline in
  the calibration notebooks under `notebooks/regime_detection/`.

## Round index (newest first)

| Round | Scope | Headline | Report (EN / CN) | Raw data |
|---|---|---|---|---|
| **Q9 Phase 1+2** (2026-05-23) | Neighborhood-stability audit on Q9 grid | Q9 winner ranks #9 of 136 eligible by robust score; Δ +0.6pp to top is within grid noise; top-robust trades -1.9pp holdout. **Verdict: keep Q9.** | [EN](macro_q9_neighborhood_addendum_en.html) / [CN](macro_q9_neighborhood_addendum_cn.html) | `macro_neighborhood_q9{,_v2}.json`, `macro_calibration_grid_q9_refined.json` (522 configs), `macro_q9_vs_robust_top_per_anchor.json` |
| **Q9** (2026-05-23) | Inflation velocity layer + train/holdout discipline | Added `inflation_velocity` concept (CPI/CoreCPI/PCE 3m annualized). Macro layer 0.5→0.6, inflation deadband ±0.12→±0.15. Train 55.9→59.7% (+3.8pp), holdout 57.4→59.4% (+2.0pp). | [EN](macro_calibration_q9_en.html) / [CN](macro_calibration_q9_cn.html) | `macro_calibration_grid_q9.json`, `macro_calibration_analysis_q9.json`, `macro_scout_q9_after.json` |
| **Q8 audit** (2026-05-22) | Four-question audit on shipped Q8 | (Q1) Robustness 21/21 wins; (Q2) only 2 genuine FAIL-clear cases isolated (2022 H1 inflation growth + 2025 tariff); (Q3) latency +3bd vs baseline (acceptable); (Q4) layer-blend change explains 2022 H1 inflation flip. | [EN](macro_calibration_audit_en.html) / [CN](macro_calibration_audit_cn.html) | `macro_robustness.json`, `macro_label_ambiguity.json`, `macro_latency.json`, `macro_concept_attribution.json` |
| **Q8** (2026-05-22) | First FRED-hydrated macro calibration (162-config grid) | Layer blend 0.35/0.30 macro + 0.65/0.70 market → **balanced 0.50/0.50**; growth_thresh ±0.15 → **±0.10**. Overall consensus 51→56% (+5pp); growth axis +11pp. | [EN](macro_calibration_report.html) / [CN](macro_calibration_report_cn.html) | `macro_calibration_grid.json`, `macro_calibration_analysis.json`, `macro_scout{,_after}.json` |
| **Q7** (2026-05-22) | Risk overlay calibration (192-run anchor grid) | `enter_threshold` 0.75 → **0.65**, `min_consecutive_days` 3 → **1**. Same-day Lehman / COVID waterfall detection; benign FP rate 3.0 → 6.4%. | [EN](calibration_report.html) | `calibration_grid_results.{json,csv}`, `calibration_analysis.json` |

## Round structure (what each report covers)

Every full-round report contains the same sections so they read like
panels of one continuous study:

1. **Goal** — what success looks like for this round
2. **Methodology** — anchors used, metrics computed, selection rule
3. **Macro data dimensions** — which knobs are in scope, which are frozen
4. **Baseline scout** — anchor matches under the *previous* shipped config
5. **Grid search** — top-N candidates + Pareto front
6. **After-calibration scout** — anchor matches under the winner
7. **Decisions & deltas** — per-anchor before/after, score-trajectory
8. **Config diff** — YAML patch that ships
9. **Caveats** — out-of-scope, framing assumptions, known limits

Audit and addendum rounds reuse the same skeleton but specialize on the
question they answer (robustness, latency, attribution, neighborhood
stability).

## Reproducing any round

Each round has paired scripts under [`../../scripts/research/`](../../scripts/research/)
named `macro_*` or `macro_*_q9.py`. The pattern per round is:

1. `macro_calibration_grid[_qN].py` — run the parameter sweep
2. `analyze_macro_calibration[_qN].py` — pick the winner under the
   selection rule
3. `macro_scout.py` — measure anchor performance under a config
4. `generate_*_report.py` — emit the EN/CN HTML

Plus round-specific audit scripts (`macro_robustness.py`,
`macro_label_ambiguity.py`, `macro_latency_probes.py`,
`macro_concept_attribution.py`, `macro_neighborhood_stability*.py`).

All scripts use:
- `scripts/research/anchors.py` for the consensus-anchor definitions
  (single source of truth, includes `is_holdout` markers)
- `data/interim/fred/macro_panel.feather` for FRED data
  (rebuildable with `_rebuild_panel.py` from cached series)
- `data/external/regime_detection/historical/market_panel_to_2024.feather`
  merged with the live Yahoo cache for market data

## Open work (parked, not in any active round)

See [`../../plan/current.md`](../../plan/current.md) for the live Regime
Engine open list. As of the most recent round (Q9 + Phase 1+2 audit),
candidate next rounds are:

- **2025 tariff shock channel** — engine still has no single-event /
  policy-shock signal; both axes failed clear-confidence on this anchor
  in both Q8 and Q9.
- **2022 H1 growth misread** — layer-disagreement case where macro_g is
  correct (+0.30, payrolls YoY +5-6%) but market_g (-0.47, equity
  drawdown) drags the final to Neutral. Q9 60/40 blend lifted train
  g_match 11 → 53% but holdout misses persist.
- **Velocity layer 2nd-derivative** — current 3m annualized captures
  *rate*, not *acceleration*. A "deceleration" signal (velocity vs YoY
  divergence) could improve 2024 disinflation further.
- **2020H2 catch-up consensus revisit** — Q9 trade-off makes this anchor
  worse on inflation (-13pp); the LEVEL-honest framing may simply be
  wrong here. Re-label or move to holdout-only.
