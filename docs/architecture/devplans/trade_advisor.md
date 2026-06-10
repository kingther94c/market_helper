# Trade Advisor — Development Plan

Goal-setting-altitude plan for the **`trade_advisor` surface**: turn portfolio +
market + regime context into **read-only** advisory output across four modules,
each with an **interactive GUI**.

This is intentionally **not** an implementation spec — it fixes the *objective*,
the *hard constraints*, the *module roster*, and especially the *UI / interaction
design*; it leaves data-shapes, signatures, and file layout to each milestone's
own design pass.

> **Direction reset (2026-06-09).** The umbrella *mechanics* are proven (M1–M6 +
> opt-in AI), but the **unified single-run cockpit was the wrong shape** and is
> superseded by §5 below. The engines beneath (option, fx-hedge, futures/option
> roll, tactical anchors + Tactical Edge ingest, the AI gateway/tools) are **kept
> and reused**; what changes is the *information architecture and per-module
> presentation*. The foundation milestone log is archived in
> `memory/archive/landed/trade_advisor_landed.md`.

---

## 1. Objective

A place — in the GUI — where, for each kind of move the user actually makes, they
get **honest, explained, read-only research output they can poke at**, never
orders. Four modules, each purpose-built around the decision it serves:

- **Option Strategy** — "what option structures fit my holdings (hedge) and which
  names in my universe are worth selling premium on?"
- **FX Hedge** — "given my baseline hedge mix, my current FX exposure, and carry,
  how should I tilt?"
- **Tactical Trade Ideas** — "what macro/market ideas are live right now — from my
  external brief and from the AI — and how confident should I be?"
- **Roll & Carry Calendar** — "which of my holdings need a roll, and when?"

---

## 2. The reset — what was wrong, and the new spine

