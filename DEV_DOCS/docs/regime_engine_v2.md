# Regime Engine v2 Design Note

Regime Engine v2 uses two macro axes: growth and inflation. Risk/stress is an
independent overlay, not a third macro dimension.

The dashboard should show the final regime label first, then expand into layer
detail:

- `macro_nowcast`: economically meaningful macro anchor from point-in-time
  macro data where supported. It is slower because macro data is published with
  lags.
- `market_implied`: faster market-pricing view using proxies such as equities,
  sectors, credit, rates, commodities, inflation-linked bonds, and volatility
  where available. It is noisier than macro data.
- `macro_truth_ml`: generic classification-model layer for ex-post macro labels.
- `return_truth_ml`: generic classification-model layer for future asset-return
  regime labels.

Macro and market disagreement is meaningful information. It may reflect slow
macro data versus fast market pricing, or a genuine dislocation, so v2 surfaces
disagreement directly instead of hiding it inside a consensus label.

Risk/stress is reported through an independent overlay driven by volatility,
credit stress, liquidity, and related stress indicators. It is regime context
only and must not produce allocation changes or policy target changes.

ML layers use a separate model-selection interface so SVM, logistic regression,
random forest, gradient boosting, or other classifiers can be swapped without
changing the engine coordinator. The initial SVM adapter is optional and must
not emit fake outputs: if there is no valid dependency, model artifact, schema,
or feature set, the layer is `Not available`. Default ML weights are `0.00`.

Ex-post revised macro data may be used for labels only, never as model features.
Features must remain point-in-time.

Confidence is a lightweight product indicator with `Low`, `Medium`, and `High`
levels. It combines score strength and layer agreement; it is not a calibrated
probability.

Data refresh should preserve existing historical caches. FRED keeps its
per-series incremental cache behavior. Market panel sync merges cached history
with recent Yahoo rows by default, then sorts, deduplicates, and writes
diagnostics for duplicate dates and unexpected panel gaps.

Phase 2 replacement status: `regime-run-report` and `regime-refresh-report` now
write `regime-engine-v2` rows by default. `regime-detect-multi` and
`regime-report-multi` are deprecated compatibility commands for old
`regime-multi-v1` payloads.

Calibration status: `regime-calibrate` is a research-only workflow that runs
v2 over local macro and market panels, then writes a static HTML report plus a
question-driven notebook. The anchor set includes GFC, 2011 stress, 2014-16 oil
collapse, 2017 soft landing, 2018 Q4, COVID, 2022 inflation/tightening,
2023-24 disinflation, and the April 2025 Liberation Day tariff-shock window.
The workflow is for product calibration only; it does not alter configs, train
ML models, produce trading signals, or emit allocation changes.

Q5 calibration note: the calibration workflow now loads the macro-method
`engine:` block from `fred_series.yml` before running v2, so the research
baseline matches the calibrated macro compression path used by the engine
contract.

Q6 calibration note: the corrected baseline uses a modestly market-heavier
blend and a narrower axis deadband to make recovery windows more responsive.
The calibrated layer weights are macro/market `0.35/0.65` for growth and
`0.30/0.70` for inflation; axis thresholds are `+/-0.15` for growth and
`+/-0.12` for inflation.

Current first-pass calibration uses neutral/deadband normalization for macro
inflation series so normal 2%-ish inflation is not automatically treated as
`Inflation Up`. The ensemble gives a modestly higher weight to
`market_implied` than `macro_nowcast` because market pricing is the faster layer.
Disagreement is reserved for opposing directional layer calls, not every
neutral-vs-directional difference.
