# ADR 0007: Option Advisor is advisory-only, execution stays out of scope

**Status**: Accepted. (Scope-expanding; accepted on the owner's explicit
directive to build a runnable advisory version. The advice/execution boundary
below is binding — the landed MVP only reads public data and emits ideas.) See
the [Option Advisor devplan](../architecture/devplans/option_advisor.md).

## Context

The Option Advisor track proposes a module that scans underlyings and emits
ranked option *trade ideas* with rationale, payoff, risk, and sizing guidance.

This sits on a boundary the repo has so far stayed away from. [ADR 0001](0001-read-only-broker-policy.md)
makes the platform read-only **with respect to the broker** — no order entry.
Separately, `plan/backlog.md` and `docs/architecture/devplans/regime_engine.md`
park **"trading-signal generation / allocation tilt suggestions / portfolio
optimization"** as explicitly out-of-V1, citing ADR 0001.

Those two things are not the same constraint, and conflating them would either
wrongly block useful research output or wrongly wave through execution risk. The
boundary needs to be stated, not inferred.

## Decision

Draw the line at **advice vs. action**:

- **In scope (this ADR):** generating, ranking, explaining, and *displaying*
  option trade ideas as research output (HTML section + JSON/CSV artifact). The
  advisor only **reads** existing artifacts and market data and **writes** only
  report artifacts.
- **Out of scope (unchanged, ADR 0001):** placing, cancelling, or modifying any
  order; any broker write path; any auto-execution of an idea. Market data the
  advisor needs from IBKR (`reqSecDefOptParams`, `reqMktData`) are **read**
  operations and remain within ADR 0001.

Binding constraints on the in-scope work:

1. **Advisory framing is mandatory.** Output is labelled ideas (`PROCEED` /
   `MONITOR` / `REJECT`), never instructions; no quantity is presented as an
   order ticket.
2. **Rule-based and explainable first.** No opaque ML; every idea is traceable
   to named drivers + an audit trail of filters applied. No multi-leg optimizer
   until the rule-based core is validated.
3. **No false confidence.** Where chain / IV-surface / earnings data is absent,
   ideas are model-only and capped at `MONITOR`; the artifact states what was
   and was not confirmed (mirrors the regime `data_mode` honesty pattern).

This **supersedes the "trading-signal generation" deferral only for advisory
output** — execution remains deferred and would require its own new interface +
a follow-on ADR revising 0001, exactly as 0001 already specifies.

## Consequences

- The regime devplan's "Deferred → Allocation tilt suggestions / Trading signal
  generation" and the backlog's matching line are narrowed to **execution**, and
  cross-reference this ADR for the advisory carve-out (kept consistent so the
  docs don't contradict).
- The read-only test/CI posture is preserved: the advisor has no write path, so
  it adds no order-entry risk surface.
- If the owner rejects the carve-out, the Option Advisor track does not proceed
  and the devplan is closed as won't-do; ADR 0001 and the existing deferrals
  stand unchanged.
- A future execution capability is still possible only via the
  ADR-0001-mandated new-interface-plus-new-ADR route; this ADR does not open
  that door.
