"""Shared design tokens, component primitives, and responsive framework for HTML reports + dashboard.

This module is the **single source of truth** for the visual + layout system used by
every HTML surface in `market_helper`. Consumers — :mod:`market_helper.reporting.report_document`,
:mod:`market_helper.reporting.regime_html`, :mod:`market_helper.reporting.performance_html`,
:mod:`market_helper.reporting.risk_html`, and the dashboard chrome at
:mod:`market_helper.presentation.dashboard.components.common` — all inject
:func:`design_tokens_css` into their ``<head>``, so any change here propagates everywhere.

Responsive contract (read this before touching the CSS):

1. **Breakpoints** — three canonical widths, declared once:
     - ``--bp-phone:  480px``  (vertical phone)
     - ``--bp-mobile: 768px``  (large phone / portrait tablet) ← default mobile cutoff
     - ``--bp-tablet: 1024px`` (landscape tablet)
   CSS ``@media`` queries cannot interpolate custom properties; the values above
   are mirrored in literal ``@media (max-width: ...)`` rules in
   ``_RESPONSIVE_FRAMEWORK_CSS``. When you change one, change the other in lock-step
   (the test suite enforces this).

2. **Sticky-stack heights** — never hard-code ``top: 49px``. Use the shared CSS
   variables ``--app-bar-height`` / ``--app-bar-height-mobile`` so the regime ribbon,
   progress strip, and dashboard chrome stay in sync when the app-bar resizes.

3. **Primitives auto-adapt** — ``.card``, ``.metrics``, ``.kpi-strip``,
   ``.app-bar``, ``.section-nav``, ``.report-shell``, ``.report-table-wrap``,
   ``.chart-row``, ``.regime-ribbon__row`` all have built-in mobile rules. New
   HTML that reuses these classes inherits responsive behavior for free.

4. **Utility classes** — when a primitive isn't a fit, opt-in via
   ``.responsive-grid-2`` / ``-3`` / ``-4`` (collapse to single / single / 2 cols
   on mobile), ``.responsive-cluster`` (flex + wrap row), ``.scroll-x-on-narrow``
   (horizontal scroll instead of overflow), ``.responsive-hide-sm``,
   ``.responsive-stack-sm``. Prefer adding a class to writing a new ``@media``
   block in a per-section CSS string.

5. **Touch-target floor** — ``@media (pointer: coarse)`` lifts every ``button`` and
   ``[role="button"]`` to a 40px hit target without changing pixel-perfect desktop
   spacing. Inputs do not get the lift (Quasar field controls already meet the
   floor); raise it explicitly if you build a custom touch surface.

Where mobile rules live:

* **Shared primitives** (anything declared in ``_COMPONENT_PRIMITIVES_CSS`` or
  the dashboard's ``.pm-*`` chrome): the responsive behavior **must** live in
  the framework block (this file) or the dashboard chrome block — never in a
  per-section CSS string. That is the only way a future ``.kpi-strip`` /
  ``.metrics`` / ``.card`` / ``.app-bar`` consumer inherits the right behavior.
* **Section-private classes** (``.perf-*``, ``.control-*``, ``.regime-*``,
  ``.heatmap-*``): per-section ``@media`` blocks are allowed because the
  classes are not reused elsewhere. But the breakpoint *value* **must** be one
  of the framework ``--bp-*`` values (480 / 768 / 1024), so every section
  flips at the same viewport width as the report shell. The test suite
  enforces this via ``test_framework_breakpoints_used_section_wide``.

If a new HTML surface needs responsive behavior the framework does not yet cover,
**extend this file** — do not add a one-off ``@media`` block in the per-section CSS.
That is how the system drifts.
"""
from __future__ import annotations


