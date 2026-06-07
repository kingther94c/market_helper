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

**State**: **foundation landed (M1–M6 + opt-in AI+); direction reset OPEN
(2026-06-07).** The umbrella mechanics are proven — one bounded-control
`/advisor` UI hosts four registered advisors (Option / Roll / FX Hedging + carry
/ Trade Ideas; adding an advisor needs no UI work), decision journal + Inbox +
cross-device snapshot, real-book seeding, regime auto-seed, CBOE cache, and an
opt-in **AI+** OpenClaw-gateway synthesis layer that never replaces the
rule-based engine (analysis only, never orders). Read-only w.r.t. the broker
(ADR `0001-read-only-broker-policy.md`). Foundation milestone log:
`memory/archive/landed/trade_advisor_landed.md`; runbook
[`docs/operations/trade_advisor_howto.md`](../docs/operations/trade_advisor_howto.md);
advisory scope `0007-option-advisor-advisory-scope.md`.

**Active — Advisor cockpit (next direction).** The foundation is no longer the
final product target: re-aim at a **multi-module Advisor cockpit** where Option
Strategy is *one module, not the center*. Target modules: **Option Strategy**;
**FX Carry** (SGD hedge allocation + futures-implied carry tilt); **Tactical
Trade Ideas** (AI-assisted non-option macro / market ideas — de-dollarization,
short USD, risk-off / vol, trend persistence); **Roll & Carry Calendar** (options
+ futures rolls, commodity strategy calendars, GSCI-like schedule, F1/F7 deferred
carry). Design:
[`trade_advisor.md`](../docs/architecture/devplans/trade_advisor.md).

### Option Strategy (cockpit Module 1)

**State**: **MVP landed + cockpit structures (in progress).** Pure-stdlib
Black–Scholes; CBOE-delayed JSON primary chain → yfinance → synthetic
vol-surface fallback; honesty tagging (`data_mode`; synthetic capped at MONITOR,
never PROCEED); earnings feed → `EventRisk`; sizing caps to % of funded AUM.
**New (2026-06-07):** zero-cost protection collar (buy OTM put-spread financed by
a short OTM call — net-short-vega, ≈flat/credit cost, honest about the uncovered
tail below the floor) + carry-premium shorts (naked short call / short put with
an annualized carry yield, margin-sized, capped at MONITOR by an explicit
`naked_premium_risk` filter). 62 option tests green. Design:
[`option_advisor.md`](../docs/architecture/devplans/option_advisor.md); scope
`0007-option-advisor-advisory-scope.md`. Future M3+ (backtest baselines,
`ib_async` live chain) in the devplan.

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
policy_expert,trade_advisor}_landed.md`. Trade Advisor "cockpit" direction reset
kept active (folded in from a parallel main-checkout edit).*
