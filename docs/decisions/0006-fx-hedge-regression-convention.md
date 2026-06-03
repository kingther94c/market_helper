# ADR 0006: FX hedge advisor — regression convention & sizing

**Status**: Accepted (2026-06-03).

## Context

An SGD-base investor holds USD-denominated AUM. In SGD terms they are long USD
vs SGD — their SGD wealth rises when USD strengthens and falls when USD weakens.
They want a *target FX hedge allocation* that neutralises this USD/SGD exposure
using liquid CME FX futures (EUR/GBP/AUD/JPY/CNH vs USD), since there is no
liquid SGD future.

Several conventions had to be pinned because a sign or basis error silently
produces a hedge that *adds* exposure instead of removing it. Acceptance
criteria demand the conventions be explicit and the report be reproducible and
cache-aware.

## Decision

### 1. Value-in-USD price basis (USD per 1 unit of currency)

Every spot series is normalised to **USD per 1 unit of the foreign currency**
(the currency's *value in USD*). Yahoo quotes given the other way are inverted:
`SGD=X` (USDSGD = SGD per USD) → USD per SGD; `JPY=X`, `CNY=X` likewise.

This is deliberately the **inverse** of the repo's existing `fx_usdsgd_eod`
(SGD per USD, see `memory/hot/gotchas.md`). The value-in-USD basis makes both
the futures notional math (USD notional = units × USD-per-unit) and the hedge
direction natural. Betas are invariant to flipping target *and* regressors
together, so the only thing the basis fixes is the notional/direction mapping —
which is exactly why it must be stated.

### 2. Regression-replication hedge, signed long-foreign

Target return `r_tgt = Δln(USD per SGD)`. The investor's SGD wealth
`W = A·(SGD per USD) = A / (USD per SGD)` has first-order exposure **−A** to
`r_tgt`. To neutralise it we take **+A** exposure, which OLS
`r_tgt ≈ α + Σ βᵢ·rᵢ` (regressors = USD-per-unit returns of each instrument)
replicates by holding **+βᵢ·A USD notional** of each leg. Positive beta ⇒ go
**long** the foreign future (equivalently short USD). Notionals and contract
counts are signed (long +, short −). Empirically all five betas are positive
and CNH/EUR dominate — consistent with SGD's MAS trade-weighted basket.

OLS uses `numpy.linalg.lstsq` (rank-robust against the majors' collinearity)
with textbook `σ²·(XᵀX)⁻¹` standard errors. The majors are collinear, so the
**basket R²** is the headline hedge-quality measure; individual betas are less
stable and are shown with standard errors / t-stats rather than treated as
precise.

### 3. Weekly returns, ~3y lookback

Weekly **log** returns on the Friday-resampled (`W-FRI`) spot, non-overlapping
by default (honest standard errors), 156-week (~3y) lookback. Overlapping
5-business-day windows are supported via config (`overlapping: true`) and yield
more observations at the cost of autocorrelated residuals.

### 4. CNY proxies offshore CNH for return estimation

Yahoo serves no long *daily* history for the offshore CNH tickers
(`CNH=X` / `USDCNH=X` are intraday-only). Onshore `CNY=X` (USDCNY) has history
back to 2001 and tracks CNH spot returns closely, so it is the **return-
estimation feed** for the CNH leg. The *traded* instrument remains the CME
Standard-Size USD/CNH future; the artifact's leg records `yahoo_symbol: CNY=X`
so the proxy is transparent.

### 5. Contract sizing & rounding

USD notional per contract = `contract_size × spot_usd_per_unit` for
foreign-currency-sized futures (EUR/GBP/AUD/JPY); the Standard-Size USD/CNH
future is **USD-sized**, so its USD notional per contract is fixed at the
contract size (100,000 USD) regardless of spot. Target contracts = nearest
whole of `target_notional ÷ usd_per_contract`, rounding **halves away from
zero**. Per-leg residual = target − realized after rounding; the portfolio
**statistical** unhedged share is `1 − R²` (basis risk the basket can't span).

### 6. Carry shown, not optimised

Indicative annual carry per leg = `realized_notional × (foreign ON − USD ON)`
using configured overnight rates (`fx_hedge_advisor.yml`, with `as_of`). Carry
is **displayed only** — it is a V1 non-goal to optimise it.

### 7. Provider owns cache + 30-day staleness

`provide_fx_hedge_allocation` mirrors the regime provider: modes `cached` /
`refresh-if-stale` / `force-refresh`. `refresh-if-stale` recomputes when the
cached `run_date` is missing or **older than 30 days** (`max_age_days`),
otherwise reuses the saved artifact. `FxHedgeArtifactState.computed_fresh`
answers the required "freshly computed vs loaded from cache" question; the
report renders a badge from it. Compute failures fall back to the cached
allocation, tagged `error`.

## Consequences

- The hedge direction is unambiguous and economically sane (long the foreign
  basket = short USD = the correct hedge for a USD-overexposed SGD investor).
- The Risk → FX section always renders (populated / cache / stale / missing /
  error), never silently disappears — same pattern as the regime section.
- Reusing a cached run ≤30 days old means the displayed notional reflects the
  **AUM at compute time**, not necessarily today's AUM. This is intentional
  (the 30-day cache is the spec); a force-refresh re-pulls current AUM.
- Standalone risk/report views (plain `PortfolioReportInputs`) do **not** own
  FX data and render the "not yet computed" card — only the combined report
  (and the `fx-hedge-report` CLI) refresh it, so no Yahoo fetch fires as a
  side effect of a risk-only flow.

## Non-decisions / out of scope (V1)

- **Second-order cross-currency term.** The hedge neutralises the first-order
  USD/SGD exposure of the AUM; the hedge legs' own USD-P&L → SGD conversion is
  a second-order effect that is *not* modelled.
- Margin optimisation, transaction-cost optimisation, and carry optimisation.
- No order placement — read-only with respect to the broker (ADR 0001).
- Richer estimators (ridge/shrinkage for the collinear basket, robust
  regression) are deferred; plain OLS is the V1 spec.