_TOKENS_CSS = """
:root {
  /* Surfaces — neutral cool palette (P3 flip from warm-paper editorial) */
  --bg: #f7f8fa;
  --surface: #ffffff;
  --surface-2: #f1f3f6;
  --page-bg: var(--bg);
  --panel-bg: var(--surface);
  --panel-border: #e4e7ec;
  --border-soft: #eef0f4;

  /* Ink */
  --ink: #0f172a;
  --ink-2: #334155;
  --hero-ink: var(--ink);
  --muted-ink: #64748b;
  --muted: var(--muted-ink);
  --muted-2: #94a3b8;

  /* Accent — single brand accent, warm reserved for warning surfaces */
  --accent: #0f766e;
  --accent-soft: #ccfbf1;
  --accent-ink: #064e3b;
  --accent-warm: #c2410c;
  --accent-warm-soft: #ffedd5;

  /* Semantic — meaning, not decoration */
  --pos: #15803d;
  --pos-soft: #dcfce7;
  --neg: #b91c1c;
  --neg-soft: #fee2e2;
  --warn: #b45309;
  --warn-soft: #fef3c7;
  --info: #1d4ed8;
  --info-soft: #dbeafe;

  /* Tables */
  --table-header: var(--surface-2);
  --table-border: var(--panel-border);
  --row-alt: #fafbfc;
  --excluded-bg: var(--warn-soft);
  --warning-bg: var(--warn-soft);
  --warning-border: #fdba74;

  /* Shadow / radius */
  --shadow-1: 0 1px 0 rgba(15,23,42,0.04), 0 1px 2px rgba(15,23,42,0.04);
  --shadow-2: 0 1px 0 rgba(15,23,42,0.04), 0 4px 12px rgba(15,23,42,0.06);
  --shadow: var(--shadow-2);
  --r-1: 6px; --r-2: 10px; --r-3: 14px; --r-4: 18px;

  /* Type — single sans, density-first (editorial serif retired) */
  --font-ui: ui-sans-serif, -apple-system, "SF Pro Text", "Inter", "Helvetica Neue", Helvetica, Arial, sans-serif;
  --font-sans: var(--font-ui);
  --font-num: ui-monospace, "SF Mono", "JetBrains Mono", Menlo, monospace;

  /* Layout — single source of truth for the shell width, gutter, and sticky
     stack offsets. Updating these flows to the dashboard chrome, the embedded
     report shell, the regime ribbon, and the progress strip in one shot. */
  --shell-max: 1540px;
  --content-pad: 24px;
  --content-pad-mobile: 12px;
  /* App-bar height — shared by the dashboard chrome, the embedded report shell,
     and every sticky strip pinned beneath them. Each consumer can override these
     for its own context: the dashboard iframe hides brand + meta so its embedded
     `.app-bar` collapses to just the section-nav row, and re-declares smaller
     values in `_EMBEDDED_REPORT_OVERRIDES` (presentation/dashboard/pages/portfolio.py).
     Mobile keeps headroom for the two-row wrap when actions can't fit beside the
     brand on a 360–390px viewport. */
  --app-bar-height: 49px;
  --app-bar-height-mobile: 108px;

  /* Breakpoints — informational. CSS @media rules cannot interpolate custom
     properties, so the values below are mirrored as literals in
     `_RESPONSIVE_FRAMEWORK_CSS`. The test suite enforces they stay in lock-step. */
  --bp-phone: 480px;
  --bp-mobile: 768px;
  --bp-tablet: 1024px;
}
"""


