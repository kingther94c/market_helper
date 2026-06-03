# Trade Advisor — Development Plan

Goal-setting-altitude plan for a **`trade_advisor` umbrella**: one advisory
surface that turns portfolio + market + regime context into ranked, explained,
**read-only** trade *ideas* across several advisor types, with an **interactive
GUI** to explore them, tweak inputs, and watch the computed feedback update —
plus a static snapshot in the daily report.

This is intentionally **not** an implementation spec. It fixes the *objective*,
the *hard constraints*, the *component family*, and especially the *UI /
interaction design*; it leaves data-shapes, signatures, and file layout to each
milestone's own design pass. The existing
[Option Advisor](option_advisor.md) becomes the first component under this
umbrella and is the proof that the shared pattern works.

---

## 1. Objective

A single place — in the GUI and in the report — where the user can ask *"given
what I hold, the regime, and the market, what option/FX/rebalance moves are
worth considering, and why?"* and get back **ranked, labelled, fully-explained
ideas they can poke at**, never orders. Every idea is reproducible, auditable,
and honest about the quality of the data behind it.

Two things make this more than "more report sections":

1. **It is interactive.** The user supplies inputs (watchlist, overrides,
   risk appetite, what-if tweaks) and the computed feedback (payoff, Greeks,
   risk, sizing) responds live. The current dashboard is mostly read-only;
   trade_advisor is the first genuinely two-way surface.
2. **It is a family, not one feature.** Options, roll reminders, FX-carry tilts,
   general trade ideas, and future advisors all plug into **one framework** and
   render through **one card/feedback UI**, so adding an advisor is cheap and
   the user learns the interaction once.

---

## 2. Hard constraints (the only non-negotiables)

These are fixed inputs to every milestone; everything else is open to design.

- **Read-only / advisory-only.** No order placement, modification, or
  cancellation, ever — anywhere in this tree ([ADR 0001](../../decisions/0001-read-only-broker-policy.md),
  [ADR 0007](../../decisions/0007-option-advisor-advisory-scope.md)). The GUI
  shows ideas + decision *labels*; it never produces an order ticket.
- **Architecture compatibility.** Stay inside the existing layering
  (`cli → workflows → application → domain → data_sources / reporting /
  presentation`). Engines/analytics in `domain`; dashboard orchestration in
  `application`; UI in `presentation`; static rendering in `reporting`. Reuse —
  don't fork — the `suggest/`, regime, and option_advisor patterns.
- **GUI = extend the existing NiceGUI dashboard; HTML stays the deliverable**
  ([ADR 0002](../../decisions/0002-html-deliverable-dashboard-entry.md)). New
  interactive pages register alongside `register_portfolio_page(...)`; static
  output embeds in the combined HTML report. **No new UI framework.**
- **Bounded interaction — no free-form input.** There is **no AI/NLP layer** to
  interpret arbitrary input, so **every control is a fixed option set or a
  validated, bounded numeric field** (dropdown / toggle / chip / segmented
  control / stepper / range-capped slider). No free-text prompts, no
  natural-language "ask". The user explores **within rails**; invalid states are
  unreachable by construction, and the compute engine only ever receives clean,
  in-range inputs. (Free-form input is revisited only if/when an AI layer lands.)
- **Honesty is mandatory.** Every idea carries a `data_mode` (live vs
  model/synthetic), a `PROCEED / MONITOR / REJECT` label, and an audit trail of
  why it was generated or filtered. Model-only ideas never reach `PROCEED`.
  (Mirrors the regime engine's `data_mode` + option_advisor's filter trail.)
- **Rule-based first; explainable; no opaque ML.** No optimizer/black-box until
  the rule layer is validated.
- **Regime is context, not an allocator.** Consume regime/risk signals; never
  turn them into auto-execution (the regime guardrails still hold).
- **Conda `py313`.** New runtime deps go into `env.yml` in the same change.
- **Funded-AUM denominator excludes options/futures** (existing risk gotcha) for
  all sizing.

---

