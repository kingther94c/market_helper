# Option Advisor Devplan

> **Now component #1 of the [Trade Advisor umbrella](trade_advisor.md)** — the
> shared advisor contract, registry, and interactive GUI live there; this file
> stays as the option engine's detailed reference.

Design memo + milestone plan for a **read-only, advisory-only** option-idea
research layer. Status: **M1+M2 landed — runnable MVP** (CLI + live data + tests);
M3–M5 open. Scope accepted in
[ADR 0007](../../decisions/0007-option-advisor-advisory-scope.md).

> **Landed (this iteration).** `market_helper/domain/option_advisor/`:
> `pricing.py` (pure-stdlib Black–Scholes), `contracts.py`, `providers.py`
> (CBOE/yfinance/synthetic), `signals.py`, `candidates.py`, `filters.py`,
> `ranking.py`, `service.py`, `__main__.py` (CLI); `configs/option_advisor/
> advisor_rules.yaml`; 26 hermetic tests. The MVP fetches **real option chains**
> (CBOE delayed JSON, free) — the original "model-only" assumption below was
> overtaken by the data research; model-only is now the *fallback* tier.

## 1. Purpose & non-negotiables

Scan selected underlyings (holdings + watchlist) and surface **ranked option
trade *ideas*** — never orders — each with thesis, structure, strike/expiry
logic, estimated payoff/Greeks, liquidity + event-risk checks, sizing guidance,
and a "why now". The module reads existing artifacts and writes only an HTML
section + a JSON/CSV artifact. It places nothing.