# Component primitives — single source of truth for shared component CSS.
#
# These were previously redeclared verbatim across `report_document`,
# `performance_html`, and `risk_html` (segmented-control), or lived inline in
# `report_document` only (everything else). Centralizing them here lets P3
# restyle each primitive in one place. Section-specific overrides (e.g.
# `risk_html`'s narrower `.chart-row` grid) remain in the per-section CSS so
# they layer on top via cascade order.
_COMPONENT_PRIMITIVES_CSS = """
/* SegmentedControl */
.segmented-control { display:inline-flex; flex-wrap:wrap; gap:2px; padding:3px; border-radius:var(--r-2); background:var(--surface-2); border:1px solid var(--border-soft); }
.segmented-control__button { appearance:none; border:0; border-radius:6px; padding:6px 12px; background:transparent; color:var(--muted-ink); font-size:12px; font-weight:600; cursor:pointer; transition: background 140ms ease, color 140ms ease; }
.segmented-control__button:hover { color:var(--ink); }
.segmented-control__button.is-active { background:var(--surface); color:var(--ink); box-shadow:var(--shadow-1); }
.segmented-control--warm .segmented-control__button { color:var(--muted-ink); }
.segmented-control--warm .segmented-control__button:hover { color:var(--ink); }
.segmented-control--warm .segmented-control__button.is-active { background:var(--surface); color:var(--warn); box-shadow:var(--shadow-1); }

/* Card / Panel */
.card { background: var(--panel-bg); border: 1px solid var(--panel-border); border-radius: var(--r-3); box-shadow: var(--shadow-1); padding: 20px; margin-bottom: 16px; }
.card h2 { margin: 0 0 12px; font-family: var(--font-sans); font-size: 16px; font-weight: 700; }
.card p { color: var(--muted-ink); line-height: 1.55; }

/* KpiCard (label + headline value) */
.metrics { display: grid; gap: 12px; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); }
.metric { padding: 14px 16px; border-radius: var(--r-2); background: var(--surface); border: 1px solid var(--border-soft); }
.metric span { display: block; font-size: 11px; font-weight: 600; letter-spacing: 0.04em; text-transform: uppercase; color: var(--muted-ink); margin-bottom: 6px; }
.metric strong { font-size: 22px; font-family: var(--font-sans); font-weight: 600; font-variant-numeric: tabular-nums; }

/* Table */
.report-table-wrap { overflow: auto; border: 1px solid var(--table-border); border-radius: var(--r-2); background: var(--surface); }
.report-table { width: 100%; border-collapse: separate; border-spacing: 0; min-width: 720px; font-size: 13px; }
.report-table__header { position: sticky; top: 0; z-index: 1; background: var(--table-header); border-bottom: 1px solid var(--table-border); padding: 10px 14px; font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.04em; color: var(--muted-ink); white-space: nowrap; }
.report-table__cell { padding: 10px 14px; border-bottom: 1px solid var(--border-soft); vertical-align: top; }
.report-table__row:nth-child(even) .report-table__cell { background: var(--row-alt); }
.report-table__row.is-excluded .report-table__cell { background: var(--excluded-bg); }
.report-table__row:last-child .report-table__cell { border-bottom: 0; }
.report-table__empty td { padding: 18px 14px; color: var(--muted-ink); }

/* Alignment + tone helpers */
.is-num { text-align: right; font-variant-numeric: tabular-nums; }
.is-center { text-align: center; }
.is-start { text-align: left; }
.tone-positive { color: var(--pos); font-weight: 600; }
.tone-negative { color: var(--neg); font-weight: 600; }
.tone-muted { color: var(--muted-ink); }

/* Tag */
.tag { display: inline-flex; align-items: center; padding: 2px 8px; border-radius: 999px; font-size: 11px; font-weight: 600; background: var(--info-soft); color: var(--info); }
.tag--warning { background: var(--warn-soft); color: var(--warn); }

/* BarRow / score row (canonical defaults; risk_html overrides the row grid + fill colors) */
.scores { display: flex; flex-wrap: wrap; gap: 10px; color: var(--muted-ink); }
.chart { display: grid; gap: 8px; margin-bottom: 14px; }
.chart-row { display: grid; grid-template-columns: 150px 1fr 80px; gap: 12px; align-items: center; }
.chart-track { position: relative; height: 8px; border-radius: 999px; background: var(--border-soft); overflow: hidden; }
.chart-midline { position: absolute; left: 50%; top: 0; bottom: 0; width: 1px; background: var(--muted-2); }
.chart-fill-pos { position: absolute; left: 50%; top: 0; bottom: 0; background: var(--pos); }
.chart-fill-neg { position: absolute; top: 0; bottom: 0; background: var(--neg); }
.chart-value { text-align: right; color: var(--muted-ink); font-size: 12px; font-variant-numeric: tabular-nums; }

/* Misc */
.perf-plot { min-height: 480px; }
.sparkline { width: 120px; height: 28px; }
"""