## 3. The advisor family (scope)

Each is described at intent level; mechanics are each milestone's job.

| Advisor | Question it answers | Status |
|---|---|---|
| **Option Advisor** | "What option structures fit my holdings + regime + vol?" | ✅ built ([devplan](option_advisor.md)) — folds in as component #1 |
| **Roll Reminder** | "Which of my *existing* option positions need attention (DTE, ITM/assignment, ex-div) and what's the roll?" | planned |
| **FX Hedging Advisor** (+ **FX Carry Tilt** sub-module) | "What's the USD/SGD hedge target across CME FX futures — and which ccy to tilt by carry?" | ✅ built ([devplan](fx_hedge_advisor.md), [ADR 0006](../../decisions/0006-fx-hedge-regression-convention.md)); **spans both surfaces**. Carry-tilt sub-module planned |
| **Trade Ideas** (general) | "Non-option moves worth considering: rebalance vs policy drift, regime-aligned sleeve tilts, relative-value pairs." | planned (scope to firm up) |
| **(extensible)** | earnings-vol, tax-loss harvest, cash-deployment, … | open — a registry makes these additive |

**Design principle:** the umbrella owns a small **shared advisor contract** so
all of the above produce the *same shape* of suggestion (label, category,
thesis, why-now, rationale, drivers, audit, data_mode, sizing, decision hooks).
That uniformity is what lets one GUI render all of them and lets "others not yet
decided" drop in without UI work.

**Two-surface advisors (worked example: FX Hedging Advisor).** Some advisors
live on *both* surfaces over **one shared artifact**: the **report** side shows
only the **target allocation**, refreshed on a slow **~30-day stale** cadence;
the **interactive** side can **trigger a refresh on demand** (force-refresh) and
shows the **full detail** (per-ccy hedge betas / R² / contracts / expiries /
carry). Either refresh writes the same artifact, so the report always loads the
latest. This is the concrete proof of §5.1's two-surface model and the template
for any advisor that warrants both a glance and a workbench. The **FX Carry
Tilt** sub-module hangs off this advisor (see §5.5) — it is **not** a standalone
family member.

---

## 4. Architecture at altitude

- **`market_helper/trade_advisor/`** — the umbrella the user asked for: the
  shared **advisor protocol + suggestion contract + registry**, plus a thin
  **context bus** that assembles the common inputs once (portfolio snapshot,
  regime state, risk view-model, market-data providers) and hands them to every
  advisor. Each component advisor is a registered plugin.
- **Component engines** live as domain analytics (the option engine already does,
  at `domain/option_advisor/`). *Decision for M1: whether to physically move
  option_advisor under the umbrella or register it in place* — recommend
  register-in-place first (zero churn), re-home later only if it earns its keep.
- **`application/trade_advisor/`** — dashboard-facing orchestration: run
  advisors, collect suggestions, drive progress events, and own the **decision
  journal** (accept/monitor/reject history — a local artifact, never a broker
  action). Reuses the `QueryService` / `ActionService` split.
