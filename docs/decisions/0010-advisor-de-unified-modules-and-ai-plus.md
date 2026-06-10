# ADR 0010: Trade Advisor de-unified module surfaces + per-module AI Plus dialog

**Status**: Accepted. Records the 2026-06-09 cockpit-v2 reset (devplan
[`trade_advisor.md`](../architecture/devplans/trade_advisor.md) §2/§5) and the
2026-06-10 v2.1 next-level pass (§9.1) — the two ADRs §12 said to add once the
scope was accepted. Amends [ADR 0002](0002-html-deliverable-dashboard-entry.md)'s
interaction model (see *AI Plus* below); the read-only broker policy
([ADR 0001](0001-read-only-broker-policy.md)) is unchanged and load-bearing.

## Context

The first Trade Advisor GUI was a **unified cockpit**: one global input panel
(Universe / Treat-as-held / AUM / Regime), one Run, four tabs rendered through
one idea-card contract with one Promote/Watch/Dismiss + Inbox. The operator
rejected the shape: the global inputs are disconnected from the modules, the
four modules are not the same shape (FX Hedge is a continuous allocation
decision — idea-verbs on it are absurd; Roll is a schedule that needs no run),
and rule-based vs AI was split at the wrong level (one AI tab bolted onto
Tactical instead of AI beside every module).

## Decision

1. **No global input entry; four purpose-built module surfaces.** Each module
   owns the inputs its decision actually needs. The default body is a
   **Rule-based | AI Plus** two-pane; a module's nature overrides the template
   (FX Hedge = a three-input **decision panel** + decision join; Roll & Carry =
   a **no-run calendar**). Journal/Inbox only for the idea-shaped modules
   (Option, Tactical — including AI-captured ideas).
2. **AI Plus is a per-module, read-only dialog** (`ai_pane.py` over the OpenClaw
   gateway). Free-form *feedback text* is allowed here — this **amends ADR
   0002's "no free-form input / no AI interpretation" line**, which now governs
   the *rule-based* panes only (bounded controls; engines receive clean inputs).
   The AI may call only registered read-only tools via the structured-text
   protocol, never emits orders/sizes, and every surface shows the tool-call
   trace. Failures degrade gracefully — the rule-based pane never depends on the
   gateway.
3. **Closed loops between the panes** (v2.1): AI output **captures** into
   journal-able idea cards via the fenced ``idea``-block protocol
   (`idea_capture.py`; T4 · WATCHLIST-capped · `data_quality=synthetic`), and a
   proven screen **crystallizes** into the rule-based preset via bounded,
   comment-preserving YAML edits (`option_rules.py`) that the scan honors
   (`rules_path=advisor_rules.yaml`).
4. **Zero-click synthesis above the tabs** (v2.1): the "Today" strip
   (`overview.py`) aggregates roll urgency, due reviews, FX-target staleness +
   tilt, brief freshness, and last-scan stats from **local/cached data only**,
   built async off the render path. Network is never in a render path anywhere
   on the page; explicit user actions (Scan, Fetch quotes, AI Generate) are the
   only fetch triggers.

## Consequences

- The one-contract uniformity of the umbrella (`Suggestion`) survives where it
  fits (Option/Tactical idea streams, roll rows re-framed as calendar rows) and
  is deliberately *not* forced onto FX (panel dicts) — a new advisor that is
  idea-shaped still gets the UI for free; a non-idea surface writes its own thin
  body.
- Honesty machinery (data_mode ladder, tier caps, four-axis assessment) is
  unchanged and now also tags AI-captured ideas (synthetic until verified).
- The old `cockpit.py` + global `inputs` fan-out are deleted; `inputs.py` keeps
  only the bounded option sets + context builders the Option module uses.
- Scan persistence (`option_scan_latest.json`) and the roll-yield quote cache
  (`futures_roll_yield.json`) live under `data/artifacts/trade_advisor/`
  (gitignored), stamped with saved-at/fetched-at — restored views are badged,
  never re-labelled fresh.