# Responsive framework — primitive overrides + utility classes + touch-target
# floor. This is the systemic layer described in the module docstring; per-section
# CSS files should rely on these defaults instead of declaring their own @media
# blocks. Keep the breakpoint literals (480 / 768 / 1024) in sync with the
# `--bp-*` custom properties above; the test suite asserts the pairing.
_RESPONSIVE_FRAMEWORK_CSS = """
/* === Responsive utility classes ============================================
   Opt-in primitives that any HTML surface (current or future) can apply to
   inherit standard mobile behavior without writing new @media rules. */

.responsive-cluster { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
/* `.scroll-x-on-narrow` — wrap a wide block so it scrolls horizontally instead
   of overflowing the viewport. The rule is always on (no media query); the
   "-on-narrow" in the name is descriptive of *when scrolling kicks in*, not of
   when the rule applies — `overflow-x: auto` only paints a scrollbar when the
   content exceeds the wrapper, so it's a no-op on desktop where content fits. */
.scroll-x-on-narrow { overflow-x: auto; -webkit-overflow-scrolling: touch; }
.responsive-grid-2 { display: grid; gap: 12px; grid-template-columns: repeat(2, minmax(0, 1fr)); }
.responsive-grid-3 { display: grid; gap: 12px; grid-template-columns: repeat(3, minmax(0, 1fr)); }
.responsive-grid-4 { display: grid; gap: 12px; grid-template-columns: repeat(4, minmax(0, 1fr)); }

/* === Touch-target floor ====================================================
   Coarse-pointer devices (phones / tablets) bump every button + role=button to
   a 40px hit target — Apple HIG / Material both call for ≥44px but 40px keeps
   the dashboard chrome from breaking; combined with the 8px tap padding below
   it satisfies the usual 44px rule. Desktop pixel sizes are untouched. */

@media (pointer: coarse) {
  button, [role="button"], .pm-app-bar__primary, .pm-app-bar__operate,
  .pm-drawer__close, .section-nav__button, .segmented-control__button,
  .pm-static-tab-button {
    min-height: 40px;
  }
}

/* === Primitive overrides — narrow phones (≤ 480px) =========================
   Tightest layout: the KPI strip drops to 2 columns even if the inline style
   asks for more (the `!important` is required because `report_document` /
   `portfolio_html` emit `style="grid-template-columns: repeat(N, ...)"` inline,
   and inline styles outrank stylesheet rules without it). */

/* Note: the 480 block only carries refinements beyond the 768 block below.
   `.kpi-strip` already collapses to 2 columns in the 768 block (which covers
   ≤480 too); repeating it here would just be noise. */
@media (max-width: 480px) {
  .kpi__value { font-size: 18px; }
  .kpi__label { font-size: 10px; }
  .metric strong { font-size: 18px; }
  .responsive-grid-3, .responsive-grid-4 { grid-template-columns: 1fr; }
}

/* === Primitive overrides — mobile (≤ 768px) ===============================
   Default mobile cutoff. Anything that wraps the shared primitives below
   inherits this behavior automatically — no per-section override needed. */

@media (max-width: 768px) {
  /* Shell-width primitives — drop the desktop gutter so content uses the full
     viewport width on phones. The `--shell-max` var still caps wider devices. */
  .app-bar__row,
  .kpi-strip-wrap,
  .report-shell,
  .regime-ribbon__row {
    padding-left: var(--content-pad-mobile);
    padding-right: var(--content-pad-mobile);
  }

  /* App-bar: two-row grid via `grid-template-areas` — brand + meta share the
     top row (so the as-of timestamp stays visible without burning a third row);
     section-nav drops to its own scrollable row underneath. Worst-case height
     ≈ padding(16) + row1(28) + row-gap(6) + row2(36) ≈ 86–108px which fits
     under `--app-bar-height-mobile`. The grid-area assignments below let the
     existing DOM order (brand → nav → meta-stack from `report_document.py`)
     render in the desired layout without per-element re-ordering. */
  .app-bar__row {
    grid-template-columns: 1fr auto;
    grid-template-areas:
      "brand meta"
      "nav   nav";
    gap: 6px 12px;
    padding-top: 8px;
    padding-bottom: 8px;
  }
  .app-bar__brand { grid-area: brand; }
  /* `.app-bar__meta-stack` desktop already sets `align-items: flex-end`; mobile
     only needs the grid-area binding. `.app-bar__meta--note` desktop has
     `max-width: 360px` which is wider than a phone viewport — clamp to 60vw. */
  .app-bar__meta-stack { grid-area: meta; }
  .app-bar__meta--note { max-width: 60vw; }

  /* Section-nav: horizontal scroll instead of forcing every button to fit. */
  .section-nav {
    grid-area: nav;
    overflow-x: auto;
    max-width: 100%;
    flex-wrap: nowrap;
    justify-self: stretch;
    -webkit-overflow-scrolling: touch;
    scrollbar-width: thin;
  }
  .section-nav__button { flex: 0 0 auto; white-space: nowrap; }

  /* Sticky stack — every ribbon / strip pinned under the app-bar moves to the
     taller mobile offset in one place. */
  .regime-ribbon { top: var(--app-bar-height-mobile); }

  /* KPI strip — phones get 2 cols (override inline `repeat(N, ...)`). */
  .kpi-strip { grid-template-columns: repeat(2, minmax(0, 1fr)) !important; }
  .kpi { padding: 10px 12px; }
  .kpi__value { font-size: 19px; }

  /* Metrics primitive — relax the minmax so 3+ tiles per row don't overflow. */
  .metrics { grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 10px; }

  /* Cards trim chrome to make room for content. */
  .card { padding: 14px; margin-bottom: 12px; }
  .card h2 { font-size: 15px; }

  /* Chart row: shrink the label column so the bar+value still get useful width. */
  .chart-row { grid-template-columns: minmax(90px, 30%) 1fr 56px; gap: 8px; }

  /* Segmented-control primitive — promoted from the per-section CSS that used
     to redeclare this rule in `performance_html` + `risk_html`. Any new HTML
     using `.segmented-control` inherits full-width-on-mobile from here. */
  .segmented-control { width: 100%; }

  /* Report sections + section header — scroll offset tracks the mobile app-bar. */
  .report-section { scroll-margin-top: calc(var(--app-bar-height-mobile) + 12px); margin-top: 24px; }
  .report-section__header { flex-wrap: wrap; gap: 8px; }
  .report-section__summary { font-size: 12px; }

  /* Generic utility-grid collapse. */
  .responsive-grid-2 { grid-template-columns: 1fr; }
  .responsive-grid-3 { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .responsive-grid-4 { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .responsive-hide-sm { display: none !important; }
  .responsive-stack-sm { flex-direction: column !important; align-items: stretch !important; }

  /* ----- Table primitive (≤ 768px) ------------------------------------------
     `.report-table` keeps its desktop `min-width: 720px` so columns stay
     readable rather than collapsing to ~50px on a 380px viewport — the
     `.report-table-wrap` overflow already handles horizontal scroll. We just
     tighten cells, sticky the first column for horizontal scroll, and reduce
     wrap radius. */
  .report-table { font-size: 12px; }
  .report-table__header { padding: 8px 10px; font-size: 10px; letter-spacing: 0.03em; }
  .report-table__cell { padding: 8px 10px; }
  .report-table__empty td { padding: 14px 10px; }

  /* Sticky first column — keeps the row identifier (ticker / region / sector)
     visible while the user scrolls horizontally. Combines with the existing
     sticky `<thead>` so the header×identifier corner stays pinned in both axes.
     Background must win over the alternating-row stripe. */
  .report-table__cell:first-child,
  .report-table__header:first-child {
    position: sticky;
    left: 0;
    z-index: 1;
    background: var(--surface);
    box-shadow: 1px 0 0 var(--border-soft);
  }
  .report-table__row:nth-child(even) .report-table__cell:first-child { background: var(--row-alt); }
  .report-table__row.is-excluded .report-table__cell:first-child { background: var(--excluded-bg); }
  .report-table__header:first-child {
    background: var(--table-header);
    z-index: 2;  /* sit on top of body sticky cells where the row + col intersect */
  }

  /* Heat-table tightening (orange + red scales in the risk section). Same
     primitive shape (no min-width to relax), just denser cells. */
  .heat-table th, .heat-table td { padding: 8px 10px; font-size: 11px; }

  /* Report-table-wrap looks better with reduced corner radius on tiny screens. */
  .report-table-wrap { border-radius: var(--r-1); }
}
"""


def design_tokens_css() -> str:
    """Return the ``:root`` token block + shared component primitive CSS as a string.

    The output is meant to be placed inside an existing ``<style>`` element in the
    consumer's ``<head>``. Use :func:`design_tokens_style_block` if a complete
    ``<style>...</style>`` wrapper is needed (e.g. NiceGUI's ``ui.add_head_html``).
    """
    return _TOKENS_CSS + _COMPONENT_PRIMITIVES_CSS + _RESPONSIVE_FRAMEWORK_CSS


def design_tokens_style_block() -> str:
    """Return ``<style>`` element wrapping :func:`design_tokens_css`."""
    return f"<style>{design_tokens_css()}</style>"


__all__ = [
    "design_tokens_css",
    "design_tokens_style_block",
]
