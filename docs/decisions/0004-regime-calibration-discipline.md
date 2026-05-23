# ADR 0004: Regime calibration discipline

**Status**: Accepted.

## Context

The regime engine is tuned by grid search over its YAML knobs (layer
blend, axis deadbands, concept weights, hysteresis, decay). The
calibration history (Q1–Q9) accumulated by trial and error revealed
three failure modes that are not solved by adding more anchors or
running larger grids:

1. **In-sample leakage**: when the same anchor set drives both grid
   search and validation, the +Npp "improvement" reported per round is
   indistinguishable from overfitting to that anchor set. The full
   13-anchor consensus was used both ways through Q8.

2. **Framing artifacts**: the engine's YoY + threshold scoring is
   LEVEL-honest ("how high is CPI YoY vs 2.5% comfort"). When
   author-curated consensus uses DIRECTION-honest framing ("CPI is
   falling"), miss reports look like signal failure but are actually
   definitional disagreement. The 2023-2024 disinflation windows are
   the canonical case.

3. **Point-argmax brittleness**: a 360-config grid returns one
   argmax. That winner may sit on a noise spike — a 0.5pp margin over
   neighbors evaporates when the data drifts or the grid is refined.
   Q9's argmax-by-train picked a different config than its
   neighborhood-robust top, with -1.9pp gap on holdout.

Each round (Q7 risk overlay, Q8 macro axis, Q9 velocity layer + train/
holdout) shipped a partial fix for one of these. This ADR codifies all
three as standing rules so they are applied uniformly going forward.

## Decision

Three discipline rules govern every future calibration round:

### Rule 1 — LEVEL-honest anchor labels

Anchor `g_consensus` and `i_consensus` labels reflect the engine's
actual scoring semantics (absolute level vs comfort band), not direction
of change. If an anchor is fundamentally direction-based (e.g. "2023
disinflation"), it is tagged `confidence="definition-dependent"` and
carries an alternative `alt_g` / `alt_i` label that the audit pipeline
uses for sensitivity reporting.

Direction-honest signals are a separate engineering project (e.g. Q9's
velocity layer adds 3-month annualized rates as a parallel concept).
They are NOT a re-framing of the level-honest anchors.

**Enforced by**: `scripts/research/anchors.py` — `Anchor` dataclass has
required `confidence` field; `perturb_alt_consensus()` consumes alt
labels for the Q8-style label-ambiguity audit.

### Rule 2 — Train / holdout discipline

Every anchor is tagged `is_holdout: bool`. Grid search evaluates only
on training anchors. Holdout enters as a **hard non-regression
constraint** post-hoc — never as an optimization objective (which
would be a slower form of leakage).

Selection rule:

1. Compute candidates' composite on training anchors.
2. Filter to those that strictly improve baseline on training metrics.
3. Filter further to those that do **not regress** baseline on holdout.
4. Among survivors, rank by `train_overall + holdout_overall` deltas.
5. If no candidate survives the holdout filter: report and **do not
   ship** the round. Keep the prior config; document the failure.

Holdout size is small (4 anchors out of 13). The split is fixed in
`anchors.py` and is not re-rolled per round — re-rolling re-introduces
in-sample selection of the holdout itself.

Current holdout set (clear-confidence anchors spanning crisis / normal
/ target / latest data):

- 2008 GFC trough (crisis)
- 2017 Goldilocks (normal cycle)
- 2024 disinflation (definition-dependent — Q9 velocity layer's target;
  held out precisely to avoid fitting velocity to its target)
- 2025 tariff shock (latest data, tests generalization)

**Enforced by**: `Anchor.is_holdout` field;
`scripts/research/macro_calibration_grid_q9.py` evaluates train and
holdout separately; `analyze_macro_calibration_q9.py` applies the
selection rule.

### Rule 3 — Neighborhood-stability check on the grid winner

A grid argmax is only ship-worthy if its **L1 neighborhood** (same
categorical dims, ±1 step on exactly one continuous dim — max 8
neighbors) is also strong:

- `n_neighbors >= 4` (corner configs lack enough context — skip)
- `min(neighbor train_overall) >= max(baseline, self - 5pp)` —
  no neighbor regresses baseline; worst neighbor stays within 5pp of
  the candidate itself
- Rank by `robust_train = mean(self_train, median(neighbor train))` —
  rewards configs that have both high self score AND high
  neighborhood center

If the argmax winner is *not* the neighborhood-robust top, decide by
inspecting **which dimension** explains the gap:

- If a continuous dim (e.g. inflation_thresh sits at a boundary), run
  **Phase 2 local refinement**: add half-step grid points around the
  contenders, re-run neighborhood analysis on the augmented grid.
- If they sit on different points of an explicit train/holdout
  trade-off curve (Q9 case: it=0.10 favors train, it=0.15 favors
  holdout), keep the candidate whose holdout is better — the small
  robust-score gap is within sampling noise and the holdout advantage
  is meaningful.

**Enforced by**: `scripts/research/macro_neighborhood_stability_v2.py`
(generic; derives step lists from the loaded grid data).

## Consequences

- Each calibration round has a paired audit. Before Q7 the workflow was
  grid → ship. After this ADR the workflow is grid → analyze → audit
  (robustness, label ambiguity, latency, attribution, neighborhood) →
  apply or keep.
- The bar for "ship a new round" is higher: a candidate must win on
  train, not regress on holdout, AND survive neighborhood checks. Many
  rounds will report "no clean improver found; keep prior config" —
  that is the correct outcome, not a failure to find one.
- Consensus label disagreements are surfaced explicitly via the
  `confidence` taxonomy. Round verdicts that fail on
  `definition-dependent` anchors are not red flags; failures on `clear`
  anchors are.
- The reproducer scripts and JSON artifacts under
  `data/research_artifacts/` are the durable record. The HTML reports
  are summaries on top. See
  [`data/research_artifacts/README.md`](../../data/research_artifacts/README.md)
  for the round index.

## Open question (parked)

Anchor relabeling. The 2020H2 catch-up anchor has produced a recurring
LEVEL/DIRECTION tension across rounds (Q8 +28pp inflation win, Q9 -13pp
loss). Either keep current LEVEL label and treat the Q9 regression as a
necessary trade-off for inflation_velocity, or revisit the label as
"genuinely ambiguous, holdout-only". Deferring until a round actually
proposes a config change keyed to this anchor.
