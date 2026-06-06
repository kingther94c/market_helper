# ADR 0009: Two-line dashboard decomposition (complete B); no backward compatibility

**Status**: Accepted. Completes the "B" refactor that [ADR 0008](0008-unified-dashboard-shell.md)
landed as optional/"selective-B later". Supersedes 0008's *selective-B* guidance
(the shared-shell, landing-page, keep-NiceGUI, no-SurfaceRegistry, and
out-of-scope decisions in 0008 still stand).

## Context

After A+ (ADR 0008) the two surfaces still lived in two monolith page modules:
`pages/portfolio.py` (~1.6k LOC) and `pages/trade_advisor.py` (~0.7k LOC). The
operator directed completing **B in full** — decompose both into symmetric
per-line subpackages and reach the target design — **with no backward
compatibility** (the dashboard is single-operator and internal; preserving old
import paths/shims is not worth the drift).

## Decision

Decompose each line into a `pages/<line>/` package, split by responsibility, and
delete all compatibility surfaces.

- **`pages/portfolio_monitor/`** — `state` (form/page dataclasses, constants,
  IBKR probing, pure helpers, initial state), `routes` (sandboxed artifact
  serving + URL resolution), `actions` (form→`*Inputs` converters, action-status
  helpers, remediation, job/toast log), `views` (always-visible page rendering),
  `drawer` (the Operate slide-over), `page` (`register_portfolio_page` + the
  `/portfolio` lifecycle closures). Service singletons stay in `page` — they are
  used only by the page's own closures, so no cross-module global is needed.
- **`pages/trade_advisor/`** — `inputs` (bounded inputs + pure context builders),
  `cards` (idea cards, body builders, live what-if, results, inbox),
  `rule_based` + `ai` (the two tabs), `page` (`register_trade_advisor_page` + the
  `/advisor` lifecycle). The `TradeAdvisorService` is **passed explicitly** into
  the tab renderers rather than shared via a module global — the one real
  cross-module dependency, made an argument.
- Each package `__init__` exposes **only** `register_<line>_page`.
- **No backward compatibility.** The `dashboard.py` re-export shim is deleted;
  there are no symbol re-export shims; every call-site and test imports from the
  owning submodule. Public routes (`/portfolio`, `/advisor`) and all behavior
  are unchanged — this is an internal code-structure change only.
- **No `SurfaceRegistry`** (that is scheme C, still out of scope per 0008);
  research / backtest / screener remain out of scope (separate project).
- **Latent bug fixed by the move**: `state.DEFAULT_CANONICAL_LOCAL_ENV_PATH` now
  uses `Path(__file__).resolve().parents[5]` (the package is one directory deeper
  than the old flat module, so `parents[4]` would have pointed at `market_helper/`
  instead of the repo root).

## Consequences

- The two lines are structurally **symmetric** (`pages/<line>/{…, page}`);
  adding/maintaining a page no longer means editing a 1.6k-line monolith, and the
  shared shell + components are reused by both.
- Tests import internals from the owning submodule (e.g.
  `portfolio_monitor.routes._served_artifact_url`,
  `trade_advisor.cards.fx_alloc_table`) — there is no compatibility surface to
  drift against.
- Full unit suite green (755 passed, 1 skipped); ruff F-clean on both packages;
  routes + in-browser DOM verified.
- Pre-existing `app.py` E402 fixed to docstring-first (matching the new modules);
  the dashboard `__init__.py` `from .app import *` (F403) is left as-is (it is the
  package's intentional public re-export and out of this refactor's scope).
