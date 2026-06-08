# AdvisorIdea contract v1

The single, frozen contract every module speaks. The goal: **stop a single label or
score from standing in for a multi-dimensional judgement.** An idea can be
high-confidence yet un-actionable; well-defined in risk yet resting on stale data.
So the contract carries those as *separate* axes.

It is the existing `trade_advisor.contracts.Suggestion` (kept for compatibility — every
adapter and the UI already speak it), now extended into the AdvisorIdea v1 shape.
`idea_id` and `module` are canonical aliases of `suggestion_id` / `advisor`.

## The four assessment axes (never collapsed)

`IdeaAssessment` — orthogonal, each an ordered best→worst ladder, **never summed**:

| Axis | Question | Levels |
|---|---|---|
| `confidence` | how credible is the signal? | high · medium · low · speculative |
| `actionability` | is it suitable to act on *now*? | act_now · staged · watch · parked |
| `risk_boundedness` | is the loss definable? | defined · capped · undefined |
| `data_quality` | is the data sufficient / fresh? | live · recent · stale · synthetic · missing |

Defaults are conservative (`low / watch / undefined / synthetic`): an idea is low-trust
until an advisor proves otherwise. `data_quality_for_mode(data_mode)` maps the honesty
`data_mode` onto the data_quality ladder (e.g. `regime+model → recent`, `cached → stale`,
`user_override → synthetic`).

The `label` (RESEARCH_READY/WATCHLIST/INFO/REJECT) and `decision_tier` (T1–T4) remain,
but they are **triage**, not a substitute for the assessment — both are shown alongside it.

## Research fields (per the contract spec)

`instrument_family` · `evidence[]` · `risk` · `invalidation` · `missing_data[]` ·
`portfolio_interaction` · `review_after[]` (ex-ante 30/60/90 review dates — set by the
decision journal) · `journal_note` (the ex-ante note carried into the journal).

## How each module populates it

| Module | Tier | Typical assessment |
|---|---|---|
| Roll / Futures roll | T1 operational | confidence high · actionability act_now (urgent) / watch · risk defined · data recent |
| Option | T2 deterministic | confidence high/medium (model-only ⇒ ≤ medium) · risk defined / **undefined** (naked) · data per chain |
| FX Hedge Tilt | T3 model-overlay | confidence medium/low · risk capped · data per cache · `missing_data` = curve / roll yield / cost |
| Tactical | T4 research | confidence from the anchor · actionability **watch** (a hypothesis, never act_now) · risk capped (defined-risk expr) / undefined · data per regime |

## Decision journal — ex-ante → 30/60/90 review (the verification loop)

The contract exists to be **graded**. When you Promote / Watch an idea, the journal
(`trade_advisor/journal.py`) freezes an **ex-ante snapshot** — thesis, the four
assessment axes, label / tier / data_mode, risk, invalidation — and schedules
`review_after` = ts + 30/60/90 days. `due_for_review(as_of)` surfaces what's owed;
`record_review(Review(verdict ∈ worked/partly/wrong/noise))` closes a milestone. The
cockpit's **"Due for review"** panel shows each due idea beside its frozen ex-ante thesis,
so you grade the call rather than your memory of it. Dismissed ideas are never reviewed.

Without this loop the cockpit is a pretty but unverifiable dashboard — it is the minimal
*decision validation* the system needs before any alpha claim (which it has not earned).

## To extend

A new module fills `assessment=IdeaAssessment(...)` with the four axes set honestly for
its tier, plus the research fields. Never invent a higher data_quality than the inputs
support; never set `actionability=act_now` for a research-tier idea.

Files: `market_helper/trade_advisor/contracts.py` (the contract + `data_quality_for_mode`);
adapters in `market_helper/trade_advisor/adapters/`; card render in
`presentation/dashboard/pages/trade_advisor/cards.py`; tests
`tests/unit/trade_advisor/test_advisor_idea_contract.py`.
