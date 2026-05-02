from __future__ import annotations

from dataclasses import dataclass, field
import html
from typing import Sequence

from market_helper.common.datetime_display import format_local_datetime
from market_helper.reporting._design_tokens import design_tokens_css


@dataclass(frozen=True)
class ReportSection:
    key: str
    title: str
    body_html: str
    summary: str | None = None


@dataclass(frozen=True)
class ReportDocument:
    title: str
    as_of: str
    sections: Sequence[ReportSection]
    subtitle: str | None = None
    warning_messages: Sequence[str] = field(default_factory=tuple)
    head_html: str = ""
    body_end_html: str = ""
    # P4 additions: optional inline HTML rendered in the sticky chrome.
    # `topline_html` is typically the 8-column KPI strip; `ribbon_html` is
    # reserved for the regime ribbon added in P5.
    topline_html: str = ""
    ribbon_html: str = ""


def render_report_document(document: ReportDocument) -> str:
    if not document.sections:
        raise ValueError("ReportDocument requires at least one section")

    nav_html = "".join(
        _render_nav_link(section, active=index == 0)
        for index, section in enumerate(document.sections)
    )
    sections_html = "".join(
        _render_section(section)
        for section in document.sections
    )
    warnings_html = ""
    if document.warning_messages:
        warning_items = "".join(f"<li>{html.escape(message)}</li>" for message in document.warning_messages)
        warnings_html = (
            "<aside class='report-alert'>"
            "<strong>Warnings</strong>"
            f"<ul>{warning_items}</ul>"
            "</aside>"
        )

    # Subtitle is no longer rendered as visible chrome — the slim app-bar replaced
    # the editorial hero. Surface it as a screen-reader-friendly meta description so
    # context is still discoverable for assistive tech without burning viewport space.
    subtitle_meta = ""
    if document.subtitle:
        subtitle_meta = f"<meta name='description' content='{html.escape(document.subtitle, quote=True)}' />"

    ribbon_html = document.ribbon_html
    topline_html = document.topline_html

    return f"""<!doctype html>
<html lang='en'>
<head>
  <meta charset='utf-8' />
  <meta name='viewport' content='width=device-width, initial-scale=1' />
  {subtitle_meta}
  <title>{html.escape(document.title)}</title>
  <style>
    {design_tokens_css()}
    * {{ box-sizing: border-box; }}
    html {{ scroll-behavior: smooth; }}
    body {{
      margin: 0;
      color: var(--ink);
      background: var(--bg);
      font-family: var(--font-ui);
      font-size: 14px;
      line-height: 1.45;
      -webkit-font-smoothing: antialiased;
    }}
    /* Sticky app-bar (P4): brand + section nav + as-of + actions in a single row */
    .app-bar {{
      position: sticky; top: 0; z-index: 30;
      background: rgba(255,255,255,0.85);
      backdrop-filter: saturate(140%) blur(8px);
      border-bottom: 1px solid var(--panel-border);
    }}
    .app-bar__row {{
      max-width: 1540px; margin: 0 auto;
      padding: 12px 24px;
      display: grid; grid-template-columns: auto 1fr auto;
      align-items: center; gap: 20px;
    }}
    .app-bar__brand {{ display: flex; align-items: center; gap: 8px; font-weight: 700; }}
    .app-bar__brand-dot {{
      width: 8px; height: 8px; border-radius: 999px; background: var(--accent);
      box-shadow: 0 0 0 3px var(--accent-soft);
    }}
    .app-bar__brand-name {{ font-size: 13px; letter-spacing: 0.02em; }}
    .app-bar__brand-sep {{ color: var(--muted-2); }}
    .app-bar__brand-title {{ font-weight: 600; }}
    .app-bar__meta {{ font-size: 12px; color: var(--muted-ink); font-variant-numeric: tabular-nums; }}
    .section-nav {{
      display: flex; gap: 2px; justify-self: center;
      background: var(--surface-2); padding: 4px; border-radius: 999px;
      border: 1px solid var(--border-soft);
    }}
    .section-nav__button {{
      appearance: none; border: 0; background: transparent; cursor: pointer;
      padding: 6px 12px; font: inherit; font-size: 13px; font-weight: 600;
      color: var(--ink-2); text-decoration: none; border-radius: 999px;
    }}
    .section-nav__button:hover {{ background: rgba(15,23,42,0.05); color: var(--ink); }}
    .section-nav__button.is-active {{ background: var(--ink); color: #fff; }}
    .section-nav__button:focus-visible {{ outline: 2px solid var(--accent); outline-offset: 2px; border-radius: 999px; }}

    /* KPI strip (P4): above-the-fold answers */
    .kpi-strip-wrap {{ max-width: 1540px; margin: 0 auto; padding: 16px 24px 0; }}
    .kpi-strip {{
      display: grid; gap: 1px; background: var(--panel-border);
      border: 1px solid var(--panel-border); border-radius: var(--r-3); overflow: hidden;
      box-shadow: var(--shadow-1);
    }}
    .kpi {{ background: var(--surface); padding: 12px 16px; display: flex; flex-direction: column; gap: 2px; }}
    .kpi__label {{ font-size: 11px; letter-spacing: 0.04em; text-transform: uppercase; color: var(--muted-ink); font-weight: 600; }}
    .kpi__value {{ font-size: 20px; font-weight: 600; line-height: 1.1; font-variant-numeric: tabular-nums; }}
    .kpi__sub {{ font-size: 11px; color: var(--muted-ink); font-variant-numeric: tabular-nums; }}
    .kpi__value.tone-positive, .kpi__value.tone-negative {{ font-weight: 600; }}
    .kpi__value.is-warn {{ color: var(--warn); }}

    .report-shell {{ max-width: 1540px; margin: 0 auto; padding: 16px 24px 40px; }}
    .report-alert {{
      margin: 0 0 16px;
      padding: 12px 14px; border-radius: var(--r-2);
      border: 1px solid var(--warning-border);
      background: var(--warning-bg); color: var(--warn);
    }}
    .report-alert ul {{ margin: 8px 0 0; padding-left: 18px; }}
    .report-section {{ scroll-margin-top: 64px; margin-top: 32px; }}
    .report-section:first-of-type {{ margin-top: 0; }}
    .report-section__header {{ margin-bottom: 12px; display: flex; align-items: baseline; justify-content: space-between; gap: 16px; }}
    .report-section__title {{ margin: 0; font-family: var(--font-sans); font-size: 18px; font-weight: 700; }}
    .report-section__summary {{ margin: 0; color: var(--muted-ink); max-width: 840px; font-size: 12px; }}

    :focus-visible {{ outline: 2px solid var(--accent); outline-offset: 2px; border-radius: 4px; }}

    /* Card, KpiCard, Table, Tag, BarRow, alignment + tone helpers, sparkline are
       provided by `_design_tokens.design_tokens_css()` (P2 of the redesign track). */
  </style>
  {document.head_html}
</head>
<body>
  <header class='app-bar'>
    <div class='app-bar__row'>
      <div class='app-bar__brand'>
        <span class='app-bar__brand-dot' aria-hidden='true'></span>
        <span class='app-bar__brand-name'>Market Helper</span>
        <span class='app-bar__brand-sep'>/</span>
        <span class='app-bar__brand-title'>{html.escape(document.title)}</span>
      </div>
      <nav class='section-nav' aria-label='Report Sections'>
        {nav_html}
      </nav>
      <div class='app-bar__meta'>As of {html.escape(format_local_datetime(document.as_of))}</div>
    </div>
  </header>
  {ribbon_html}
  {topline_html}
  <main class='report-shell'>
    {warnings_html}
    {sections_html}
  </main>
  <script>
    (function () {{
      const links = Array.from(document.querySelectorAll('.section-nav__button'));
      const sections = Array.from(document.querySelectorAll('.report-section'));
      function setActive(id) {{
        links.forEach(function (link) {{
          const active = link.getAttribute('href') === '#' + id;
          link.classList.toggle('is-active', active);
          link.setAttribute('aria-current', active ? 'true' : 'false');
        }});
      }}
      if (typeof IntersectionObserver === 'function' && sections.length > 0) {{
        const io = new IntersectionObserver(function (entries) {{
          entries.forEach(function (entry) {{ if (entry.isIntersecting) {{ setActive(entry.target.id); }} }});
        }}, {{ rootMargin: '-40% 0px -55% 0px' }});
        sections.forEach(function (section) {{ io.observe(section); }});
      }}
      // Honor `?section=...` query on initial load by jumping to the matching anchor.
      const params = new URLSearchParams(window.location.search);
      const requested = params.get('section');
      if (requested) {{
        const target = document.getElementById(requested);
        if (target) {{ target.scrollIntoView({{ block: 'start' }}); }}
      }}
    }})();
  </script>
  {document.body_end_html}
</body>
</html>
"""


def _render_nav_link(section: ReportSection, *, active: bool) -> str:
    """Render a hash-routed anchor for the section nav.

    The IntersectionObserver in the rendered page flips the `is-active` class as
    the user scrolls, so the initial `active` flag is just the first-paint hint.
    """
    classes = "section-nav__button is-active" if active else "section-nav__button"
    aria_current = " aria-current='true'" if active else ""
    return (
        f"<a class='{classes}' href='#{html.escape(section.key, quote=True)}'"
        f"{aria_current}>{html.escape(section.title)}</a>"
    )


def _render_section(section: ReportSection) -> str:
    """Render a stacked section. Sections are always visible (P4 hash routing)."""
    summary = ""
    if section.summary:
        summary = f"<p class='report-section__summary'>{html.escape(section.summary)}</p>"
    title = (
        f"<h2 class='report-section__title'>{html.escape(section.title)}</h2>"
    )
    return (
        f"<section id='{html.escape(section.key, quote=True)}' class='report-section'"
        f" data-report-section='{html.escape(section.key, quote=True)}'>"
        f"<header class='report-section__header'>{title}{summary}</header>"
        f"{section.body_html}"
        "</section>"
    )
