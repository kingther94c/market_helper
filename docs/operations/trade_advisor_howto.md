# How to use the Trade Advisor

A **read-only, advisory-only** surface that turns your portfolio + market +
regime context into ranked, explained **trade ideas** — never orders. It places
nothing; it shows labelled ideas you act on yourself.

Design + architecture: [`docs/architecture/devplans/trade_advisor.md`](../architecture/devplans/trade_advisor.md).
Scope decision: [ADR 0007](../decisions/0007-option-advisor-advisory-scope.md).

## Open it

Launch the dashboard (`./scripts/launch_ui.sh`) and go to **`/advisor`**
(linked from the Portfolio dashboard). Localhost-only by default; reach it
cross-device via Tailscale Serve, same as the main dashboard.

There's also a CLI for the option engine alone:

```bash
python -m market_helper.domain.option_advisor SPY QQQ --aum 250000 --hold SPY:200
# pull next-earnings dates (flags ideas whose expiry spans them):
python -m market_helper.domain.option_advisor AAPL --events
# fallback when you have no live chain — override spot + IV (and pin earnings):
python -m market_helper.domain.option_advisor NVDA \
    --override NVDA:spot=120,iv=0.45,earnings=2026-07-30 --no-realized
```

## Run an advisor

The `/advisor` page has two parallel tabs you select between: **Rule-based** (the
default, always-on, zero-AI surface described here) and **AI+** (an optional
synthesis layer — see below). The rule-based tab:

1. **Inputs** (all bounded controls — there's no free-text/AI box):
   - *Use my portfolio (live positions)* — on by default: seeds your real held
     stocks + options + funded AUM from the live positions report. Off → use the
     manual Universe / Held / AUM controls instead.
   - *Universe* (multi-select), *Treat as held*, *AUM*, *Regime* / *Confidence*,
     *Crisis overlay*, *Fetch realized vol*, *Check earnings* (pulls each name's
     next-earnings date so ideas whose expiry spans it are flagged).
2. Click **Run advisor**. All advisors run together:
   - **Option** — covered call / CSP / protective put / collar / verticals on
     your names, using live CBOE chains (or a synthetic vol-surface fallback).
   - **Roll Reminder** — your held options by DTE / ITM / assignment risk.
   - **FX Hedging** (+ **FX Carry Tilt**) — USD/SGD hedge target + carry tilt.
   - **Trade Ideas** — regime-aligned sleeve tilt (advisory).
3. Results come back as **ranked cards**, grouped **PROCEED → MONITOR → REJECT**,
   with a **data-mode banner** (live / synthetic / cached) so you always know how
   real the numbers are.

## AI+ tab (optional)

The **AI+** tab is a *parallel, opt-in* layer over the rule-based engine — it
never replaces it. It takes the same bounded inputs (your book + regime), **runs
the rule-based advisors**, then sends the portfolio + regime + those ideas to
your **local OpenClaw gateway** for a synthesized read (positioning, which ideas
matter most, the biggest risk, what the rules miss). Output is display-only
**analysis, never orders**.

- **Enable it**: just start the OpenClaw gateway — it lives in a separate repo
  (`openclaw_thinking_partner`); from there `OPENCLAW_SKIP_CHANNELS=1 node
  scripts/run-node.mjs gateway run` binds it on loopback:18789. The token resolves in order
  *explicit → `OPENCLAW_GATEWAY_TOKEN` env → `configs/portfolio_monitor/local.env`
  → the gateway's own `~/.openclaw/openclaw.json`* — so a running local gateway
  works out of the box without copying the secret anywhere. If none is found the
  tab shows a "disabled" explainer; the rule-based tab is unaffected.
  Endpoint/model default to `http://127.0.0.1:18789/v1` / `openclaw/trade-advisor`
  (override via `OPENCLAW_GATEWAY_URL` / `OPENCLAW_TRADE_ADVISOR_MODEL` or the
  bounded **AI model** select).
- **Controls stay bounded** (no free-text prompt box): Universe / Held / AUM /
  Regime, an *AI model* select, and an *Include rule-based ideas as context*
  switch. Click **Generate AI advisory**.
- It's a *second opinion* on the deterministic ideas — the rule-based cards
  remain the explainable source of truth.

## Read a card

Each card shows the label, category, structure, score, key economics (net
credit/debit, max loss/gain, breakeven, and — when known — days-to-earnings),
thesis, and "why now". Expand **Detail** for a body tailored to the advisor:

- **Option** — the interactive **payoff chart**, Greeks, sizing, liquidity.
- **FX Hedging** — a **hedge-legs table** (currency / instrument / beta /
  contracts / notional / carry bps / overnight rate / expiry) + totals.
- **FX Carry Tilt** — a **carry-ranking table** (currency / carry bps / ON %).
- **Roll Reminder** — a **position facts grid** (underlying / contract / qty /
  DTE / moneyness / underlying price).

Every body ends with the **audit trail** (each filter that passed/failed, and
why) and the rationale.

- **What-if** (option cards): drag the bounded **Contracts / IV shift / Spot**
  controls to re-price the payoff & Greeks in place (Black–Scholes). When the
  idea carries a chain skew, **Link IV to chain skew** (on by default) makes
  spot moves track the chain's observed skew (sticky-moneyness); toggle it off
  for a flat-vol model view.

## Decide & track

Use **Proceed / Monitor / Reject** (+ an optional note) on any card. Decisions
persist to a journal, feed the **Inbox** at the top of the page, and refresh a
static **snapshot** that mirrors cross-device (review-only, no controls).

## Honesty & limits

- **Read-only**: ideas, never orders. `MONITOR`/`PROCEED`/`REJECT` are *your*
  triage, recorded as notes — nothing is sent to the broker.
- Model-only data (synthetic chain / overrides) is **capped at MONITOR** and the
  banner says so; it never masquerades as a live quote.
- The **Rule-based** tab is explainable — no opaque ML, no optimizer; it's the
  default and source of truth. The **AI+** tab is an *opt-in, clearly-labelled*
  second opinion that synthesizes those rule-based ideas via your own local
  OpenClaw gateway; it's analysis-only (never orders), display-only (the model's
  text is shown, not executed), and off unless you set `OPENCLAW_GATEWAY_TOKEN`.
- Sizing is a share of **funded AUM** (stock-like + cash; excludes
  options/futures).
- If a data source is slow/unavailable the run degrades gracefully (cached or
  synthetic) with a note, rather than failing.
