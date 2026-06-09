# Current Plan

Active initiatives only. Future work lives in [`backlog.md`](backlog.md).
Track-level architecture detail lives in
[`../docs/architecture/devplans/`](../docs/architecture/devplans/). Landed-phase
detail is archived under `memory/archive/landed/` (gitignored, local-only, not
read by default).

> **ADR numbering note:** `docs/decisions/` currently has two `0006-*` and two
> `0007-*` files (fx-hedge + policy-expert at 0006; option-advisor-scope +
> policy-expert at 0007). Until they are renumbered, cite ADRs by **full
> filename**, not bare number.

## Dashboard Shell + two-line decomposition

**State**: **landed**. Shared `presentation/dashboard/shell.py` (`app_shell`)
injects styles once + renders cross-surface nav + owns a real `/` landing; both
page monoliths decomposed into symmetric `pages/portfolio_monitor/` and
`pages/trade_advisor/` subpackages (no backward compat). Routes/behavior
unchanged; 755 unit tests green. Detail:
[`0008-unified-dashboard-shell.md`](../docs/decisions/0008-unified-dashboard-shell.md),
[`0009-two-line-dashboard-decomposition.md`](../docs/decisions/0009-two-line-dashboard-decomposition.md),
`memory/archive/landed/dashboard_landed.md`.

## Portfolio Monitor

**State**: **stable. No near-term scope open.** All landed work — FX Hedging
Advisor, regime/FRED fetch resilience, Flex hardening, report restructure
(Regime tab + Performance merge), mobile/responsive framework, GDrive mirroring,
daily cron, loopback+Tailscale serving, regime-orchestration ownership (ADR
`0005-combined-report-owns-regime-orchestration.md`) — is archived in
`memory/archive/landed/portfolio_monitor_landed.md`; architecture in
[`portfolio_monitor.md`](../docs/architecture/devplans/portfolio_monitor.md).
Open items rotate in via [`backlog.md`](backlog.md).

## Regime Engine

**State**: calibrated through **Q9** (inflation-velocity layer + train/holdout
discipline; neighborhood-stability addendum → verdict **keep Q9 unchanged**).
Engine / concept aggregation / symmetric tanh / beta-adjusted returns / label
hysteresis / anchor-period harness / auto-sync / historical baseline /
per-frequency decay all landed. The two dead gated SVM slots (`macro_truth_ml`,
`return_truth_ml`) are fully removed (engine + config + UI + tests; ensemble +
verdict bit-for-bit unchanged) — their conceptual replacement is the
allocation-layer ML predictor below. Detail:
`memory/archive/landed/regime_engine_landed.md`,
[`regime_engine.md`](../docs/architecture/devplans/regime_engine.md).

**Open near-term work:**
1. **(Optional)** Pin per-anchor macro fixtures from `macro_scout_q9_after.json`
   into the anchor-period harness for a CI guardrail on the macro layer. Not
   blocking — the full-history macro scout is the offline measurement harness.
2. **Q10 candidates (parked)**: 2025 tariff single-event-shock channel (no
   shock signal yet); 2022 H1 growth misread (macro_g Up vs market_g Down —
   post-COVID base-effect handling); velocity 2nd-derivative ("deceleration")
   refinement for 2024 disinflation.

## Regime-Aware Policy-Expert Allocation Model

**State**: **Phases 1–7 + goal v2 COMPLETE** (not merged to main yet). EQ/CM/FI
policy experts (MACRO sleeve removed) + ex-ante **Ridge** ML predictor
(embargoed-CV α=1000, OOS rank-IC +0.20 @6M) → soft mixture-of-experts
allocation; live in the dashboard Regime tab (forward-forecast peer card with
feature attribution + backward "Trending" panel), plus the
`policy_expert_report.html` research report. **Verdict: MONITOR** — MoE Sharpe
0.65 vs 0.58 best-static (beats 6/7 baselines), but a simple cash-in-stagflation
rule (0.79) is competitive → the edge is advisory crisis-tilting. Detail:
`memory/archive/landed/policy_expert_landed.md`, ADR
`0007-policy-expert-ml-predictor-and-trending.md` (supersedes
`0006-policy-expert-allocation-predictor.md`), auto-memory
`inflation_tilt_v0_research.md`.

**Optional follow-ups**: transaction-cost audit (futures financing already
modelled — edge survives ~50 bps; transaction costs still unmodelled); live
feature refresh on a schedule; periodically reassess vs the simple
cash-in-stagflation rule.

## Trade Advisor

