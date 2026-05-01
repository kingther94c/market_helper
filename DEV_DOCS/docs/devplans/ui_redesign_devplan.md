# UI / Reports Redesign — Devplan

Operational plan for the **UI / Reports Redesign** track in [PLAN.md](../../PLAN.md). One PR per phase unless noted; each phase is independently revertible. Visual target: `design_mockup.html` at the worktree root.

## Sequencing with other in-flight tracks

The Playwright snapshot track (Phase B/C/D in PLAN.md) and this redesign interact: the dashboard view becomes the static HTML report via `capture_snapshot()`, so dashboard chrome changes flow into the snapshot output automatically. Recommended interleave:

```
snapshot-A  ── snapshot-B  ── snapshot-C-risk  ── snapshot-C-perf  ── snapshot-C-combined  ── snapshot-D
                                                       │
                                                       ├── P1 (tokens)
                                                       ├── P2 (component primitives)
                                                       ├── P3 (visual reset, combined report)
                                                       ├── P4 (app-bar + KPI strip + hash nav)
                                                       ├── P5 (regime ribbon + fold-in)
                                                       ├── P6 (dashboard chrome alignment)
                                                       ├── P7 (split operate from view)
                                                       └── P8 (legacy template deletion)
```

Rationale: P1/P2 are pure refactor and can land any time. P3+ is the first user-visible change and should land **after** snapshot-C-perf so the static snapshot and the live dashboard converge in the new look together — otherwise the snapshot output and live UI drift visibly during the transition. P8 (legacy template deletion) is dependent on snapshot-D anyway since both delete the same files.

## Phase dependencies

```
P1 ──► P2 ──► P3 ──► P4 ──► P5 ──► P8
                       │      │
                       ▼      │
                      P6 ─────┴──► P7
```

P1 unblocks P2 (component primitives need the token vars). P2 unblocks P3 (re-skin reuses primitives). P4 (app-bar) unblocks P5 (ribbon docks under app-bar) and P6 (dashboard mirrors the same chrome). P6 + P7 are independent of each other but both depend on P4. P8 is the final consolidation pass and depends on everything else being stable.

---

## P1 — Token extraction (pure refactor)

**Scope.** Extract all `:root` custom properties and the redeclared component CSS (`.segmented-control`, `.chart-row`, `.chart-track`, etc.) into one Python module that emits a `<style>` block with the canonical tokens. Have all five surfaces consume it. No DOM, layout, or visual change.

**Files touched.**
- New: `market_helper/reporting/_design_tokens.py`
- Edit: `market_helper/reporting/report_document.py` (drop inline `:root`, import tokens)
- Edit: `market_helper/reporting/performance_html.py` (drop redeclared `.segmented-control` and summary-card CSS)
- Edit: `market_helper/reporting/risk_html.py` (drop redeclared `.segmented-control`, `.chart-row`, `.chart-track`)
- Edit: `market_helper/reporting/regime_html.py` (consume shared tokens; drop local `_styles()` `:root`)
- Edit: `market_helper/presentation/dashboard/components/common.py` (consume shared tokens via `ui.add_head_html`)

**Concrete steps.**
1. Build `design_tokens_css()` function returning the `<style>` block. Tokens follow the mockup: 4-based spacing scale, 6/10/14/18 radius scale, neutral cool palette, single accent (teal), semantic pos/neg/warn/info, single sans font-stack (`ui-sans-serif, -apple-system, "SF Pro Text", ...`), tabular-nums helper class.
2. Build `component_primitives_css()` function returning the redeclared shared component CSS — segmented control, chart row, chart track. (Stub for now; P2 expands it.)
3. Refactor `report_document.py` to compose: `design_tokens_css() + component_primitives_css() + report_shell_css() + (per-section CSS)`. The current literal `:root` block is deleted from the inline f-string; layout-only CSS stays.
4. In `performance_html.py` and `risk_html.py`, delete the local `.segmented-control*` redeclarations. Keep the layout-only CSS (`.perf-summary-grid`, `.heat-table`, etc.) inline for now.
5. In `regime_html.py`, replace `_styles()` with a small wrapper that calls the same shared functions plus regime-only CSS.
6. In dashboard `common.py`, change `add_dashboard_styles()` to inject `design_tokens_css()` + `component_primitives_css()` first, then keep the existing `.pm-*` overlay rules. The cascade order matters — tokens first, dashboard-specific rules win.

