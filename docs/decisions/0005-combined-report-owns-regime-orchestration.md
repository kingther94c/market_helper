# ADR 0005: Combined report owns regime orchestration

**Status**: Accepted (2026-05-24). Replaces the previous "regime is an
independently-triggered side-artifact" pattern.

## Context

The combined HTML report contained a Regime section that was driven by an
on-disk artifact at `data/artifacts/regime_detection/regime_snapshots.json`.
Producing that artifact required a *separate* manual action ("Refresh Regime"
button in the dashboard, or `scripts/run_regime_detection.bat` from the CLI).

The combined report's renderer treated `regime_view_model` as `Optional`: when
the file was absent or stale, the renderer silently dropped the entire Regime
section, the regime ribbon, the regime KPI cell, and the regime CSS, leaving
no actionable signal in the report itself — only a single line in the
warnings list.

In practice this meant:

- The Windows scheduled daily cron (`scripts/dev/run_daily_report.py`)
  refreshed positions and rendered the report but never refreshed the regime.
  On any machine where the regime artifact was missing, the daily report
  permanently had no regime section. The bug only surfaced when a user noticed
  the missing chrome.
- Five separate `regime_view_model is None` branches were sprinkled across the
  render layer (KPI cell, ribbon, section append, head CSS, body switch),
  with no single source of truth for "what does the user see when regime is
  unavailable".
- Three layers separately decided when regime was "fresh enough" (the
  workflow's `max_age_days=7`, the renderer's `_regime_is_stale` 1-day
  parent-vs-regime comparison, and an implicit "if the file exists at all").

## Decision

Combined-report assembly **owns regime orchestration**. The combined report
pipeline asks a regime-provider service for the view-model in one of three
modes; the renderer always renders the regime section.

### Mechanics

1. **`RegimeMode`** — `Literal["cached", "refresh-if-stale", "force-refresh"]`,
   declared on `GenerateCombinedReportInputs` (and inherited from
   `PortfolioReportInputs`). Default: `"refresh-if-stale"`.

2. **`RegimeArtifactState`** — tagged dataclass returned by the provider:
   `state` ∈ {`ok`, `stale`, `missing`, `engine_error`}, plus the optional
   view-model, last-engine-run timestamp, mode used, and error message.
   `PortfolioReportData.regime_state` is always present.

3. **`provide_regime_view_model`** in
   `market_helper/domain/regime_detection/services/regime_report_provider.py`
   centralises load / refresh / fallback / state tagging. Engine failures are
   caught and surfaced as `engine_error` with the original message; the report
   still renders, falling back to the prior snapshot if one exists.

4. **Single staleness definition: trading-day T-1.** Both the
   `refresh-if-stale` trigger and the renderer's `state == "stale"` tag use
   `market_helper.common.datetime_display.is_as_of_stale`, which is the
   shared predicate behind the report's overall `as_of_freshness_note`. A
   regime artifact is stale if its latest snapshot's `date` lags the
   previous weekday (SGT-anchored, matching the rest of the dashboard's
   T-1 convention). The earlier 1-day parent-vs-regime tag remains as a
   complementary signal — it answers a different question ("does the
   regime data point apply to the report's as-of date?") and is computed
   in the renderer, not the provider.

5. **Renderer is always-on**: the regime section, ribbon, KPI cell, and CSS
   are always emitted by `market_helper/reporting/portfolio_html.py`. On
   `missing` / `engine_error`, the body becomes an explanatory card listing
   the state, last-engine-run, mode tried, error message, and the precise
   action that fixes it ("click Refresh Regime" / "run
   `scripts/run_regime_detection.bat`").

6. **Cron is wired**: `scripts/dev/run_daily_report.py` explicitly passes
   `regime_mode="refresh-if-stale"`. The daily cron now self-sufficiently
   keeps the regime fresh — no separate manual step.

### Why trading-day T-1 (not an hour-count threshold)

The combined report already uses trading-day semantics for its
top-of-page `as_of_freshness_note` ("Latest trading day not yet
published..."). Two definitions of "stale" in the same report would
inevitably disagree (e.g., a 72h artifact across a weekend reads "fresh"
by hours but "stale" by trading days, or vice-versa). Sharing
`is_as_of_stale` means the regime section's stale flag and the report's
overall freshness hint always agree about what counts as out-of-date.

The refresh trigger uses a cheap JSON-tail peek to read the latest
snapshot's `date` field without building the full view-model, so the
trigger is essentially free when the artifact is already current.

## Consequences

- The "Refresh Regime" dashboard button becomes a manual *force-refresh*
  shortcut rather than a prerequisite. Users who never click it still get
  fresh regime data in their daily report.
- Combined-report flows (cron / dashboard / future CLI entry) all go through
  the same single contract — `regime_mode` on `GenerateCombinedReportInputs`.
- "What counts as stale" lives in exactly one place
  (`market_helper.common.datetime_display.is_as_of_stale`) and is shared
  with the report's overall freshness note. Changing the rule changes both
  call sites at once.
- The render layer no longer carries `view_model is None` branches; the
  unavailable-card is the single place users see "why is regime missing".
- The five-way conditional rendering coupling in `portfolio_html.py`
  collapses to one switch on `regime_state.state`.

## Non-decisions

- The independent `run_regime_report` / `refresh_regime_report` workflows
  remain available for users who want to produce the standalone Regime HTML
  artifact without rendering the combined report.
- The Regime Engine Q-series calibration discipline (ADR 0004) is unchanged.
- ML layers (`macro_truth_ml`, `return_truth_ml`) remain gated; the provider
  has no opinion on which layers run.
