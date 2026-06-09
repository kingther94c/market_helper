# Devplan: FX Hedging Advisor (Risk → FX)

Track-level architecture for the SGD-base FX hedge advisor. Governance +
reading order in [`AGENTS.md`](../../../AGENTS.md); the load-bearing conventions
are pinned in [ADR 0006](../../decisions/0006-fx-hedge-regression-convention.md).

## Purpose

Convert a desired USD/SGD hedge amount (default: the portfolio's funded USD AUM)
into a **target FX allocation** across liquid CME FX futures (EUR/GBP/AUD/JPY/CNH
vs USD), via a weekly-return regression of the SGD/USD spot return on the
instruments' spot returns. Answers: *to hedge 100% of the USD/SGD exposure, how
much notional / how many contracts of each instrument?*

## Ownership

| Concern | Home |
|---|---|
| Compute + artifact + cache provider | `market_helper/domain/portfolio_monitor/services/fx_hedge_advisor.py` |
| Instrument registry + params | `configs/portfolio_monitor/fx_hedge_advisor.yml` |
| Rendering (Risk → FX section) | `market_helper/reporting/fx_hedge_html.py` |
| Report wiring (`fx_hedge_state`) | `application/portfolio_monitor/contracts.py` + `services.py` (`_load_fx_hedge_state`) |
| Section placement | `reporting/portfolio_html.py` (appended under the Risk section) |
| CLI / standalone facade | `cli/main.py` `fx-hedge-report` → `workflows.generate_report.generate_fx_hedge_report` |
| Artifact | `data/artifacts/portfolio_monitor/fx_hedge/fx_hedge_allocation.json` (gitignored) |

## Data flow

```
configs/.../fx_hedge_advisor.yml ─┐
                                  ▼
 Yahoo daily spot (per instrument) ─► normalise to USD-per-unit (invert where needed)
   ─► weekly W-FRI log returns ─► align panel ─► OLS (betas, SEs, R²)
   ─► × hedge notional ─► ÷ USD-per-contract ─► round to whole contracts
   ─► carry from configured ON rates ─► FxHedgeAllocation (JSON artifact)
                                  ▼
 provide_fx_hedge_allocation (cached / refresh-if-stale[30d] / force-refresh)
   ─► FxHedgeArtifactState (ok / stale / missing / error, computed_fresh)
                                  ▼
 render_fx_hedge_section ─► Risk → FX card (badge + legs + totals + conventions)
```

## Key design points (see ADR 0006 for the full rationale)

- **Value-in-USD basis** (USD per 1 unit of currency); inverse of the repo's
  `fx_usdsgd_eod`. Hedge = **long** the foreign basket (short USD) — positive
  betas, signed notionals/contracts.
- **CNY proxies offshore CNH** for return estimation (Yahoo lacks long daily
  CNH history); the traded instrument is still the CME USD/CNH future.
- **USD-sized CNH future** vs foreign-currency-sized majors → branch in the
  USD-per-contract computation.
- **30-day cache**: the provider mirrors the regime provider; `computed_fresh`
  drives the "Freshly computed / Loaded from cache (N days old)" badge.
- **Hedge notional** defaults to `risk_view_model.summary.funded_aum_usd`
  ("full AUM exposure"); falls back to the configured default for AUM ≤ 0.
- Plain risk/report flows resolve the FX artifact path to `None` and skip the
  provider (no side-effect Yahoo fetch); only the combined report + CLI refresh.

## Tests

- `tests/unit/domain/portfolio_monitor/test_fx_hedge_advisor.py` — config,
  beta recovery on synthetic data, lookback/min-obs, overlapping vs calendar
  weeks, IMM expiry roll, contract rounding, full allocation math/carry signs,
  artifact round-trip, provider caching/staleness/error-fallback.
- `tests/unit/reporting/test_fx_hedge_html.py` — populated / cache-badge /
  missing / error renders + conventions block.
- `tests/unit/reporting/test_combined_html.py` — FX section under Risk
  (populated + default-sentinel unavailable card).

All hermetic — a synthetic spot loader + injected `now` keep the suite
network-free.

## Backlog / not in V1

- **Current FX exposure lookthrough** (symbol → currency-of-risk → per-ccy weight)
  — not computed today; required by the Trade Advisor **FX Hedge decision panel**
  (baseline mix + exposure + carry → tilt). See
  [`trade_advisor.md`](trade_advisor.md) §5.2.
- Second-order cross-currency (hedge-leg USD-P&L → SGD) term.
- Margin / transaction-cost / carry optimisation.
- Shrinkage / robust estimators for the collinear basket.
- Dashboard "Refresh FX Hedge" action button (today: combined-report
  refresh-if-stale + the `fx-hedge-report` CLI).
- Wiring live AUM into a cache *rescale* so a reused run reflects today's AUM
  without a full recompute.