**Acceptance.**
- All four reporting modules + dashboard import the token module; no `:root` block remains in any `*_html.py`.
- `git diff --stat` shows reductions in `performance_html.py` / `risk_html.py` / `regime_html.py` and addition of `_design_tokens.py`.
- Existing `tests/unit/reporting/` suite passes unchanged.
- Snapshot diff between pre-PR HTML and post-PR HTML is byte-equivalent for the visual portion (allow whitespace/ordering differences in the `<style>` block).

**Risks.**
- Cascade ordering. If a dashboard page loads tokens *after* `.pm-*` rules, dashboard styling wins where it shouldn't. Mitigation: assert injection order in `common.py` and add a small NiceGUI smoke test.
- Token coverage gap. If a redeclared CSS literal is missed, P3 will surface it as a visual delta. Mitigation: grep for `:root\|--` in each module pre-merge; everything declared inline should be in the token module.

**Estimated change size.** ~250 LOC added (token module), ~150 LOC removed (redeclared `:root` and `.segmented-control` / `.chart-row` blocks).

---

## P2 — Component primitives

**Scope.** Promote redeclared component CSS into named primitives so phase-3 re-skin can re-style them in one place. No visual change.

**Files touched.**
- Edit: `market_helper/reporting/_design_tokens.py` (extend `component_primitives_css()`)
- Edit: `market_helper/reporting/performance_html.py` (use shared `KpiCard`, `SegmentedControl` classes)
- Edit: `market_helper/reporting/risk_html.py` (use shared `BarRow`, `HeatCell`, `Tag`, `StatusChip`, `Table` classes)
- Edit: `market_helper/reporting/regime_html.py` (use shared `StatusChip`, `Tag`, `Table` classes)
- Edit: `market_helper/presentation/dashboard/components/common.py` (use shared `Button`, `StatusChip`)

**Component inventory** (each gets one canonical CSS block in the token module):
- `Button` — primary / secondary / ghost variants.
- `SegmentedControl` — single set of states; the warm-vs-teal active variant in current code becomes one component with a `data-tone="warm|accent"` attribute.
- `KpiCard` — replaces `.perf-summary-card` (drop the decorative gradient bar in P3, not here).
- `Tag` — info / warn / pos / neg / mute variants.
- `StatusChip` — replaces `.pm-status-*` chips.
- `Table` — replaces `.report-table*` styling; keep `tabular-nums`, sticky header, zebra rows.
- `BarRow` — replaces the three slightly-different `.chart-row` declarations across combined-report, perf-html, risk-html.
- `HeatCell` — replaces inline `style="background:#fb923c;..."` literals in `_orange_heat_color` / `_red_heat_color` output. Functions stay; they emit class names + a CSS variable for opacity.

**Concrete steps.**
1. Extend `component_primitives_css()` with the 8 components above. Keep current visuals; just give each a stable class name.
2. In each `*_html.py` consumer, replace literal class names with the primitive class name, e.g. `.perf-summary-card` → `.kpi-card`, `.report-table` → `.table`, `.report-nav__button` → `.btn`. Update the surrounding HTML strings to match.
3. Update `_orange_heat_color` and `_red_heat_color` to emit `class='heat heat--orange'` plus `style='--heat: 0.42'` (intensity 0–1) so the actual color comes from the token module.
4. Move the policy-drift bar chart helper (`_render_policy_drift_chart`) to use `BarRow` markup.

**Acceptance.**
- No literal `.perf-summary-card`, `.report-table`, `.segmented-control__button` etc. in the per-section files; only the primitive class names.
- Tests in `tests/unit/reporting/` pass; HTML-string assertions updated where they hard-coded the old class names.
- Visual parity confirmed by side-by-side rendering (host the pre-PR and post-PR combined HTML in a browser and toggle).

**Risks.**
- HTML-string assertion churn. `tests/unit/reporting/test_risk_html.py` greps the rendered HTML for class strings. Mitigation: this is the kind of test that should be migrated to view-model assertions in P8 anyway; for P2, just update the strings.

**Estimated change size.** ~400 LOC moved (no net add); per-file `<style>` blocks shrink by ~30–50%.

---

## P3 — Visual reset on the combined report

**Scope.** Apply the new design language: neutral cool background, drop editorial serif, drop decorative gradient on KPI cards, encode delta values with semantic color, tighten radius and spacing. Layout still mostly the same as today; this is the "swap the skin" phase. **No content removal** (see PLAN.md content preservation contract).

