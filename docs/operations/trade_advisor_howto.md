# How to use the Trade Advisor

A **read-only, advisory-only** surface that turns your portfolio + market +
regime context into ranked, explained **trade ideas** — never orders. It places
nothing; it shows labelled ideas you act on yourself.

Design + architecture: [`docs/architecture/devplans/trade_advisor.md`](../architecture/devplans/trade_advisor.md).
Scope decision: [ADR 0006](../decisions/0006-option-advisor-advisory-scope.md).

## Open it

Launch the dashboard (`./scripts/launch_ui.sh`) and go to **`/advisor`**
(linked from the Portfolio dashboard). Localhost-only by default; reach it
cross-device via Tailscale Serve, same as the main dashboard.

There's also a CLI for the option engine alone:

```bash
python -m market_helper.domain.option_advisor SPY QQQ --aum 250000 --hold SPY:200
# fallback when you have no live chain — override spot + IV:
python -m market_helper.domain.option_advisor NVDA --override NVDA:spot=120,iv=0.45 --no-realized
```

## Run an advisor

1. **Inputs** (all bounded controls — there's no free-text/AI box):
   - *Use my portfolio (live positions)* — on by default: seeds your real held
     stocks + options + funded AUM from the live positions report. Off → use the
     manual Universe / Held / AUM controls instead.
   - *Universe* (multi-select), *Treat as held*, *AUM*, *Regime* / *Confidence*,
     *Crisis overlay*, *Fetch realized vol*.
2. Click **Run advisor**. All advisors run together:
   - **Option** — covered call / CSP / protective put / collar / verticals on
     your names, using live CBOE chains (or a synthetic vol-surface fallback).
   - **Roll Reminder** — your held options by DTE / ITM / assignment risk.
   - **FX Hedging** (+ **FX Carry Tilt**) — USD/SGD hedge target + carry tilt.
   - **Trade Ideas** — regime-aligned sleeve tilt (advisory).
3. Results come back as **ranked cards**, grouped **PROCEED → MONITOR → REJECT**,
   with a **data-mode banner** (live / synthetic / cached) so you always know how
   real the numbers are.

## Read a card

Each card shows the label, category, structure, score, key economics (net
credit/debit, max loss/gain, breakeven), thesis, and "why now". Expand
**Detail** for the interactive **payoff chart**, Greeks, sizing, liquidity, and
the **audit trail** (every filter that passed/failed, and why).

- **What-if** (option cards): drag the bounded **Contracts / IV shift / Spot**
  controls to re-price the payoff & Greeks in place (a Black–Scholes *model*
  view, independent of live quotes).

## Decide & track

Use **Proceed / Monitor / Reject** (+ an optional note) on any card. Decisions
persist to a journal, feed the **Inbox** at the top of the page, and refresh a
static **snapshot** that mirrors cross-device (review-only, no controls).

## Honesty & limits

- **Read-only**: ideas, never orders. `MONITOR`/`PROCEED`/`REJECT` are *your*
  triage, recorded as notes — nothing is sent to the broker.
- Model-only data (synthetic chain / overrides) is **capped at MONITOR** and the
  banner says so; it never masquerades as a live quote.
- Rule-based and explainable — no opaque ML, no optimizer.
- Sizing is a share of **funded AUM** (stock-like + cash; excludes
  options/futures).
- If a data source is slow/unavailable the run degrades gracefully (cached or
  synthetic) with a note, rather than failing.