**State**: **foundation landed (M1–M6 + opt-in AI); unified cockpit SUPERSEDED;
v2 IA reset SPECIFIED (2026-06-09).** The umbrella mechanics are proven — but the
unified single-run cockpit over a global input panel was the wrong shape. The
engines (option / fx-hedge + carry / futures+option roll / tactical anchors +
Tactical Edge ingest / AI gateway+tools) and the reusable capabilities below are
kept; what changes is the information architecture + per-module presentation.
Read-only w.r.t. the broker (ADR `0001-read-only-broker-policy.md`). Foundation
log: `memory/archive/landed/trade_advisor_landed.md`; runbook
[`docs/operations/trade_advisor_howto.md`](../docs/operations/trade_advisor_howto.md);
advisory scope `0007-option-advisor-advisory-scope.md`.

**Active — Cockpit v2 (de-unified IA, 2026-06-09).** Re-aim per the rewritten
devplan: **no global input entry**; four **purpose-built module surfaces**, each
with a deterministic **Rule-based** pane + an interactive read-only **AI Plus**
dialog (free-form refine, tools only, never orders) — except where a module's
nature departs from the template. (1) **Option Strategy** — Rule-based runs two
screens: zero-cost collar over *holdings*, premium-shorts over the *security
universe* (`security_universe.csv` EQ rows, not the hardcoded 14; needs a
minimum-research pass to fix the premium screen); AI Plus opens the search +
crystallizes good screens back into the preset. (2) **FX Hedge** — an independent
**decision panel** (baseline mix + current FX exposure + carry → tilt), **not**
idea-cards; drops Promote/Watch/Dismiss. (3) **Tactical** — lead with the external
Tactical Edge brief as baseline, then AI-accumulate ideas (multi-direction query +
tools + confidence). (4) **Roll & Carry Calendar** — **no run**, derived from
holdings (options+futures roll) + a commodity-carry **placeholder** (GSCI/F1-F7,
blocked on a CME forward curve). Journal/Inbox kept for **Option + Tactical only**.
Three named gaps: FX currency-exposure lookthrough (**new build**), option scan
universe wiring, GSCI F1/F7 (forward-curve-blocked). Milestones M1–M6 + open
questions in [`trade_advisor.md`](../docs/architecture/devplans/trade_advisor.md).

**Reused capabilities (landed on-branch; survive the v2 reset).** The four engines
+ adapters (Option collar + carry-premium shorts; FX carry-tilt before/after on the
SGD hedge; futures+option roll driven by `futures_roll_calendar.yml`; tactical rule
anchors + external **Tactical Edge** ingest); the **AdvisorIdea v1** four-axis
assessment (confidence / actionability / risk / data — never one score) + research
fields; the **decision journal** with ex-ante snapshot + 30/60/90 review loop; the
trust **tiers** T1–T4 + research-framed labels; the **AI capability framework**
(`trade_advisor/ai/`: read-only tools + skills + knowledge, gateway-agnostic
structured-text tool protocol, conversational `continue_messages` feedback); three
validations (safety / data-honesty / decision). Suite 832 passed / 1 skipped
(on-branch). Devplans:
[`advisor_idea_contract.md`](../docs/architecture/devplans/advisor_idea_contract.md),
[`advisor_ai_capabilities.md`](../docs/architecture/devplans/advisor_ai_capabilities.md).

### Option Strategy (engine — cockpit Module 1)

**State**: **MVP landed.** Pure-stdlib Black–Scholes; CBOE-delayed JSON chain →
yfinance → synthetic fallback; honesty tagging (synthetic capped at MONITOR);
earnings → `EventRisk`; sizing caps to % funded AUM; zero-cost protection collar +
carry-premium shorts (naked, MONITOR-capped). 62 option tests green. Design:
[`option_advisor.md`](../docs/architecture/devplans/option_advisor.md); scope
`0007-option-advisor-advisory-scope.md`. Future (backtest baselines, `ib_async`
live chain) in the devplan.

## Repository governance

Canonical layered-memory layout in
[`0003-layered-memory-canonical-homes.md`](../docs/decisions/0003-layered-memory-canonical-homes.md);
governance rules + reading order in [`AGENTS.md`](../AGENTS.md). Skills
consolidated to two homes (`.claude/skills/` + `.agents/skills/`); durable
conda/env-setup facts live in `memory/hot/operations.md`. `lookthrough-researcher`
stays a deliberate Claude/Codex copy-mirror (keep in sync; do **not** symlink —
that broke on Windows under `core.symlinks=false`).

---
*Last compaction: 2026-06-07 (790 → 126 lines). Landed-phase detail moved to
`memory/archive/landed/{dashboard,portfolio_monitor,regime_engine,
policy_expert,trade_advisor}_landed.md`. Trade Advisor section re-compacted
2026-06-09 for the cockpit-v2 IA reset: the superseded unified-cockpit build log
collapsed to "reused capabilities"; v2 direction authoritative in
`trade_advisor.md`.*