**Files touched.**
- Edit: `market_helper/reporting/_design_tokens.py` (flip token values to the new palette / radius / spacing)
- Edit: `market_helper/reporting/report_document.py` (slim hero, drop `clamp(34px, 4vw, 56px)` H1, drop `radial-gradient` body bg)
- Edit: `market_helper/reporting/performance_html.py` (KPI cards drop the `::before` gradient bar; positive/negative deltas get semantic class names — see content contract: ITD ann return / vol / Sharpe USD+SGD cards must remain)
- Edit: `market_helper/reporting/risk_html.py` (rerun visual smoke test against all 18 cards)
- Edit: `market_helper/reporting/regime_html.py` (token flip carries through)

**Concrete steps.**
1. Flip palette in the token module: `--page-bg` from `#f7f4ec` (warm paper) to `#f7f8fa` (neutral cool); drop `--accent-warm-soft` if not reused for Tag warn variant; keep `--accent` teal.
2. Replace `--font-sans` (Iowan Old Style) with the unified sans stack; drop the editorial serif from H1 / H2 / KPI value styles.
3. Slim the hero in `report_document.py`: keep the `As of` line and the warning aside; drop the H1 size to `clamp(20px, 2vw, 28px)`; drop the radial-gradient body backgrounds in favor of solid `--bg`.
4. Remove the `::before` gradient bar from `.kpi-card` (was `.perf-summary-card`).
5. In `_render_summary_card` (perf), wrap the value in a `<span class="num">` and add a `pos` / `neg` class when the value is signed.
6. In risk-section policy-drift bars, switch to the unified `BarRow` color tokens (`pos` for over-target, `neg` for under-target) — current implementation uses raw inline gradients.
7. Run the **acceptance grep** from PLAN.md content contract: every card title, column header, and disclosure string from the "must remain" list is still present in the rendered HTML.

**Acceptance.**
- All 4 since-inception summary cards still rendered (As of, Ann Return, Ann Vol, Sharpe), each with USD primary + SGD secondary.
- Horizon Metrics table still has 6 columns (TWR Return, MWR Return, Ann Return, Ann Vol, Sharpe, Max Drawdown).
- Historical Years table still rendered with 5 columns.
- Both USD and SGD tabs still rendered.
- All 18 risk cards still present in order, all column header strings preserved.
- Visual review: KPI card no longer has decorative gradient bar; positive deltas are green, negative are red, warn is amber — semantic, not decorative.
- No editorial serif in body or display text.

**Risks.**
- Snapshot drift. If P3 lands before snapshot-C-perf, the static report and the live dashboard will look different until P6 catches up. Mitigation: gate this PR on snapshot-C-perf landing first.
- Visual regression in risk's heat tables. The orange-scale and red-scale heat cells are baked into `_orange_heat_color` / `_red_heat_color` color literals. P2 already moved those to use `--heat` opacity; P3 should validate the heat scales still read correctly against the new neutral background.

**Estimated change size.** ~80 LOC token diffs, ~120 LOC HTML structure tweaks.

---

## P4 — App-bar + KPI strip + hash-routed nav

**Scope.** Replace the oversized hero + `.report-nav` button row + `<section hidden>` swap with a sticky app-bar, an above-the-fold 8-column KPI strip, and `IntersectionObserver`-based scroll-spy nav. **No content removal** — the existing summary cards (ITD ann return / vol / Sharpe USD+SGD) move to a "Performance overview" sub-block; the new KPI strip is *additive* with values aggregated from existing view-models.

**Files touched.**
- Edit: `market_helper/reporting/report_document.py` (new app-bar markup, hash routing JS replaces hidden-attr swap)
- New: `market_helper/reporting/_topline.py` — fanout helper that aggregates `RiskTopline` from `PerformanceReportViewModel` + `RiskReportViewModel` outputs (NAV, MTD, YTD, 1Y, vol, Sharpe, Max DD 1Y, policy drift summary).
- Edit: `market_helper/domain/portfolio_monitor/services/performance_analytics.py` (expose helpers needed by the topline if not already public)
- Edit: `market_helper/reporting/performance_html.py` (existing summary cards stay as overview block; KPI strip rendered above)
- Edit: `market_helper/presentation/dashboard/pages/portfolio.py` (mirror the app-bar in the live dashboard so they match)

