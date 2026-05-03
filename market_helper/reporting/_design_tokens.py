"""Shared design tokens and component primitive CSS for the HTML reports + dashboard.

Phase P1 of the UI / Reports redesign track (see ``DEV_DOCS/PLAN.md``). This module is
the single source of truth for ``:root`` custom properties and for component CSS that
was previously redeclared verbatim across :mod:`market_helper.reporting.report_document`,
:mod:`market_helper.reporting.performance_html`, and :mod:`market_helper.reporting.risk_html`.

P1 preserves visuals exactly — values mirror the canonical ``:root`` block in
``report_document.py`` as it stood before the redesign. P3 will flip these values to
the new design language; consumers will not need to change.
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


# Mobile-only refinements (≤ 768px). Strictly additive — no calc, no column,
# no row-ordering changes; desktop layout untouched. The primary win is making
# the existing horizontal-scroll affordance more usable on phone-sized viewports
# rather than collapsing wide tables to unreadable widths.
_MOBILE_OVERRIDES_CSS = """
@media (max-width: 768px) {
  /* Tighter cells + smaller cell font so more columns fit per scroll step.
     `.report-table` keeps its desktop `min-width: 720px` so columns stay
     readable rather than collapsing to ~50px on a 380px viewport — the
     `.report-table-wrap` overflow already handles horizontal scroll. */
  .report-table { font-size: 12px; }
  .report-table__header { padding: 8px 10px; font-size: 10px; letter-spacing: 0.03em; }
  .report-table__cell { padding: 8px 10px; }
  .report-table__empty td { padding: 14px 10px; }

  /* Sticky first column — keeps the row identifier (ticker / region / sector)
     visible while the user scrolls horizontally through wide numeric columns.
     Combines with the existing sticky `<thead>` so the header×identifier corner
     stays pinned in both axes. Background must win over the alternating-row
     stripe to avoid the sticky cell being seen through. */
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

  /* Report-table-wrap looks better with reduced corner radius on tiny screens
     where the cell density is higher. Pure cosmetic. */
  .report-table-wrap { border-radius: var(--r-1); }
}
"""


def design_tokens_css() -> str:
    """Return the ``:root`` token block + shared component primitive CSS as a string.

    The output is meant to be placed inside an existing ``<style>`` element in the
    consumer's ``<head>``. Use :func:`design_tokens_style_block` if a complete
    ``<style>...</style>`` wrapper is needed (e.g. NiceGUI's ``ui.add_head_html``).
    """
    return _TOKENS_CSS + _COMPONENT_PRIMITIVES_CSS + _MOBILE_OVERRIDES_CSS


def design_tokens_style_block() -> str:
    """Return ``<style>`` element wrapping :func:`design_tokens_css`."""
    return f"<style>{design_tokens_css()}</style>"


__all__ = [
    "design_tokens_css",
    "design_tokens_style_block",
]
