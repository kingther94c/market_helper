# ADR 0006: Policy-expert allocation predictor (allocation-layer overlay)

**Status**: Accepted (2026-06-06). Realizes the long-gated `macro_truth_ml` /
`return_truth_ml` ML slots as a single allocation-layer predictor, surfaced as an
advisory panel on the dashboard Regime tab.

**Update (2026-06-06, goal v2 — Section A):** the two dead SVM slots are now **fully
removed** (deleted from `engine_v2.py`, `ml.py`, `regime_engine.yml`, the snapshot
schema, `ALL_METHODS`, and all referencing tests) rather than left gated — the
macro/market ensemble + verdict are unchanged (the slots had weight 0). Sections B–E
of goal v2 then upgrade the predictor (rigorous model selection + 30-day lazy retrain),
move it to a **peer card alongside the macro/market regime layers** with a
feature-attribution breakdown, and add a separate descriptive **Policy-Expert Trending**
panel. This ADR will be superseded by a consolidated ADR once that lands.

## Context

The regime engine (`engine_v2.py`) has carried two dormant ML layer slots —
`macro_truth_ml` and `return_truth_ml` — gated `enabled: false` with zero ensemble
weights in `configs/regime_detection/regime_engine.yml`, on the standing rule "emit no
fake ML outputs until a feature schema + trained artifact are explicit."

The regime-aware policy-expert research track (Phases 1-6, `scripts/research/policy_expert_*.py`)
produced exactly that: four economically-interpretable policy experts (Growth×Inflation),
a labelled forward target, an explicit 21-feature ex-ante panel, and a walk-forward
predictor of which expert outperforms (OOS rank-IC ~0.20 at 6M). The goal was to surface
this predictor "running on the dashboard" without destabilising the regime verdict.

Two integration shapes were possible (the research spec posed them):
- **(a)** wire the predictor in as a third blended *axis-layer* of the regime ensemble;
- **(b)** run it *one level up* as an allocation driver, fed BY the regime axes, not
  mixed INTO them.

## Decision

**Adopt (b): an additive allocation-layer overlay, not an axis-layer.**

- New package module `market_helper/regimes/policy_expert_predictor.py` loads the
  committed numpy-only artifact (`policy_expert_model_artifact.json`: feature schema +
  standardisation + linear coef + expert exposure vectors + softmax temp) and the latest
  ex-ante feature row (`policy_expert_features.csv`), and returns a
  `PolicyExpertPrediction` (soft mix across the 4 experts + target sleeve exposures).
  Pure-Python (json/csv/math) — **no sklearn / numpy / network in the render path**
  (the FRED/Yahoo pulls happen offline in the research harness; live pulls timed out and
  are unfit for the render path).
- The combined dashboard report attaches the prediction to the regime view-model at a
  single chokepoint, `portfolio_html._attach_policy_allocation`, which renders a new
  "Policy-Expert Allocation (ML)" panel in the Regime tab. The standalone CLI regime
  report and unit tests leave it unattached (panel omitted).
- **Graceful degradation**: every predictor failure path returns
  `PolicyExpertPrediction(available=False, reason=...)` → an explainer card, never a fake
  number, never an exception to the report (mirrors the `missing` / `engine_error`
  `RegimeArtifactState` pattern).
- **The dormant `macro_truth_ml` / `return_truth_ml` slots remain gated and untouched.**
  This overlay does not compete for ensemble weights and cannot move the regime verdict.
- **Advisory / read-only.** No order entry; the V1 broker-read-only invariant holds.

## Consequences

- The dashboard Regime tab now shows the live expert mixture + target sleeves with an
  as-of date and a MONITOR caveat. The regime engine's verdict is unaffected.
- The predictor is decoupled and independently testable
  (`tests/unit/regimes/test_policy_expert_predictor.py`); the panel render is covered in
  `tests/unit/reporting/test_regime_html.py`.
- Freshness is bounded by the committed feature panel's last month; a scheduled
  re-run of `scripts/research/policy_expert_features.py` + `policy_expert_model.py`
  refreshes it. A live in-render feature refresh was deliberately rejected (render-path
  network fragility).
- Verdict is **MONITOR**, not proceed: the model adds risk-adjusted value over standard
  baselines but is matched by a simple cash-in-stagflation heuristic; it ships advisory
  pending a cost/financing audit and live tracking.