**Concrete steps.**
1. Build `RiskTopline` dataclass in `_topline.py`: `nav_usd`, `mtd_pct`, `ytd_pct`, `one_year_pct`, `ann_vol_pct`, `sharpe`, `max_dd_1y_pct`, `policy_drift_summary` (string like "+3.8pp EQ"). Aggregate from existing view-models — no new computation.
2. New `_render_app_bar(document)` function returning the sticky header markup. Brand → section nav → as-of → Operate → Refresh.
3. New `_render_kpi_strip(topline)` function returning the 8-column grid.
4. Replace `<nav class="report-nav">` button row + `<section hidden>` toggle script with a hash-routed pattern: each section gets `id="performance"` etc.; nav links use `href="#performance"`; scroll-spy uses `IntersectionObserver` to flip the `.is-active` class.
5. Bookmarkable: `?section=risk` query param sets initial scroll target on load.
6. Keyboard accessibility: `:focus-visible` rings on nav links; tab order matches section order.

**Acceptance.**
- KPI strip appears at the top of the combined report; reads NAV / MTD / YTD / 1Y / vol / Sharpe / Max DD / policy drift, with USD primary.
- Existing 4 summary cards (As of / ITD return / ITD vol / ITD Sharpe with USD+SGD) still present in the Performance section under a "Since inception" sub-block.
- `#performance`, `#risk`, `#regime` deep-links work from a fresh load.
- Browser back/forward restores prior section.
- Tab key navigates the section nav with visible focus rings.

**Risks.**
- Topline aggregation. `Max DD 1Y` is not currently a view-model field — the perf service computes it for the horizon table. Mitigation: read directly from `view_model.horizon_rows` for the `1Y` window's `max_drawdown` cell; no new compute path.
- Sticky app-bar inside an iframe. `position: sticky` works fine inside an iframe but the iframe itself scrolls independently. Mitigation: in the dashboard, use `srcdoc=` and let the iframe own its scroll; sticky behavior is per-document.

**Estimated change size.** ~200 LOC added (`_topline.py`, app-bar + KPI markup, scroll-spy JS), ~80 LOC removed (old hero + hidden-toggle JS).

---

## P5 — Regime ribbon + regime fold-in

**Scope.** Add a sticky compact regime ribbon directly under the app-bar, and bring `regime_html.py` content into the combined report shell as a third section. Standalone `regime-html-report` CLI keeps emitting a self-contained file (same DOM, minimal shell).

**Files touched.**
- Edit: `market_helper/reporting/report_document.py` (regime ribbon component, optional render)
- Edit: `market_helper/reporting/regime_html.py` (split into `render_regime_section(view_model)` returning a body fragment + `render_regime_html_report(view_model)` wrapping it in a minimal shell for the CLI)
- Edit: `market_helper/reporting/combined_html.py` (or wherever the combined orchestration lives — TBD; check `__init__.py` for the entry point) — pass `regime_html_view_model` and call `render_regime_section` as a third tab.
- Edit: `market_helper/cli/main.py` — `regime-html-report` keeps current behavior (standalone), `combined-html-report` now optionally includes the regime tab when regime data is available.

**New regime visuals (additive, from the mockup):**
- Factor-score grid with inline SVG sparklines (Growth / Inflation / Liquidity / Vol over last ~6 months).
- Crisis-intensity area chart with threshold band (replaces the static "intensity 0.18" text).
- Method-vote heat strip: last 30 sessions × N methods, color-coded by quadrant + crisis. Reads from `MultiMethodRegimeSnapshot` payload via `_build_multi_method_view_model`.
- Regime-transition log: dates + label changes from the latest payload.