**What was wrong (the user's critique).** Opening `/advisor` led with a *global*
input panel (Universe / Treat-as-held / AUM / Regime) on the left, feeding **one
Run** that fanned out to **four tabs**, all rendered through **one idea-card
contract** with the **same Promote / Watch / Dismiss + Inbox**. Three problems:

1. **The global inputs are disconnected from the modules.** A single Universe /
   AUM entry is meaningful for Option scanning but irrelevant to FX Hedge and to
   the Roll calendar; presenting it as the one front door is incoherent.
2. **The four modules are not the same shape**, so one contract flattens them:
   - *Option* and *Tactical* genuinely produce a **stream of ideas** (a journal +
     Promote/Watch fits).
   - *FX Hedge* is a **continuous allocation decision** (baseline mix → exposure →
     carry → tilt), not a discrete idea stream. Promote/Watch/Dismiss on it is, in
     the user's words, *滑稽* (absurd).
   - *Roll & Carry* is a **deterministic schedule derived from holdings** — it
     should not need a "Run advisor" at all.
3. **Rule-based vs AI were split the wrong way** — once a global "rule-based run"
   plus a single AI tab bolted onto Tactical. AI should be available **per module**,
   beside that module's deterministic view.

**The new spine.**

- **No global input entry.** Each module owns the inputs its decision actually
  needs, and nothing more.
- **Two surfaces per module, side by side:** a **Rule-based** pane (deterministic:
  preset rules over holdings + the security universe) and an **AI Plus** pane
  (open: calls read-only tools, fetches fresh data, runs a more expansive search,
  and supports **interactive refine** — a dialog, not a one-shot). *(Working
  names; "Rule-based" / "AI Plus" are provisional and may be renamed.)*
- **Module nature overrides the template where it must.** FX Hedge's left pane is
  a *decision panel* (mix + exposure + carry), not an idea list; Roll & Carry has
  *no run* and (for now) no AI pane. The two-pane pattern is the default, not a
  straitjacket.
- **A closed loop between the panes.** AI Plus is where the user *discovers* a good
  screen interactively; when one proves out, it can be **crystallized into the
  Rule-based preset** (config, not code), so the deterministic pane keeps getting
  better. This is the explicit payoff of running the two panes side by side.

---

## 3. Hard constraints (the only non-negotiables)

- **Read-only / advisory-only.** No order placement, modification, or cancellation,
  ever, anywhere in this tree ([ADR 0001](../../decisions/0001-read-only-broker-policy.md),
  [ADR 0007](../../decisions/0007-option-advisor-advisory-scope.md)). This includes
  the AI Plus panes: they analyze and suggest, they never emit an order ticket or
  position size as an instruction. The read-only invariant is injected into every
  AI prompt and asserted by the safety tests.
- **Architecture compatibility.** Stay inside the existing layering
  (`cli → workflows → application → domain → data_sources / reporting /
  presentation`). Engines/analytics in `domain`; orchestration in `application`;
  UI in `presentation`. **Reuse** the existing engines (don't fork them); this
  reset is mostly a presentation + per-module-orchestration change.
- **GUI = extend the existing NiceGUI dashboard**
  ([ADR 0002](../../decisions/0002-html-deliverable-dashboard-entry.md),
  [ADR 0008](../../decisions/0008-unified-dashboard-shell.md)). No new UI framework.
- **Two interaction modes, each honest about its rails:**
  - *Rule-based pane* — **bounded controls only** (dropdown / toggle / stepper /
    range-capped slider over fixed option sets and validated numeric bands). Invalid
    states are unreachable; the engine only ever receives clean inputs.
  - *AI Plus pane* — a **read-only dialog** over the OpenClaw gateway. Free-form
    text refine **is** allowed here (this supersedes the old "no free-form input /
    no AI layer" constraint), but the AI may only call **registered read-only
    tools** via the structured-text tool protocol, and may never produce orders.
- **Honesty is mandatory.** Every piece of output carries a `data_mode` (live vs
  cached vs model/synthetic vs your-override). Nothing model-derived is dressed up
  as live. Synthetic/model-only option ideas are capped (never "research-ready");
  the AI pane shows which tools it actually called.
- **Rule-based first; explainable; no opaque ML.** The deterministic pane is the
  product's backbone; the AI pane augments, never replaces it.
- **Regime is context, not an allocator.** Consume regime/risk signals; never turn
  them into auto-execution.
- **Conda `py313`;** new runtime deps go into `env.yml` in the same change.
- **Funded-AUM denominator excludes options/futures** (existing risk gotcha) for
  all sizing.

---

## 4. The four modules (roster + surface types)

The modules are peers in the nav but **not** peers in shape or in trust — each
suggestion already carries a `decision_tier` (T1 operational · T2 deterministic ·
T3 model-overlay · T4 research), and that stays.

| Module | Decision it serves | Rule-based pane | AI Plus pane | Output shape | Journal? |
|---|---|---|---|---|---|
| **Option Strategy** | hedge holdings; sell premium on the universe | two screens: *collar over holdings*, *premium-shorts over the security universe* | open search over holdings + universe; tool-evaluate opportunity quality; refine | **idea stream** | ✅ yes |
| **FX Hedge** | tilt the hedge by exposure + carry | **decision panel**: baseline mix + current FX exposure + carry → tilt | free analysis of the same three inputs; refine | **state / decision panel** | ❌ no |
| **Tactical Trade Ideas** | what's live and how confident | display the external **Tactical Edge** brief as baseline | accumulate our own ideas — query in several directions, call tools, fetch latest data, judge confidence | **idea stream** | ✅ yes |
| **Roll & Carry Calendar** | which holdings need a roll, when | **no run** — derived from holdings: (a) options + futures roll calendar, (b) commodity carry calendar *(placeholder)* | *(deferred — not asked for yet)* | **calendar** | ❌ no |

Engines reused per module: `domain/option_advisor/` (Option); the
`portfolio_monitor` fx-hedge engine + `fx_carry_tilt` (FX Hedge); the futures-roll
+ option-roll engines (Roll); `domain/tactical_ideas/` anchors + the Tactical Edge
parser (Tactical); and `trade_advisor/ai/` (gateway + read-only tools + skills) for
every AI Plus pane.

---

## 5. UI / UX — the four module surfaces (the heart of this plan)

Each module is its **own surface** with inputs scoped to its decision; there is no
shared input column and no single Run button. The default body is a **Rule-based |
AI Plus** two-pane; FX Hedge and Roll & Carry depart from it where their nature
demands.

### 5.0 The shared two-pane pattern

```
┌─ <Module> ──────────────────────────────────────────────────────────────┐
│  ┌──────── Rule-based ────────────┐  ┌────────── AI Plus ──────────────┐ │
│  │ inputs scoped to THIS module   │  │ same context, opened up:        │ │
│  │ (bounded controls)             │  │  • calls read-only tools        │ │
│  │ preset-rule scan over          │  │  • fetches fresh data           │ │
│  │   holdings + security universe │  │  • broader search               │ │
│  │ → deterministic results        │  │  • interactive refine (dialog)  │ │
│  │                                │  │  ↳ "crystallize" a good screen  │ │
│  │                                │  │     back into the Rule-based     │ │
│  │                                │  │     preset (config, not code)    │ │
│  └────────────────────────────────┘  └──────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────────────────┘
```

The **AI Plus dialog** is the interactive-feedback mechanism the user asked for
across *all* AI panes: generate → read → type feedback ("focus on the 2 best;
check the gold trend; be concise") → it revises, with the tool-call trace visible.
This reuses the existing `run_tool_chat` / `continue_messages` loop — read-only,
never orders.

### 5.1 Option Strategy

**Rule-based pane — two preset screens, each with its own scope:**

- **Zero-cost collar (holdings only).** Only meaningful against names the user
  actually holds — it hedges an existing long. Scans `context.holdings`, builds the
  buy-put-spread-financed-by-short-call structure, shows the honest tail below the
  floor. *(Engine exists; carry over the current collar builder.)*
- **Sell call / sell put for premium (the universe).** Searches the **security
  universe** (the EQ rows of `configs/security_universe.csv` — ~32 names today, not
  the hardcoded 14-name `LIQUID_UNIVERSE`) plus holdings, and filters for the
  *valuable* premium opportunities by preset rule (carry yield vs margin, liquidity,
  regime gate). **This needs a minimum research pass** to fix the screen: what makes
  a premium short "worth it" (annualized yield floor, delta band, IV-rank gate,
  event-risk exclusion). The result is YAML preset rules, not code.

Per-idea detail keeps the existing **risk-explainer** body (scenario P&L, vol-shock,
liquidity, plain-English flags) + the bounded what-if re-price. Ideas flow to the
**journal / Inbox** (this module stays idea-shaped).

**AI Plus pane.** Given holdings + the interest universe, the AI runs a more
expansive search and **calls tools to evaluate whether an opportunity is good
enough** (price-trend, regime, liquidity proxies), then refines on feedback. When
an AI-found screen proves out, **crystallize it into the Rule-based preset**.

### 5.2 FX Hedge — an independent decision panel (not idea cards)

FX Hedge does **not** use the idea-card / Promote-Watch-Dismiss contract. It is a
standing **decision panel** built from three parts:

```
┌─ FX Hedge ───────────────────────────────────────────────────────────────┐
│  1) Baseline hedging mix   2) Current FX exposure   3) Carry               │
│  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────────────┐ │
│  │ from Portfolio    │  │ my actual FX      │  │ per-ccy carry (ON-rate   │ │
│  │ Monitor's hedge   │  │ weight / exposure │  │ differential today;      │ │
│  │ target artifact   │  │ across the book   │  │ futures-implied later)   │ │
│  │ (EUR/GBP/AUD/JPY/ │  │  ← NEW: currency  │  │ e.g. AUD carry is good   │ │
│  │  CNH legs, betas) │  │     lookthrough   │  │                          │ │
│  └──────────────────┘  └──────────────────┘  └──────────────────────────┘ │
│  → Decision: tilt the mix given exposure + carry                          │
│    (e.g. "AUD carry is attractive → add AUD weight") — before/after view  │
│  ┌──────────────────────────── AI Plus ────────────────────────────────┐  │
│  │ free analysis over the same mix/exposure/carry; interactive refine   │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────────────────────────┘
```

- **Baseline hedging mix** — read Portfolio Monitor's FX-hedge target artifact
  (`fx_hedge_allocation.json`: per-ccy target contracts, betas, indicative carry).
  Display as the starting point; do not re-derive it here.
- **Current FX exposure** — **landed (coarse lookthrough).** The positions CSV
  carries a per-row `currency`; `currency_exposure_from_positions_csv` sums
  `|market_value|` by currency-of-risk — FX futures (USD-quoted) map to the foreign
  currency they track, everything else to its quote currency, options excluded.
  Honestly labelled coarse: a USD-listed ex-US fund still counts as USD (the deeper
  underlying-asset-currency lookthrough is the open refinement). No fabricated number;
  falls back to a placeholder when no positions are loaded.
- **Carry** — per-ccy carry. Today this is the **ON-rate differential** approximation
  already in `fx_carry_tilt` (honestly labelled rate-approx, not futures-implied);
  the futures-implied curve is a later upgrade gated on a forward-curve feed.
- **Decision layer** — the tilt: combine exposure + carry to suggest leaning the mix
  (the user's example: AUD carry attractive → add AUD weight), with the existing
  before/after exposure + carry-impact + hedge-deviation (basis-risk) view. This is
  a *recommendation to the user about a continuous allocation*, recorded (if at all)
  as the latest panel state — **not** a Promote/Watch/Dismiss idea.

**AI Plus pane** — free analysis over the same three inputs, interactive refine.

### 5.3 Tactical Trade Ideas

Two steps, matching how the user wants to work:

1. **Baseline = the external brief.** Pull the **Tactical Edge** daily brief from
   the user's folder (`MARKET_HELPER_GDRIVE_ROOT/Tactical_Edge/latest.md`, already
   parsed by `parse_tactical_edge`) and **display it directly** as the baseline set
   of ideas — title, status, mechanism, the skeptic's "why-not", scores. This is a
   strong reference to build on.
2. **Accumulate our own ideas (AI-led).** On top of the baseline, the AI is queried
   **in several directions** (the rule anchors: short-USD / de-dollarization,
   risk-off / vol, trend-persistence, curve, sector rotation, commodity RV), **calls
   read-only tools to fetch the latest data**, and **judges confidence** + suggests
   new ideas — each forced to answer "why NOT trade today", capped at WATCHLIST.
   This is the interactive-refine dialog again.

Tactical stays idea-shaped → keeps the **journal / Inbox** and the 30/60/90 ex-ante
review loop (this is what makes a promoted idea *verifiable* later).

### 5.4 Roll & Carry Calendar — holdings-derived, no run

This module should **not** run an advisor. It is read straight off the book:

- **(a) Current holdings' roll calendar.** Options **and** futures the user holds,
  with DTE / roll-target / urgency (PROCEED-within-urgent / MONITOR-within-window /
  INFO), driven by `configs/portfolio_monitor/futures_roll_calendar.yml` (per-root
  schedules) + the option-roll engine. Engines exist; this is a presentation re-home
  away from the idea-card contract into a plain **calendar/table**.
- **(b) Commodity carry calendar — placeholder now.** Leave a clearly-labelled
  placeholder. The target: pull **GSCI's latest roll calendar** and tune its **F1/F7
  deferred-carry** logic as the baseline. This is honestly **blocked on a CME forward
  curve** (not in-repo) — today's roll engine is roll-*timing* only and must not
  fabricate basis. The placeholder states exactly that and what data would unblock it.

No Promote/Watch/Dismiss; no journal — it's a schedule, not an idea stream.

### 5.5 What keeps the journal / Inbox

Only the two **idea-stream** modules — **Option Strategy** and **Tactical Trade
Ideas** — keep the decision journal, the cross-module Inbox of Promote/Watch items,
and the ex-ante 30/60/90 review queue. **FX Hedge** (a decision panel) and **Roll &
Carry** (a calendar) drop out of that contract entirely. *(Design decision taken in
this reset — flagged for the user to veto.)*

---

## 6. Architecture at altitude

- **`market_helper/trade_advisor/`** keeps the shared contract + AI capability home
  (`ai/`), but the contract stops being a one-size mould: FX Hedge and Roll render
  their own bodies and skip the idea/journal machinery.
- **Per-module presentation** replaces the single cockpit (`pages/trade_advisor/
  cockpit.py`) + the global `inputs.py`: each module gets its own inputs + two-pane
  surface. The old global-input builder and the single-Run fan-out are retired.
- **Engines are untouched** — option, fx-hedge + carry-tilt, futures/option roll,
  tactical anchors + Tactical Edge parse, and `ai/` gateway/tools/skills all stay.
  The change is *which presentation calls them and how the output is framed*.
- **New build surface, small and contained:** the FX currency-exposure lookthrough
  (§5.2) and the Option premium-short preset-rule research (§5.1).

---

## 7. Data & honesty (and the three real gaps)

Reuse the live → cached → model/synthetic ladder; each module declares freshness,
the UI surfaces it. Three honest gaps this reset must name rather than paper over:

1. **Option scan universe** — switch the premium-short scan from the hardcoded
   14-name list to the **EQ rows of `security_universe.csv`**. Small, clean.
2. **FX current exposure** — **landed (deeper — country lookthrough).**
   `currency_exposure_from_positions_csv` maps FX futures to their economic ccy and
   looks equities *through* to their underlying-country currencies (shared domain
   service `currency_lookthrough.py`, country→currency map) — a USD-listed ex-US fund
   now shows JPY/EUR/AUD/… not all USD (real book USD 74%→66%). Bucket-level coarseness
   (DM-EUME folds GBP/CHF into EUR) is documented; single-name underlying-currency is
   still listing-ccy. Surfaced in **both** the advisor FX panel and the monitor risk
   report (EQ Currency Exposure).
3. **GSCI F1/F7 deferred carry** — **blocked on a CME forward curve.** Placeholder
   only; roll-timing is honest, basis numbers would not be.

AI Plus data access is **read-only tools only** (the registry refuses non-read-only
functions); the AI cannot reach the broker or any write path.

---

## 8. Validation

- Keep the engine test discipline (pure math unit-tested; deterministic
  ranking/filter tests; hermetic via synthetic/override fixtures).
- **Safety tests** (carry over): the AI panes never emit orders/sizes — prompt-
  regression + leakage checks on every AI surface.
- **Data-honesty tests** (carry over): synthetic / cached / missing is never tagged
  "live"; the FX exposure placeholder never shows a fabricated weight.
- **Decision validation** (carry over, Option + Tactical only): the journal freezes
  an ex-ante snapshot + schedules 30/60/90 reviews.
- Keep the full unit suite green on every milestone.

---

## 9. Milestones (v2 — small, reviewable; sequenced to de-risk the IA first)

1. **M1 — Shell re-aim.** Replace the global-input cockpit with **four
   independently-routed module surfaces** (no shared input column, no single Run).
   Move Roll & Carry off the idea-card contract into a plain holdings-derived
   calendar (no run). *Proves the de-unified IA with the lowest-risk module.*
2. **M2 — FX Hedge decision panel.** Re-home FX off idea-cards into the three-part
   panel (baseline mix + exposure-placeholder + carry → tilt before/after). Drop
   Promote/Watch/Dismiss for FX.
3. **M3 — FX currency-exposure lookthrough.** The new build: symbol → currency-of-
   risk → per-ccy weight; fills the §5.2 exposure column for real.
4. **M4 — Option two-pane + universe + premium-short research.** Wire the scan to
   `security_universe.csv`; do the minimum-research pass to fix the premium-short
   preset rules (YAML); add the AI Plus pane with the crystallize-back loop.
5. **M5 — Tactical baseline-first + AI accumulation.** Lead with the Tactical Edge
   brief as baseline; AI accumulation pane with multi-direction querying + tools +
   confidence judging + interactive refine.
6. **M6 — Commodity carry calendar (placeholder → GSCI/F1-F7).** Ship the labelled
   placeholder now; the GSCI roll calendar + F1/F7 tune lands when a forward-curve
   feed is available.

**Build status (2026-06-09).** ✅ M1 (4-tab shell, no global inputs, `cockpit.py`
deleted; Roll is a no-run holdings calendar) · ✅ M2 (FX decision panel; no
Promote/Watch/Dismiss) · ✅ M3 (FX currency-exposure lookthrough, now **deeper** —
equities looked *through* to underlying-country currencies via `currency_lookthrough.py`;
USD 74%→66% on the real book; in **both** advisor + monitor) · ✅ M4 (option scan wired
to `security_universe.csv`; **premium value screen** researched — variance-risk-premium
IV/RV × annualized yield, ~30-45 DTE / manage ~21 DTE, sources in `option_advisor.md`)
· ✅ M5 (Tactical Edge baseline + AI
accumulation) · ✅ M6 (commodity-carry placeholder). The reusable **AI Plus** pane
(`ai_pane.py`, tools-only/never-orders) is on Option/FX/Tactical. All four tabs
**browser-verified on the real book** (FX exposure USD 74% + AUD/EUR/GBP tilts; the
carry tilt adds AUD / trims JPY; Tactical Edge cards + rule anchors render). Two
incidental fixes shipped: a Tactical-Edge `scores` render crash, and a 181 MB
`regime_snapshots.json` full-parse on every load → now a cached tail-read (5 ms).

Each milestone gets its own short design pass; scope-expanding ones get an ADR.

### 9.1 v2.1 — the next-level pass (2026-06-10)

A fresh full review of the built v2 found the IA right but the *product* still
answering only when poked. Six concrete weaknesses, each with a fix:

1. **The surface has no "so what" layer.** Opening `/advisor` gives four tabs and
   buttons. Roll urgency, due idea reviews, FX-target staleness, the carry-tilt
   headline, and brief freshness are all *computed* but each buried one tab deep;
   nothing synthesizes "what needs my attention today".
2. **Scans evaporate.** An Option scan dies on reload; the tab always opens empty
   and nothing is as-of-stamped. There is also no compact ranked view — only a
   card pile — so comparing 10+ ideas means scrolling.
3. **The FX panel shows the three inputs but never does the join.** §5.2 promises
   a *decision*; what renders is mix, exposure, and carry side by side-ish
   (actually stacked) with the only join being the carry tilt. The actual gap —
   per-currency **target hedge leg vs the FX futures the book already holds**
   (their `market_value` is the signed notional, so this is exactly computable) —
   and the post-at-target net currency mix are missing.
4. **The promised loops aren't closed.** Tactical "accumulate own ideas" produces
   prose that evaporates with the dialog; Option "crystallize a good screen into
   the preset" has no affordance at all. Both are flagship §2 promises.
5. **Roll & Carry shows neither dates nor carry.** The table gives relative "12d"
   but not the target date; the carry card is a pure placeholder — although the
   book's NG calendar spread (short Q26 / long G27) *is* a carry position, and a
   **two-contract roll yield** from live month-contract quotes (`NGQ26.NYM`) is
   honestly computable without a CME curve feed.
6. **Render-path jank.** All four tab panels build synchronously at page load (FX
   artifact read + roll computation inline); `build_fx_panel` runs twice (panel +
   AI grounding); the Option module's manual "Treat as held" select is silently
   ignored while "use my portfolio" is on.

**v2.1 milestones** (sequenced; each lands with tests + an honest data label):

- **V1 — Option scan persistence + ranked summary.** Persist each scan
  (suggestions + inputs + as-of) to
  `data/artifacts/trade_advisor/option_scan_latest.json` (gitignored); restore on
  open with an as-of badge; a ranked summary table (screen · symbol · structure ·
  label · yield · IV/RV · net · liquidity) above the cards; grey out the manual
  held-select while the live book drives the scan.
- **V2 — "Today" attention strip.** A zero-click synthesis bar at the top of
  `/advisor`: roll-now items (T1), due idea reviews, FX-target staleness + tilt
  headline, Tactical-Edge brief freshness, last-scan stats. Local/cached data
  only, built async off the render path; each chip jumps to its tab. Module tab
  bodies defer their IO the same way (fixes weakness 6).
- **V3 — FX target-vs-current decision table.** Split the book's FX-future
  overlay (signed notionals) out of the lookthrough exposure; join per currency:
  book exposure | current overlay | target leg | **gap**; plus an "at target" net
  mix line. Input cards side-by-side per the §5.2 sketch; the decision card —
  gap table + carry tilt — beneath.
- **V4 — Roll calendar dates + held-roots roll yield.** Add the roll-target date
  column. New `futures_roll_yield` service: held month-coded contract → next
  liquid contract (per-root liquid-months config) → quote both via Yahoo
  month-contract symbols → annualized roll yield `ln(F1/F2) × 365/Δdays`, cached
  artifact + an explicit "Fetch quotes (network)" button. Honest scope:
  two-contract carry for *held* roots — the GSCI F1/F7 curve stays open.
- **V5 — Tactical idea capture.** A fenced ```idea`` block protocol in the
  tactical AI prompt; parser + mapping onto `Suggestion` (T4, WATCHLIST-capped);
  a "Capture" action per AI turn renders captured ideas as journal-able cards.
  Closes the accumulate loop; the same protocol is reusable by Option later.
- **V6 (stretch) — crystallize editor.** A bounded premium-screen knob editor
  writing the YAML preset the scan honors. Closes the crystallize loop.

**Build status (2026-06-10).** ✅ V1 (scan persisted to
`option_scan_latest.json` + restored with a saved-at badge; ranked summary table;
manual held/AUM greyed out under "use my portfolio") · ✅ V2 (`overview.py` Today
strip: roll/reviews/FX/edge/scan chips, severity-sorted, async-gathered, chips
jump tabs; FX + Roll module bodies now also populate async) · ✅ V3
(`fx_overlay_by_currency` signed split in the exposure; `build_fx_decision` joins
target legs vs held FX futures per ccy — gap in contracts + USD, "at target" mix
line, CNH↔CNY bucket join; three input cards side-by-side, decision card beneath;
AI grounding now includes the gap + reuses the module's cached panel) · ✅ V4
(roll-date column; `futures_roll_yield.py` two-contract roll yield over Yahoo
month contracts, per-root `liquid_months` cycles, cached via
`roll_carry.fetch/load_roll_yields`, explicit Fetch button — network never in the
render path) · ✅ V5 (`idea_capture.py` fenced ``idea``-block protocol + parser +
`captured_suggestion` → T4/WATCHLIST/synthetic-tagged cards; generic capture seam
on `ai_pane.py`; tactical wires it with a captured-ideas shelf + dedupe) · ✅ V6
(`option_rules.py` bounded clamp + targeted-line-edit YAML save that preserves
comments; the Option scan now passes `advisor_rules.yaml` as `rules_path`, so the
crystallize loop is live end-to-end) · ✅ **V7 — AI harness upgrade (2026-06-10,
gateway live).** The AI panes previously could not *see* any of the above: four
cross-module read-only tools (`trade_advisor/ai/advisor_tools.py` — portfolio
book / FX decision gap / cached roll yields / persisted option scan) now ride in
every pane's registry (9 tools total); the FX decision join moved to
`application/trade_advisor/fx_decision.py` (one home for panel + strip + AI);
option/FX asks point at the authoritative tools. Verified live against the
running OpenClaw gateway: the model called `get_fx_decision` + `get_roll_yields`
unprompted and answered with the real gap (AUD 7ct vs 2ct) and the real NG carry.

---

## 10. Non-goals

- No order execution / broker writes — now or via this surface, ever.
- No opaque ML; no full multi-leg optimizer before the rule layer is validated.
- No new UI framework (extend NiceGUI).
- No fabricated FX exposure or F1/F7 basis while the underlying data is absent.
- Not a multi-user SaaS; single-operator, Tailscale-reachable.

---

## 11. Open questions / decisions taken in this reset

- **Decided:** journal/Inbox kept for Option + Tactical only; FX + Roll drop it.
  *(User may veto.)*
- **Decided:** "Rule-based" / "AI Plus" as provisional pane names; open to rename.
- **Open:** does Roll & Carry ever get an AI pane, or stay purely deterministic?
  (Not asked for; default = stay deterministic.)
- **Open:** does the FX tilt decision get any persistence (panel-state history), or
  stay stateless each session?
- **Open:** when the currency lookthrough lands, is currency-of-risk a manual map
  (like country/sector lookthrough) or derived — and where does it live?

---

## 12. Governance

- This file is the canonical track devplan; [option_advisor](option_advisor.md) and
  [fx_hedge_advisor](fx_hedge_advisor.md) stay as the engine references beneath it.
- The IA + interaction decisions are recorded in
  [ADR 0010](../../decisions/0010-advisor-de-unified-modules-and-ai-plus.md)
  (de-unified module surfaces; per-module AI Plus read-only dialog — amends the
  "no free-form input" line in ADR 0002's interaction model; v2.1 closed loops).
- `plan/current.md` carries the active entry; each milestone updates it.
