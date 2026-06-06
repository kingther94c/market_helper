# ADR 0007: Policy-expert ML predictor (rigorous, self-retraining) + Trending panel

**Status**: Accepted (2026-06-06). **Supersedes ADR 0006.** Removes the dead SVM layer
slots, productionises the policy-expert predictor with model selection + a lazy 30-day
retrain, surfaces it as a peer to the macro/market regime layers with a feature
breakdown, and adds a separate descriptive Trending panel.

## Context

ADR 0006 shipped the policy-expert predictor as an advisory allocation-layer *panel* and
left the dormant `macro_truth_ml` / `return_truth_ml` SVM slots gated. Two follow-on
needs emerged: (1) those dead slots still cluttered the engine + UI and should be gone;
(2) the predictor was a one-off research artifact (single Ridge, trained once, committed)
rather than a properly model-selected, self-maintaining production model; and the user
wanted the forecast shown *with* the regime axes (+ a "why" breakdown) plus a separate
descriptive momentum view.

## Decision

**1. Remove the SVM slots entirely.** `macro_truth_ml` / `return_truth_ml` are deleted
from `engine_v2.py` (layer set, scoring, the 4 `ml_*_score` snapshot fields), `ml.py`
(deleted), `regime_engine.yml`, `run_regime_report.py`, the snapshot schema, and all
tests. The macro(0.60)+market(0.40) ensemble and the verdict are bit-for-bit unchanged
(the slots had weight 0).

**2. Rigorous, model-selected predictor.** `scripts/research/policy_expert_model_selection.py`
compares {ridge, elastic-net, multinomial-logit, random-forest, hist-grad-boosting,
linear-ensemble} by embargoed time-series CV, scored by OOS excess-captured / rank-IC /
log-loss **plus an allocation-dispersion (dynamism) check**. Key finding: ElasticNet(α=1)
*degenerates* — L1 zeroes every coefficient, collapsing to the static unconditional
ranking; it "wins" raw capture only by becoming always-best. The deployable winner is
**Ridge with embargoed-CV α (≈1000)**: dynamic (all coefficients non-zero), interpretable,
OOS rank-IC +0.22. Trees underperform linear on the autocorrelated targets.

**3. Production training pipeline + lazy 30-day retrain.**
`market_helper/regimes/policy_expert_training.py` rebuilds the panel + 22 ex-ante features
+ forward-expert-return labels from live keyless data and fits Ridge, writing a **dated**
numpy artifact + the refreshed feature panel. `policy_expert_predictor.predict_latest`
checks the artifact age and, if missing / unstamped / older than 30 days, retrains on ALL
data (best-effort, network+sklearn there only) before predicting; the common fresh path
stays **pure-Python** (coef-based). Every failure degrades gracefully (stale artifact /
explainer), never a fake number.

**4. UI: forecast peer card + breakdown, and a separate Trending panel.** The forward
forecast renders as **"Policy-Expert Forecast (ML)"** in the Regime "Axes & Layers" group
(a peer to the macro/market layers) with a **feature-attribution breakdown** (top driver
features per expert; linear coef×standardised value), mirroring the macro/market concept
breakdown. A separate **"Policy-Expert Trending"** panel (`policy_expert_trending.py`,
backed by a new daily expert-return series, FI→IEF) shows EW relative performance →
softmax probabilities, an inline-SVG probability **trend chart**, and an allocation +
**3M / 1M / 1W** table. Forecast = forward/ML; Trending = backward/momentum — deliberately
distinct, attached only on the combined-report path, graceful when unavailable.

## Consequences

- The regime engine is leaner; no dead ML rows in the Layer Detail / heat strip.
- The predictor is self-maintaining (monthly lazy retrain) and model-selected, with a
  documented winner + hyperparameters in the artifact and the study JSON.
- The Regime tab now carries two advisory, read-only policy-expert surfaces (forward
  forecast + backward trend). Broker read-only preserved; no order entry.
- Verdict stays **MONITOR** (the predictor's edge is risk-adjusted; a simple
  cash-in-stagflation rule remains competitive — see the research report).
- The monthly lazy retrain adds latency to whichever report first runs it; it is
  best-effort and falls back to the existing artifact on any failure.