**Concrete steps.**
1. Add a `RegimeRibbonViewModel` slice (regime label, agreement, duration, vol multiplier, crisis flag, last transition date) — extracted from existing `RegimeHtmlViewModel`.
2. Refactor `render_regime_html_report` into `render_regime_section_body(view_model)` + `render_regime_html_report(view_model)` (the latter wraps the former in `<html>…<body>` for the standalone CLI artifact).
3. Add SVG sparkline helper for the factor-score grid: read 6-month axes timeseries from `MultiMethodRegimeSnapshot.history` (or compute from payload list; check whether history is accessible at view-model level — if not, surface it).
4. Add area-chart helper for crisis intensity timeline. Pure SVG to keep the report self-contained without bringing Plotly into the regime section.
5. Add the method-vote heat strip helper. One row per method, one cell per session, color from a small enum.
6. Wire the ribbon into `report_document.render_report_document()` — render between the app-bar and the section nav.
7. Wire the regime section into `combined-html-report` — gated on regime view-model availability (don't break the no-regime path).

**Acceptance.**
- Combined report has three tabs: Performance / Risk / Regime.
- Standalone `regime-html-report` CLI still emits a single-file HTML with the same data points as today (and the new visuals).
- Ribbon shows on every section (sticky).
- Crisis flag toggles between `Crisis off` (mute) and `Crisis on` (red-soft) styles.
- Method-vote heat strip renders 30 columns × N method rows.
- Regime transition log shows last 4–8 transitions.

**Risks.**
- Coupling between standalone regime HTML and combined report. If `render_regime_section_body` mistakenly assumes parent app-bar context (e.g. relative-positioned ribbon), the standalone artifact will look broken. Mitigation: render the standalone version in the smoke test (`tests/unit/reporting/test_regime_html.py`) and assert it's still self-contained.
- History data availability. The factor-score sparklines need ~6 months of history. The current `RegimeHtmlViewModel` doesn't carry that — we'll need to surface from `multi_method_service.py`. Mitigation: add an optional `history_axes_series: list[AxisHistoryPoint] | None = None` field; render the sparkline only when present; fall back to just-the-scalar today when absent.

**Estimated change size.** ~350 LOC added (sparkline / area-chart / heat-strip helpers + ribbon), ~50 LOC moved (split of regime renderer).

---

## P6 — Dashboard chrome alignment

**Scope.** Apply shared tokens + app-bar pattern to the NiceGUI dashboard so the dashboard chrome and the embedded HTML report share visual language. The iframe seam closes.

**Files touched.**
- Edit: `market_helper/presentation/dashboard/components/common.py` (add `add_app_bar_styles()`, drop the slate-blue `.pm-hero` gradient)
- Edit: `market_helper/presentation/dashboard/pages/portfolio.py` (replace `_render_header` + `_render_toolbar` with the new app-bar; reuse shared `KpiCard` / `Button` / `StatusChip` / `Tag`)

**Concrete steps.**
1. Replace `.pm-hero` gradient block with a token-driven app-bar matching the report's. Brand on left, section/tab nav center, action buttons right.
2. Replace toolbar's "Recompute Report Data / Reload Embedded HTML / Refresh Pipeline + Generate / Generate HTML Report" button row with a single primary "Refresh" + a kebab/overflow menu for the niche actions. (Actual operate cards move to a drawer in P7.)
3. Update `render_status_card` and `render_status_badge` to use shared `StatusChip` / `KpiCard` primitives.
4. Make sure the iframe `srcdoc` content has the same token module embedded — the iframe is its own document but reads the same tokens, so visually it bleeds into the parent.

**Acceptance.**
- No visible seam between the dashboard chrome and the embedded report (same fonts, same accent, same neutral background).
- Dashboard `_render_header` no longer renders the slate-blue gradient hero.
- "Refresh" is the only primary button visible in the chrome on first paint (other actions move to overflow / drawer in P7).
- All `pm-status-*` chip semantics preserved (running / success / error / neutral).

**Risks.**
- NiceGUI default Quasar styles may override custom CSS in ways that aren't obvious from `add_head_html`. Mitigation: prefix all dashboard-specific overrides with `.pm-` and check specificity.

**Estimated change size.** ~120 LOC edited.

---

## P7 — Split operate from view

**Scope.** Move the action console (Refresh Pipeline / Live Refresh / Flex Refresh / HTML Report / Reference Sync), artifact-paths inputs, and progress log out of the `/portfolio` first-paint. Default pattern: slide-over drawer triggered by the Operate button. Fallback if drawer gets crowded: a `/operations` route.

**Files touched.**
- Edit: `market_helper/presentation/dashboard/pages/portfolio.py` (most of the changes — `_render_action_console`, `_render_logs`, `_render_toolbar` "Artifact Paths" expansion all move into a drawer slot)
- New: `market_helper/presentation/dashboard/components/operate_drawer.py` (drawer composition; reuses existing action-card components)
- Edit: `market_helper/presentation/dashboard/components/actions.py` (no functional change; just split out into the drawer slot)

**Concrete steps.**
1. Build a `<aside class="drawer">` slide-over component using NiceGUI's `ui.drawer` or a custom `ui.element('aside')` with `position: fixed` + transform animation.
2. Move `_render_action_console`, the "Artifact Paths" expansion, and `_render_logs` into the drawer.
3. Wire the app-bar "Operate" button to toggle the drawer's `is-open` state.
4. `/portfolio` first-paint contains: app-bar, regime ribbon, KPI strip, embedded report iframe. No forms, no file paths, no log.
5. Progress log: when an action runs, surface a small toast at the bottom-right showing the latest progress event; full log stays inside the drawer.
6. Remove the legacy "Recompute Report Data / Reload Embedded HTML" buttons — the single Refresh button (Refresh Pipeline + Generate flow) replaces them. If users actually need the granular flows they can be exposed in the drawer's overflow menu.

**Acceptance.**
- Loading `/portfolio` shows zero form inputs and zero file-path strings on first paint.
- Pressing Operate opens a drawer with all 5 action cards and all artifact paths.
- Pressing Refresh runs the previous "Refresh Pipeline + Generate" action with no extra clicks.
- An action-progress toast appears bottom-right while a job is running; full history is in the drawer's log panel.
- Closing the drawer doesn't lose form state — the existing `_cache_stale_page_state` / `_restore_stale_page_state` machinery still works.

**Risks.**
- State machinery. The current page caches stale form state in `_STALE_PAGE_CACHE`; moving forms into a drawer must not break that round-trip. Mitigation: drawer content is rendered via the same `@ui.refreshable` `render` function, so cache logic is unchanged.
- Browser scrolling. With the drawer open over the iframe, users may try to scroll the report and hit the drawer. Mitigation: drawer takes pointer events; backdrop click closes.

**Estimated change size.** ~250 LOC moved, ~100 LOC added (drawer component + toast).

---

## P8 — Legacy template deletion + test migration

**Scope.** Once P1–P7 are stable and the snapshot pipeline owns the canonical look, delete the legacy HTML-only renderer paths and migrate HTML-string assertions to view-model assertions. This phase pairs with snapshot-Phase-D.

**Files touched / deleted.**
- Delete: `_render_summary_card` decorative-gradient CSS (already orphaned by P3).
- Delete: redundant inline `<style>` blocks across the four reporting modules (remaining duplication after P1+P2).
- Delete: the standalone `_styles()` function in `regime_html.py` if it's been fully absorbed by the shared token module.
- Delete (paired with snapshot-D): legacy `render_html` / `render_risk_tab` template code in `risk_html.py`, the `market_helper/presentation/html/portfolio_risk_report.py` shim, and the HTML half of `market_helper/reporting/combined_html.py`.
- Edit: `tests/unit/reporting/test_risk_html.py` and `test_performance_html.py` — replace HTML-string assertions with view-model-level assertions where possible.
- Edit: `tests/unit/reporting/test_regime_html.py` — assert sections present in the standalone artifact.

**Concrete steps.**
1. Audit every `<style>` block in the four reporting modules; anything that fully duplicates shared tokens or primitives gets deleted.
2. Migrate test assertions: `assert "<h2>Portfolio Summary</h2>" in html` becomes `assert "Portfolio Summary" in section_titles(view_model)` where reasonable. Keep a small grep-style smoke test that asserts the rendered HTML contains every "must remain" content marker from the PLAN.md preservation contract.
3. Add a small CSS-presence test that imports the token module and asserts the canonical class names (`btn`, `kpi-card`, `tag`, `seg`, `bar`, etc.) appear in the emitted CSS — guards against future drift.

**Acceptance.**
- CSS character count across `performance_html.py` + `risk_html.py` + `regime_html.py` drops by ≥ 40% from pre-P1 baseline.
- All `tests/unit/reporting/` tests still pass.
- A regression smoke test asserts every PLAN.md "must remain" item is still in the rendered HTML.

**Risks.**
- HTML-string assertions can be load-bearing for things the view model doesn't surface. Mitigation: when migrating, preserve the assertion if the data point lives only in the rendered HTML (e.g. specific localized labels, currency formatting decisions).

**Estimated change size.** ~600 LOC deleted (template code + redundant CSS), ~150 LOC test migrations.

---

## Per-phase rollback

Each phase has a clean revert: tokens / primitives / component renames are isolated to their phase; the app-bar/KPI strip/regime ribbon are additive markup; operate-drawer is a layout move with no data changes. P3 is the riskiest visual change — if it lands and you don't like it, revert is one PR. P7 is the riskiest UX change — keep the drawer simple in V1; if it doesn't feel right, fall back to a `/operations` route.

## Status tracking

Track per-phase status in PLAN.md (mark phases complete as they ship). When P1 lands, move the P1 bullet from "Phases" into "Completed" with a one-line summary. The "Acceptance for the redesign track as a whole" block in PLAN.md is the final gate.
