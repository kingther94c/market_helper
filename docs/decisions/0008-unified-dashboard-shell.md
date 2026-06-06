# ADR 0008: Unified dashboard shell; two parallel surfaces, not a platform

**Status**: Accepted. Implements the "A+ now → selective-B later" refactor of
the dashboard presentation layer.

## Context

The NiceGUI dashboard hosts two parallel product lines:

- **`portfolio_monitor`** (`/portfolio`) — read-only portfolio / performance /
  risk / regime monitoring; the static HTML report ([ADR 0002](0002-html-deliverable-dashboard-entry.md))
  embedded in an iframe.
- **`trade_advisor`** (`/advisor`) — read-only advisory; bounded controls,
  rule-based ideas, optional AI+ synthesis.

They shared no chrome: `/` redirected straight to `/portfolio`, the advisor had
only a one-way "← Portfolio dashboard" text link, and `add_dashboard_styles`
was injected by the portfolio page alone (so the advisor's `pm-*` classes were
inert). A refactor review proposed three nested options — A (shared shell), B
(symmetric decomposition + split the 1.6k-line `portfolio.py`), C (a
`SurfaceRegistry` platform so the Nth top-level surface is free), optionally
paired with a framework swap (Reflex / Dash / Streamlit).

## Decision

Implement **A+ now**, keep **B selective and later**, reject **C**.

- **Shared shell** (`market_helper/presentation/dashboard/shell.py`): injects
  the shared styles once, renders the brand + cross-surface nav, provides a
  content container, and owns a real `/` **landing page** (two cards →
  `/portfolio`, `/advisor`; no live data load). Both pages wrap their body in
  `app_shell(active=...)`.
- **Keep NiceGUI.** The heaviest requirement — static HTML as the cross-device
  deliverable — is owned by `reporting/` (server-rendered) and is *orthogonal*
  to the UI framework; the advisor's live what-if already works in NiceGUI. A
  framework swap is a high-risk rewrite with no functional win. **No migration
  to Reflex / Dash / Streamlit.**
- **No `SurfaceRegistry`.** The two lines are a fixed pair (`shell.NAV_ITEMS`),
  not a plugin point. **Research / backtest / screener / alpha-lab workflows are
  out of scope for this repo** and belong to a separate project; `market_helper`
  is not a generic multi-surface quant platform. The dead `regimes.py` /
  `signals.py` / `backtests.py` page scaffolds that implied otherwise are
  deleted.
- **Routes and behavior preserved.** `/portfolio` and `/advisor` are unchanged
  (the iframe/report route, operate drawer, refresh pipeline, progress strip,
  Rule-based / AI+ tabs all behave as before). The shell nav is intentionally
  **not sticky** so the portfolio's own sticky `.pm-app-bar` (and the progress
  strip keyed off `--app-bar-height`) is untouched.
- **No `domain/option_advisor` rename**; **no trading / brokerage-write
  behavior** ([ADR 0001](0001-read-only-broker-policy.md)).

**Selective-B later (optional, after A+ is stable):** split `portfolio.py` by
*real* boundaries — `state.py` (dataclasses / page state / stale cache),
`report_host.py` + `artifact_routes.py` (generated-HTML / artifact serving +
iframe URL logic), `actions.py` (dispatch + input parsing) — only where it
improves readability or testability. Do **not** split `trade_advisor.py` merely
to mirror portfolio.

## Consequences

- One front door: `/` is a navigable landing; the nav links the two lines both
  ways. The advisor's `pm-*` classes now resolve (shell injects the styles).
- Adding a third top-level surface is a deliberate edit (`NAV_ITEMS` + a page),
  not a drop-in — by design, to keep research/backtest/screener out.
- `portfolio.py` stays a monolith until selective-B is taken up; this ADR is the
  pointer for that follow-up.
- Supersedes nothing; extends ADR 0002 (HTML stays the deliverable; the shell is
  the interactive entry around it).