Inviolable constraints (inherited from this repo's governance):

- **Read-only w.r.t. the broker** ([ADR 0001](../../decisions/0001-read-only-broker-policy.md)).
  No order-entry / cancel / modify, ever. New data the advisor needs from IBKR
  (`reqSecDefOptParams`, `reqMktData`) are **read** ops only.
- **No opaque ML.** Rule-based heuristics first; every idea is explainable from
  named drivers (mirrors the regime engine's `top_contributors` discipline).
- **No multi-leg optimizer** until the rule-based core is validated.
- **Honest about missing data.** Where the chain / IV-surface / earnings feed
  is absent, the idea is *labelled* as model-only and capped at `MONITOR` — it
  must not pretend to have a live quote it never fetched. This mirrors the
  regime `data_mode` + `RegimeArtifactState{ok|stale|missing|engine_error}`
  honesty pattern and the per-position `option_greeks_status` enum.

This module is a **scope expansion**: `plan/backlog.md` and the regime devplan
currently park "trading-signal generation / allocation tilt suggestions" as
out-of-V1. ADR 0007 draws the line — *advisory research output* is in scope;
*execution* stays out of scope under ADR 0001 — and must be Accepted before
Milestone 1 lands code.

## 2. Idea taxonomy (the product model)

Every idea declares exactly one **category** so the reader can filter by intent:

| Category | Intent | Example structures |
|---|---|---|
| `INCOME` | harvest premium on a holding / fund an entry | covered call, cash-secured put, **carry short call/put** (naked premium; MONITOR-capped) |
| `HEDGE` | cap downside on an existing long | protective put, collar, **zero-cost collar** (buy put-spread, finance with a short call), put spread |
| `DIRECTIONAL` | express a defined-risk view | call spread (bull), put spread (bear) |
| `VOLATILITY` | trade IV level / term structure | calendar, straddle/strangle *(gated — needs chain)* |
| `CONVEXITY` | cheap tail / asymmetric payoff | long OTM call/put, ratio *(model-only until chain)* |

Each idea also carries a **label**: `PROCEED` (passes all hard filters, top
ranked), `MONITOR` (viable but blocked on a soft gate — e.g. needs live-chain
liquidity confirmation, or event risk unverified), or `REJECT` (failed a hard
filter; retained with the failing reason for the audit trail).

## 3. Architecture

Follows the existing dependency direction
(`cli → workflows → application → domain → data_sources / reporting`). The new
track is a sibling of `domain/regime_detection/`, and reuses the
`suggest/quadrant_policy.py` pattern (frozen decision dataclass + YAML-driven,
no-code tuning + free-text `notes` audit).

Pipeline = the five layers the goal asks for:

```
signals → candidate generation → risk filter → ranking → report
```

```
market_helper/domain/option_advisor/        # ✅ landed (M1+M2)
  contracts.py     # frozen dataclasses (§4) — data + advisory contracts
  pricing.py       # pure-stdlib Black–Scholes: price / greeks / IV solve / payoff
  providers.py     # CBOE (urllib) → yfinance → synthetic vol-surface; get_chain()
  structures.py    # build_* structure templates + payoff/breakeven/greeks math
  config.py        # load_rules() — YAML merged over DEFAULT_RULES
  signals.py       # build_context(): realized vol, IV rank, trend, regime, holdings
  candidates.py    # rule-based generation per category (regime-gated)
  filters.py       # liquidity / assignment / event / cost / sizing → FilterOutcome[]
  ranking.py       # score + label PROCEED/MONITOR/REJECT (top-N cap)
  service.py       # orchestrator → OptionAdvisoryResult (+ audit trail)
  __main__.py      # runnable CLI: python -m market_helper.domain.option_advisor
configs/option_advisor/
  advisor_rules.yaml   # ✅ enabled strategies, thresholds, ranking weights, gates
market_helper/reporting/                     # ⬜ M3
  option_advisor_html.py   # render_option_advisor_tab(vm) + build_*_view_model(...)
```

Touch-points in existing code (all additive):

- `application/portfolio_monitor/contracts.py` — add `OptionAdvisorInputs`
  (`from_namespace` classmethod) and an `option_advisor_state:
  OptionAdvisorArtifactState` field on `PortfolioReportData` (always present,
  same pattern ADR 0005 used to retire `Optional[regime_view_model]`).
- `application/portfolio_monitor/services.py` — build the advisor view-model in
  `_assemble_report_data` **after** the risk + regime view-models exist (it
  consumes both), guarding on artifact existence like the regime provider does.
- `reporting/portfolio_html.py` — insert `ReportSection(key="option-advisor",
  …)` into `build_portfolio_report_document` **after `regime`, before
  `artifacts`** (section order is explicit; the sticky nav auto-derives from the
  list, so no separate nav edit). A `build_option_advisor_section_body` helper
  renders ok / empty / `engine_error` cards exactly like the regime fallback.
- `cli/main.py` — new `option-advisor-report` subcommand (standalone JSON/HTML
  artifact for ad-hoc runs); the combined report needs no new CLI flags (it
  already passes positions / returns / regime paths).

**Pricing engine**: `pricing.py` is pure stdlib — `statistics.NormalDist().cdf`
/ `.pdf` for the normal CDF/PDF, no numpy/scipy required, **zero new runtime
dependencies** (so no `env.yml` change). Black–Scholes price, the five Greeks,
breakeven(s), and a discrete payoff curve for the report chart. This is the only
genuinely new math; everything else composes existing analytics.

## 4. Data contracts

Stdlib `@dataclass(frozen=True)`, `float | None` for nullable metrics,
`field(default_factory=…)` for mutable defaults, `as_of: str`, an `internal_id`
key where one exists — matching `risk_html.RiskInputRow` /
`suggest.quadrant_policy.RegimePolicyDecision`. Sketches (final field lists
firm up in Milestone 1):

```python
@dataclass(frozen=True)
class UnderlyingContext:
    """Everything the rules need about one underlying, assembled from existing artifacts."""
    internal_id: str
    symbol: str
    as_of: str
    spot: float | None
    realized_vol_1m: float | None
    realized_vol_3m: float | None
    realized_vol_1y: float | None
    held_iv: float | None            # from PositionSnapshot.option_implied_vol (held opts only)
    iv_rank: float | None            # None until the IV-history cache lands (GAP)
    trend_state: str                 # "up" | "down" | "chop" from SMA(50/200) on Yahoo prices
    regime_label: str                # FinalRegimeResult.final_regime
    regime_confidence: str           # "High" | "Medium" | "Low"
    crisis_flag: bool
    held_qty: float
    held_delta_exposure_usd: float | None
    weight: float                    # share of funded AUM (excludes opts/futures — see gotchas)
    sector: str
    policy_drift: float | None       # vs allocation policy, from RiskReportViewModel

@dataclass(frozen=True)
class OptionLeg:
    right: str                       # "C" | "P"
    action: str                      # "buy" | "sell"
    strike_rule: str                 # "delta:0.30" | "pct_otm:0.05" | "abs:450"
    resolved_strike: float | None    # None until a chain resolves the rule (model picks nearest)
    expiry_rule: str                 # "dte:30-45"
    resolved_expiry: str | None
    qty_ratio: int                   # legs per structure unit
    est_iv: float | None             # vol input used for the model estimate
    est_price: float | None          # BS model price (NOT a live quote)
    est_delta: float | None
    est_gamma: float | None
    est_theta: float | None
    est_vega: float | None

@dataclass(frozen=True)
class OptionIdea:
    idea_id: str
    as_of: str
    underlying_id: str
    underlying_symbol: str
    category: str                    # INCOME | HEDGE | DIRECTIONAL | VOLATILITY | CONVEXITY
    structure_type: str              # COVERED_CALL | CSP | PROTECTIVE_PUT | COLLAR | PUT_SPREAD | ...
    legs: list[OptionLeg]
    thesis: str
    why_now: str
    expiry_strike_logic: str         # human-readable selection rule
    est_net_debit_credit: float | None
    est_max_loss: float | None
    est_max_gain: float | None
    est_breakevens: list[float] = field(default_factory=list)
    est_payoff_curve: list[tuple[float, float]] = field(default_factory=list)  # (spot, P&L)
    net_greeks: dict[str, float] = field(default_factory=dict)
    liquidity: "LiquidityAssessment" | None = None
    event_risk: "EventRisk" | None = None
    sizing: "SizingGuidance" | None = None
    score: float = 0.0
    label: str = "MONITOR"           # PROCEED | MONITOR | REJECT
    rationale: str = ""              # free-text "why", like RegimePolicyDecision.notes
    drivers: list[tuple[str, float]] = field(default_factory=list)   # named signal contributions
    filters_applied: list["FilterOutcome"] = field(default_factory=list)  # the audit trail
    data_status: str = "model_only"  # model_only | chain_validated

@dataclass(frozen=True)
class FilterOutcome:                 # one row of the "why generated / why rejected" trail
    filter_name: str
    passed: bool
    severity: str                    # "hard" | "soft"
    detail: str

@dataclass(frozen=True)
class OptionAdvisoryResult:
    as_of: str
    ideas: list[OptionIdea]          # all of them, every label — rejected kept for audit
    universe_scanned: list[str]
    data_mode: str                   # "model_only" | "chain_available"
    config_version: str
    warnings: list[str] = field(default_factory=list)
```

Supporting frozen records: `LiquidityAssessment(status, bid_ask_pct|None,
open_interest|None, volume|None, notes)` — `status="unknown_no_chain"` until the
chain adapter lands; `EventRisk(symbol, next_earnings_date|None,
days_to_earnings|None, event_status)` — `event_status="unverified"` until the
earnings adapter lands; `SizingGuidance(basis, max_contracts|None,
notional_pct_of_aum, capital_at_risk_usd, notes)`.

Optional CSV export reuses the `POSITION_REPORT_HEADERS` pattern: a module-level
`OPTION_IDEA_HEADERS` list driving `csv.DictWriter` + `asdict(row)`.

### Data availability (drives the milestone order)

| Input | Status today | Source |
|---|---|---|
| Held-option delta / IV / underlying price + `option_greeks_status` | **EXISTS** | TWS `modelGreeks` → `PositionSnapshot` |
| Realized vol (1m/3m/1y/EWMA, log-return, 252-annualized) | **EXISTS** | `domain/portfolio_monitor/services/volatility.py` |
| Daily price history (5y) for trend / RV | **EXISTS** | `YahooFinanceClient.fetch_price_history` + return cache |
| Regime label / confidence / crisis flag | **EXISTS** | `FinalRegimeResult` / `RegimeArtifactState` |
| Per-position weight / exposure / policy drift | **EXISTS** | `RiskReportViewModel` |
| Universe + watchlist | **EXISTS** | `configs/security_universe.csv`, `security_reference.csv` |
| Option **chain** (strikes/expiries, per-strike bid/ask/OI/greeks) | **EXISTS** | **CBOE delayed JSON** (free, no key, stdlib `urllib`) primary; yfinance fallback; `ib_async` `reqSecDefOptParams` = M5 |
| IV rank / percentile / term-structure | **PARTIAL** | per-strike IV from the chain; live IV-rank from an IBKR underlying snapshot; historical IV-rank cache = M5 |
| Synthetic vol-surface fallback (spot + ATM IV, user-overridable) | **EXISTS** | `providers.build_synthetic_chain` (skew/term defaults; user can override spot & iv) |
| Earnings / ex-div calendar | **GAP** | new provider adapter — Tradier/FMP/Yahoo (M5) |

**Data ladder (as built):** live CBOE chain (`data_mode=live_chain`, can
PROCEED) → yfinance fallback → **synthetic** chain from spot + ATM IV
(`data_mode=synthetic`/`user_override`, **capped at MONITOR** — honest about
being model-only). The user can override `spot` and `iv` to force the synthetic
path. `event_risk.event_status="unverified"` until an earnings feed lands (M5).
Community data-source research (15+ sources) is summarized in the landed-work
note; CBOE won on free + full-greeks + zero-key + stdlib-only.

## 5. Configuration (YAML, no-code tuning)

Mirrors `configs/regime_detection/quadrant_policy.yml` + its merge-over-defaults
loader. `configs/option_advisor/advisor_rules.yaml`:

```yaml
strategies:
  covered_call:   { enabled: true,  target_delta: 0.30, dte: [30, 45], min_round_lots: 1 }
  cash_secured_put: { enabled: true, target_delta: 0.27, dte: [30, 45] }
  protective_put: { enabled: true,  target_delta: 0.15, dte: [60, 120], hedge_weight_trigger: 0.08 }
  collar:         { enabled: true }
  vertical_spread: { enabled: true, long_delta: 0.40, short_delta: 0.20, dte: [30, 45] }
filters:
  min_premium_over_costs: 1.5      # est credit must clear (commission + half-spread) × this
  max_notional_pct_aum: 0.05       # sizing cap, on FUNDED AUM (excludes opts/futures)
  liquid_underlyings_only: true    # gate to known-liquid names until the chain adapter lands
ranking:
  weights: { yield_or_hedge_eff: 0.4, regime_align: 0.25, liquidity_conf: 0.2, event_penalty: 0.15 }
regime_gates:                      # don't cap upside in strong risk-on; no naked-ish risk in crisis
  suppress_income_when: ["Goldilocks:High"]
  hedge_bias_when:       ["crisis_flag", "Deflationary Slowdown"]
```

Editing this file re-tunes strategy enablement, strike/DTE targets, filter
thresholds, and ranking weights **without touching Python** — the same property
that lets a regime signal be retuned from YAML.

## 5b. Premium value screen (INCOME) — research basis

The rule-based screen for *selling* premium ranks INCOME ideas by **value**, grounded
in two established results (so "普通版怎么筛选" is researched, not arbitrary):

1. **Theta sweet spot — when to be in the trade.** Time decay is non-linear: it
   accelerates as expiry nears, steepest in the final ~30 days, fastest in the last
   week; **>70% of the time premium erodes in the final three weeks**. The income
   window is therefore **~30–45 DTE entry** (theta meaningful, gamma/pin risk still
   manageable) and **management at ~21 DTE** (bank the bulk of the decay, exit before
   the gamma / binary-event week). [Cboe Options Institute; daystoexpiry; projectfinance]
2. **The edge is the variance risk premium (VRP), not "high IV".** Implied vol
   systematically exceeds the realized vol that follows; that gap (**VRP = IV − RV**)
   is the structural reason short-premium earns a positive expected return. The popular
   "sell when IV-rank > 50" heuristic is fragile (one IV spike distorts IV-rank for a
   year), so we rank by **IV/RV richness** — is implied rich vs what the underlying is
   actually realizing? A rich premium with *negative* VRP (IV < RV) is poor seller value
   and is scored down. [predictingalpha; volradar; Quantpedia VRP effect]

**Implementation.** `premium_screen` config (`target_yield_annualized`, `vrp_ratio_span`,
`min_vrp_ratio`, `manage_dte`) drives `ranking._efficiency`: for INCOME the score is the
**geometric mean of annualized yield × VRP richness** (both must be decent), surfaced as
`yield` + `IV/RV` on the card with a "manage ~21 DTE" note. IV comes from the fetched
chain, RV from `domain/portfolio_monitor/services/volatility.py` — **no new IV-history
cache needed**. (IV-percentile over a history cache stays a future refinement; the AI Plus
pane covers open-ended discovery and can crystallize a tuned screen back into this config.)

Sources: [daystoexpiry — theta DTE guide](https://www.daystoexpiry.com/blog/theta-decay-dte-guide) ·
[projectfinance — option theta](https://www.projectfinance.com/theta/) ·
[predictingalpha — IV vs RV](https://www.predictingalpha.com/implied-vs-realized-volatility/) ·
[volradar — IV vs RV](https://volradar.com/learn/implied-vs-realized-volatility) ·
[Quantpedia — volatility risk premium](https://quantpedia.com/strategies/volatility-risk-premium-effect)

## 6. Audit trail

No new mechanism — reuse the regime engine's three-part pattern:

1. `OptionIdea.rationale` — free-text "why", like `RegimePolicyDecision.notes`.
2. `OptionIdea.drivers: list[tuple[name, value]]` — named signal contributions,
   like `FinalRegimeResult.top_contributors`.
3. `OptionIdea.filters_applied: list[FilterOutcome]` — every gate it passed or
   failed, with `severity` + `detail`. **Rejected ideas are retained** in
   `OptionAdvisoryResult.ideas`, so "why was X *not* suggested" is always
   inspectable in the report's collapsible audit panel.

## 7. Validation (Milestone 4)

- **Unit — payoff & Greeks sanity**: BS put-call parity; `delta∈[0,1]` calls /
  `[-1,0]` puts; `gamma,vega > 0`; long-option `theta < 0`; breakeven arithmetic
  for verticals/collars; payoff-curve endpoints = analytic max-gain/max-loss.
- **Unit — filtering & ranking**: deterministic given fixtures — assignment-risk
  flag fires for short ITM near expiry; sizing cap rejects when one contract
  already exceeds `max_notional_pct_aum`; ranking order stable; reject reasons
  populated.
- **Backtest where data permits** (rule evaluation, *not* a P&L promise):
  covered-call-overwrite and protective-put rules replayed on a held name's 5y
  Yahoo history with **BS-modeled premia** (clearly labelled model-based, since
  historical option quotes aren't available), compared against baselines —
  **buy-and-hold, always-covered-call, always-protective-put** — exactly the
  comparison the goal asks for. Artifacts land in `data/research_artifacts/`
  (gitignored outputs; pin small fixtures under `tests/`).
- **Sensitivity**: transaction cost (commission + half-spread sweep) and
  assignment/earnings exposure — show idea ranking stability, log what gets
  dropped (no silent truncation).

## 8. Milestones

Each is a small, independently reviewable PR. Every PR updates `plan/current.md`
(governance rule).

- ✅ **M0 — Scope decision.** ADR 0007 Accepted; backlog/regime "deferred
  trading signals" lines reconciled to the advisory/execution boundary.
- ✅ **M1 — Contracts + pricing.** `contracts.py`, `pricing.py` (pure-stdlib BS
  + greeks + IV solver), `config.py` (`advisor_rules.yaml` loader). Unit tests
  for pricing/greeks/IV round-trip.
- ✅ **M2 — Runnable rule-based advisor.** `providers.py` (CBOE/yfinance/
  synthetic), `structures.py`, `signals/candidates/filters/ranking/service`, and
  a `python -m market_helper.domain.option_advisor` CLI (JSON/console). Runs on
  **live CBOE chains** (not model-only); user-overridable spot/IV fallback.
  Hermetic unit tests for filtering / sizing / ranking / synthetic surface.
  *Delta vs original plan: real chain data arrived in M2, so the model-only
  assumption was relaxed to a fallback tier.*
- ⬜ **M3 — Report / dashboard section.** `option_advisor_html.py` +
  `ReportSection` wiring + `PortfolioReportData.option_advisor_state` + service
  build + ok/empty/error card. Dashboard nav auto-includes it. `test_combined_html`
  extended with an `#option-advisor` assertion.
- **M4 — Historical validation.** Backtest harness + baseline comparison +
  cost/assignment sensitivity (§7). Research artifact + pinned fixtures.
- **M5 — Refinement backlog (each a discrete ask).** Read-only chain adapter
  (`reqSecDefOptParams` + market-data snapshot) → real strikes / bid-ask / OI /
  vol → flips `data_mode` to `chain_available` and lets `MONITOR`→`PROCEED`;
  IV-rank/percentile + term-structure cache; earnings/ex-div adapter; richer
  liquidity scoring; *then, only if validated*, a constrained multi-leg
  optimizer (still advisory).

## 9. Guardrails (carry into every PR)

- Advisory only; no broker write path; chain/quote pulls are read ops (ADR 0001).
- Rule-based + explainable; no opaque ML; no optimizer before M5.
- Never present a model estimate as a live quote — `data_status` /
  `liquidity.status` / `event_status` must say what was and wasn't confirmed.
- Sizing % is on **funded AUM (stock-like + cash; excludes options/futures)** —
  the existing AUM-denominator gotcha.
- Keep the report section's missing-data card actionable, like the regime card.