- **`presentation/dashboard/pages/trade_advisor.py`** — the interactive page,
  registered next to the portfolio page; built from the existing NiceGUI
  primitives (`render_action_card`, status badges, `.pm-card`) + Plotly (already
  the dashboard's charting lib).
- **`reporting/`** — a static **Trade Advisor snapshot** section in the combined
  HTML report (for the daily cron + Tailscale cross-device view).

Net: the umbrella is a **coordinator + shared contract + two presentation
hooks**, not a monolith. Adding an advisor touches the registry + one engine +
(optionally) a per-advisor sub-view, nothing else.

---

## 5. UI / UX design

The emphasis of this plan. Two surfaces, one mental model.

### 5.1 Two surfaces

- **Interactive (NiceGUI, localhost / Tailscale):** where the user *works* —
  picks inputs, runs advisors, tweaks what-if, records decisions.
- **Static snapshot (combined HTML report):** where the user *reviews* — a
  read-only roll-up of current PROCEED/MONITOR items, mirrored to GDrive and
  reachable cross-device. No inputs; links back to the live page.

### 5.2 Information architecture

A new top-level **"Advisor"** entry next to Overview / Performance / Risk /
Regime. Inside it, a unified **Inbox** plus one sub-tab per advisor:

```
┌─ Market Helper ───────────────────────────── [Live Refresh] [Refresh Regime] ─┐
│  Overview  Performance  Risk  Regime  ▸ ADVISOR ◂  Artifacts                   │
├───────────────────────────────────────────────────────────────────────────────┤
│  Inbox │ Options │ Rolls │ FX Hedge │ Ideas            data: ● live  ⟳ 14:32   │
│  ┌──────────── Inputs ───────────┐  ┌──────────── Results (ranked) ─────────┐  │
│  │ Universe: [holdings ✓][watch+]│  │ [PROCEED] HEDGE · Collar · SPY  0.91  │  │
│  │ AUM:  [ 250,000 ]             │  │ [PROCEED] DIR  · CallSpd · QQQ  0.90  │  │
│  │ Regime: Reflation (auto) [⟳]  │  │ [MONITOR] INC  · CovCall · SPY  0.49  │  │
│  │ Override IV/spot:  [SPY ▸]    │  │ [REJECT ] INC  · CSP     · SPY  —     │  │
│  │ Strategies: ☑CC ☑CSP ☑PP …    │  │  … grouped by label, sortable          │  │
│  │ Risk:  delta◍── dte◍──        │  └────────────────────────────────────────┘  │
│  │           [ Run Advisor ▶ ]   │     ↑ click a row → detail panel (5.4)        │
│  └───────────────────────────────┘                                              │
└───────────────────────────────────────────────────────────────────────────────┘
```

The **Inbox** aggregates the top PROCEED/MONITOR items across *all* advisors so
the user has one "what should I look at today" list; the per-advisor tabs are
for focused work.

### 5.3 Interaction model (input → compute → feedback)

Reuse the established **action-card loop** (status badge → progress → last
output) so running an advisor feels like the existing Live/Flex refresh:

1. **Inputs** auto-seed from live state (holdings, regime, risk weights) and are
   overridable **only through bounded controls** — never free text:
   - *Universe*: multi-select of current holdings + a **validated symbol picker**
     (autocomplete against the security universe / contract search), not an
     arbitrary text box.
   - *AUM*: numeric field with a min + step (or auto from the portfolio).
   - *Regime*: a **select** — auto from the engine; manual override chooses from
     the known regime labels.
   - *Strategies*: per-strategy **toggles**.
   - *Risk targets* (delta / DTE): **range-capped sliders** (fixed min/max/step).
   - *Overrides* (IV / spot): **steppers / capped sliders** within a validated
     band (e.g. IV in [floor, cap]; spot within ±N% of live).
2. **Run** streams progress (per-symbol, per-advisor) — never a frozen spinner.
3. **Results** arrive as ranked cards, grouped by label, with a persistent
   **data-mode banner** (● live chain / ◐ live-anchored / ○ synthetic / ✎ your
   override) so honesty is always on screen.

### 5.4 Idea card + detail (how computed feedback is shown)

Collapsed card = the headline; expanded = the full computed feedback.

```
┌ [PROCEED] HEDGE · Collar · SPY ───────────────── score 0.91 · ● live ─┐
│ Buy P718 / Sell C791 · ~60DTE · net debit $96/unit · BE 760.5          │
│ thesis: finance downside on the SPY long by capping upside             │
│ ▸ expand: payoff · greeks · liquidity · sizing · audit · what-if       │
└────────────────────────────────────────────────────────────────────────┘
        ▼ expanded
   ┌ Payoff (interactive Plotly) ─────────┐  ┌ Greeks ─────────┐
   │   P&L ┆      ___________              │  │ Δ +55  Γ -0.33  │
   │       ┆     /                         │  │ Θ -3.3  V -11.6 │
   │  0 ───┼────/──────●BE────── spot      │  └─────────────────┘
   │       ┆  / 718        791             │  ┌ Sizing ─────────┐
   │  hover: at S=740 → P&L −$1,840        │  │ 2 lots (held)   │
   └───────────────────────────────────────┘  │ risk $9,550     │
   what-if:  strike[718▾] expiry[Jul31▾] qty[2▾] IV[+0%]  spot[759]│
             └ drag any control → payoff/greeks/BE recompute live ─┘
   liquidity: ● ok (spread 0.5%, OI 229)     event: earnings n/a (unverified)
   audit ▸ why generated / why not PROCEED:  [liquidity ✓][cost ✓][sizing ✓]…
   decision:  [ Proceed ]  [ Monitor ]  [ Reject ]   + note ▢
```

The load-bearing UX ideas:

- **Live what-if — all via bounded controls.** Strike and expiry are
  **dropdowns populated from the actual chain** (discrete by nature); quantity is
  a **stepper** capped by the sizing rule; IV / spot are **steppers or
  range-capped sliders** within a validated band. Changing one recomputes payoff,
  Greeks, breakevens, and sizing *in place* — so the user explores the structure
  instead of reading a fixed recommendation, but can never enter an out-of-range
  or unparseable value. (Cheap: the pricing math is already pure + fast.)
- **Payoff as the centerpiece.** An interactive P&L-vs-spot chart with hover
  read-outs and breakeven/strike markers, optionally overlaid with a baseline
  (buy-and-hold / unhedged) so the *marginal* effect is visible.
- **Sensitivity on demand.** Toggle the x-axis to vol or days-to-expiry to see
  P&L decay / vega exposure, not just terminal payoff.
- **Audit is one click, always available.** The filter trail (each
  pass/fail + reason) is how the user trusts a PROCEED and understands a REJECT.
- **Decision controls, not order buttons.** Proceed/Monitor/Reject + a note
  write to the **decision journal** (history + the Inbox + the static snapshot).
  This is the closest the product comes to "action" — and it's purely a record.

### 5.5 Per-advisor surfaces (same frame, different body)

- **Roll Reminder:** a positions-by-expiry table — DTE countdown, ITM /
  assignment / ex-div flags, and a suggested roll per row; row-expand reuses the
  same payoff/greeks/what-if panel comparing *current vs rolled*. "Snooze /
  monitor" instead of proceed.
- **FX Hedging Advisor:** the **report** card shows the target hedge allocation
  (cached ~30d); the **interactive** view adds the full detail — per-ccy hedge
  ratios (betas) + R², contract counts, expiries, indicative carry — plus a
  **Refresh now** trigger (force-refresh the shared artifact). Its **FX Carry
  Tilt** sub-module ranks currencies by **futures-implied carry** (or
  overnight-rate carry) and suggests a tilt *on top of* the hedge, with a
  before/after exposure view. Decision = "adopt tilt / monitor / dismiss".
- **Trade Ideas:** rebalance/relative-value cards; expand shows the drift-vs-
  policy or pair chart instead of an option payoff.

Same card chrome, same label/audit/decision controls — only the **body** differs
per advisor, which is exactly what the shared contract buys us.

### 5.6 Cross-device & persistence

Interactive page is localhost-bound (Tailscale Serve for remote, per existing
setup). The decision journal + the latest snapshot persist as local artifacts
and mirror to GDrive like other reports, so the static "what did I flag" view is
reachable anywhere without exposing the interactive controls.

---

## 6. Data & honesty

Reuse the option_advisor provider ladder (live → fallback → synthetic, all
user-overridable) and generalize it: each advisor declares the freshness of its
inputs, the UI surfaces it, and nothing model-derived is dressed up as live. FX
carry needs rate/forward data; roll reminder reads already-ingested held-option
Greeks; trade ideas read the existing risk/regime artifacts — **prefer existing
in-repo data before adding any provider**, and when a provider is added it's
read-only and declared in `env.yml`.

---

## 7. Validation

- Reuse the option_advisor test discipline: pure math unit-tested; deterministic
  ranking/filter tests; hermetic (no network) via synthetic/override fixtures.
- Per-advisor backtest vs **simple baselines** where data permits (covered-call
  vs buy-and-hold; carry tilt vs equal-weight FX; rebalance vs do-nothing).
- A **what-if-matches-engine** test class: the UI's live recompute must equal the
  engine's batch output for the same inputs (no drift between display and truth).
- Keep the full unit suite green on every milestone.

---

## 8. Milestones (each small, reviewable; sequenced for early proof)

1. ✅ **M1 — Umbrella + shared contract.** `market_helper/trade_advisor/`:
   `Advisor` protocol, shared `Suggestion` / `AdvisorResult` / `AdvisorContext`
   contracts, `AdvisorRegistry`, and an option-advisor adapter (registered in
   place — **no behavior change**). 8 tests; full unit suite green (635).
2. ✅ **M2 — Interactive shell + live what-if.** NiceGUI `/advisor` page
   (bounded controls → Run → ranked cards → Plotly payoff + Greeks + sizing +
   audit + live what-if re-price), wired into `create_app`. **Browser-verified**
   end-to-end on live CBOE data (9 SPY/QQQ ideas, `data mode: live_chain`; cards,
   payoff chart, audit all render); `what-if == engine` unit test. Proves the
   interaction model on the option advisor.
3. ✅ **M3 — Decision journal + static snapshot.** Append-only JSONL journal
   (`trade_advisor.journal`); `/advisor` cards get Proceed/Monitor/Reject + note
   controls feeding a cross-advisor **Inbox**; each decision regenerates a static
   **snapshot HTML** (`reporting/trade_advisor_html`) written to
   `data/artifacts/trade_advisor/` and mirrored cross-device via the existing
   GDrive helper. Persist→inbox→snapshot pipeline unit + headless verified.
4. **M4 — Roll Reminder.** Uses already-ingested held-option positions; first
   advisor that's *about the existing book*.
5. **M5 — FX Hedging Advisor onto the interactive surface.** Fold the existing
   FX Hedging Advisor (`071a188`) into the umbrella: detail view + on-demand
   refresh over its shared artifact (the report side stays the cached ~30d
   target allocation). Then add the **FX Carry Tilt** sub-module (futures-implied
   / overnight-rate carry). First non-option advisor.
6. **M6 — Trade Ideas (general) + extensibility hardening.** Firm up scope; make
   "add an advisor" a documented, low-friction path for the undecided ones.

Each milestone gets its own short design pass; scope-expanding ones get an ADR.

---

## 9. Non-goals

- No order execution / broker writes — now or via this surface, ever.
- No opaque ML; no full multi-leg optimizer before the rule layer is validated.
- No new UI framework (extend NiceGUI + the HTML report).
- No real-time tick infrastructure in V1 — delayed/snapshot data is sufficient.
- Not a multi-user SaaS; single-operator, Tailscale-reachable.

---

## 10. Open questions (to resolve as milestones land)

- Final placement: move `option_advisor` physically under the umbrella, or
  register in place? (Recommend in-place first.)
- The "others not yet decided" advisors — which earn a slot (earnings-vol,
  tax-loss harvest, cash deployment, pairs)?
- Decision journal persistence: local JSON/Feather vs GDrive-mirrored; retention.
- Do reminders ever *push* (email/notification via the existing scheduled-task
  path), or stay pull-only in the Inbox?
- What-if recompute: server round-trip vs lightweight client-side — latency vs
  single-source-of-truth (the test in §7 guards correctness either way).

---

## 11. Governance

- This file is the canonical track devplan. The
  [option_advisor devplan](option_advisor.md) becomes a component reference under
  it.
- ADRs to add as scope is accepted: **trade_advisor umbrella + shared advisor
  contract** (M1) and **interactive advisory surface** (M2, extends ADR 0002's
  "HTML is the deliverable" to "interactive advisor page + static snapshot").
- `plan/current.md` carries the active entry; each milestone updates it.
