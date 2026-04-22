from __future__ import annotations

from dataclasses import dataclass, field
import html
from typing import Sequence

from market_helper.common.datetime_display import format_local_datetime


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


def render_report_document(document: ReportDocument) -> str:
    if not document.sections:
        raise ValueError("ReportDocument requires at least one section")

    nav_html = "".join(
        _render_nav_button(section, active=index == 0)
        for index, section in enumerate(document.sections)
    )
    sections_html = "".join(
        _render_section(section, active=index == 0)
        for index, section in enumerate(document.sections)
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

    subtitle_html = ""
    if document.subtitle:
        subtitle_html = f"<p class='report-hero__subtitle'>{html.escape(document.subtitle)}</p>"

    return f"""<!doctype html>
<html lang='en'>
<head>
  <meta charset='utf-8' />
  <meta name='viewport' content='width=device-width, initial-scale=1' />
  <title>{html.escape(document.title)}</title>
  <style>
    :root {{
      --page-bg: #f7f4ec;
      --panel-bg: rgba(255,255,255,0.92);
      --panel-border: rgba(148, 163, 184, 0.22);
      --hero-ink: #0f172a;
      --muted-ink: #475569;
      --accent: #0f766e;
      --accent-soft: #ccfbf1;
      --accent-warm: #c2410c;
      --accent-warm-soft: #ffedd5;
      --shadow: 0 24px 80px rgba(15, 23, 42, 0.08);
      --table-header: #f8fafc;
      --table-border: #e2e8f0;
      --row-alt: #fcfcfd;
      --excluded-bg: #fff7ed;
      --warning-bg: #fff7ed;
      --warning-border: #fdba74;
      --font-sans: "Iowan Old Style", "Palatino Linotype", "Book Antiqua", Georgia, serif;
      --font-ui: "Avenir Next", "Helvetica Neue", Helvetica, Arial, sans-serif;
    }}
    * {{ box-sizing: border-box; }}
    html {{ scroll-behavior: smooth; }}
    body {{
      margin: 0;
      color: var(--hero-ink);
      background:
        radial-gradient(circle at top left, rgba(13, 148, 136, 0.14), transparent 28%),
        radial-gradient(circle at top right, rgba(249, 115, 22, 0.12), transparent 24%),
        linear-gradient(180deg, #fffdf8 0%, var(--page-bg) 58%, #f8fafc 100%);
      font-family: var(--font-ui);
    }}
    .report-shell {{
      max-width: 1540px;
      margin: 0 auto;
      padding: 40px 24px 56px;
    }}
    .report-hero {{
      padding: 30px 32px;
      border: 1px solid var(--panel-border);
      border-radius: 28px;
      background:
        linear-gradient(135deg, rgba(255,255,255,0.95), rgba(248,250,252,0.88)),
        linear-gradient(90deg, rgba(15, 118, 110, 0.04), rgba(194, 65, 12, 0.04));
      box-shadow: var(--shadow);
      margin-bottom: 20px;
    }}
    .report-hero__eyebrow {{
      margin: 0 0 10px;
      font-size: 12px;
      letter-spacing: 0.16em;
      text-transform: uppercase;
      color: var(--accent);
      font-weight: 700;
    }}
    .report-hero h1 {{
      margin: 0;
      font-family: var(--font-sans);
      font-size: clamp(34px, 4vw, 56px);
      line-height: 0.98;
    }}
    .report-hero__subtitle {{
      margin: 12px 0 0;
      font-size: 16px;
      max-width: 920px;
      color: var(--muted-ink);
    }}
    .report-nav {{
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      margin: 0 0 18px;
    }}
    .report-nav__button {{
      appearance: none;
      border: 1px solid rgba(15, 23, 42, 0.1);
      background: rgba(255,255,255,0.7);
      color: var(--hero-ink);
      border-radius: 999px;
      padding: 10px 16px;
      font-weight: 700;
      font-size: 13px;
      cursor: pointer;
      transition: background 140ms ease, color 140ms ease, transform 140ms ease, border-color 140ms ease;
    }}
    .report-nav__button:hover {{
      transform: translateY(-1px);
      border-color: rgba(15, 118, 110, 0.35);
    }}
    .report-nav__button.is-active {{
      background: linear-gradient(135deg, var(--accent), #115e59);
      color: #fff;
      border-color: transparent;
      box-shadow: 0 12px 28px rgba(15, 118, 110, 0.22);
    }}
    .report-alert {{
      margin-bottom: 18px;
      padding: 14px 16px;
      border-radius: 18px;
      border: 1px solid var(--warning-border);
      background: var(--warning-bg);
      color: #9a3412;
    }}
    .report-alert ul {{
      margin: 10px 0 0;
      padding-left: 18px;
    }}
    .report-section[hidden] {{ display: none !important; }}
    .report-section__header {{
      margin-bottom: 18px;
    }}
    .report-section__title {{
      margin: 0;
      font-family: var(--font-sans);
      font-size: 30px;
    }}
    .report-section__summary {{
      margin: 8px 0 0;
      color: var(--muted-ink);
      max-width: 840px;
    }}
    .card {{
      background: var(--panel-bg);
      border: 1px solid var(--panel-border);
      border-radius: 22px;
      box-shadow: 0 12px 40px rgba(15, 23, 42, 0.05);
      padding: 20px;
      margin-bottom: 16px;
      backdrop-filter: blur(10px);
    }}
    .card h2 {{
      margin: 0 0 12px;
      font-family: var(--font-sans);
      font-size: 24px;
    }}
    .card p {{
      color: var(--muted-ink);
      line-height: 1.55;
    }}
    .metrics {{
      display: grid;
      gap: 12px;
      grid-template-columns: repeat(auto-fit, minmax(190px, 1fr));
    }}
    .metric {{
      padding: 14px 16px;
      border-radius: 18px;
      background: linear-gradient(180deg, rgba(248,250,252,0.9), rgba(255,255,255,0.98));
      border: 1px solid rgba(226, 232, 240, 0.95);
    }}
    .metric span {{
      display: block;
      font-size: 12px;
      font-weight: 700;
      letter-spacing: 0.03em;
      text-transform: uppercase;
      color: var(--muted-ink);
      margin-bottom: 6px;
    }}
    .metric strong {{
      font-size: 26px;
      font-family: var(--font-sans);
    }}
    .report-table-wrap {{
      overflow: auto;
      border: 1px solid var(--table-border);
      border-radius: 18px;
      background: rgba(255,255,255,0.92);
    }}
    .report-table {{
      width: 100%;
      border-collapse: separate;
      border-spacing: 0;
      min-width: 720px;
      font-size: 14px;
    }}
    .report-table__header {{
      position: sticky;
      top: 0;
      z-index: 1;
      background: var(--table-header);
      border-bottom: 1px solid var(--table-border);
      padding: 11px 14px;
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: 0.05em;
      color: var(--muted-ink);
      white-space: nowrap;
    }}
    .report-table__cell {{
      padding: 12px 14px;
      border-bottom: 1px solid var(--table-border);
      vertical-align: top;
    }}
    .report-table__row:nth-child(even) .report-table__cell {{
      background: var(--row-alt);
    }}
    .report-table__row.is-excluded .report-table__cell {{
      background: var(--excluded-bg);
    }}
    .report-table__row:last-child .report-table__cell {{
      border-bottom: 0;
    }}
    .report-table__empty td {{
      padding: 18px 14px;
      color: var(--muted-ink);
    }}
    .is-num {{
      text-align: right;
      font-variant-numeric: tabular-nums;
    }}
    .is-center {{ text-align: center; }}
    .is-start {{ text-align: left; }}
    .tone-positive {{ color: #166534; font-weight: 700; }}
    .tone-negative {{ color: #b91c1c; font-weight: 700; }}
    .tone-muted {{ color: var(--muted-ink); }}
    .tag {{
      display: inline-flex;
      align-items: center;
      padding: 4px 8px;
      border-radius: 999px;
      font-size: 12px;
      font-weight: 700;
      background: #eef2ff;
      color: #3730a3;
    }}
    .tag--warning {{
      background: #fff7ed;
      color: #9a3412;
    }}
    .scores {{
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      color: var(--muted-ink);
    }}
    .chart {{ display: grid; gap: 8px; margin-bottom: 14px; }}
    .chart-row {{ display: grid; grid-template-columns: 150px 1fr 80px; gap: 12px; align-items: center; }}
    .chart-track {{ position: relative; height: 14px; border-radius: 999px; background: #e2e8f0; overflow: hidden; }}
    .chart-midline {{ position: absolute; left: 50%; top: 0; bottom: 0; width: 1px; background: #94a3b8; }}
    .chart-fill-pos {{ position: absolute; left: 50%; top: 0; bottom: 0; background: linear-gradient(90deg, #14b8a6, #0f766e); }}
    .chart-fill-neg {{ position: absolute; top: 0; bottom: 0; background: linear-gradient(90deg, #fb923c, #c2410c); }}
    .chart-value {{ text-align: right; color: var(--muted-ink); font-size: 12px; font-variant-numeric: tabular-nums; }}
    .perf-plot {{ min-height: 520px; }}
    .sparkline {{ width: 120px; height: 28px; }}
    @media (max-width: 840px) {{
      .report-shell {{ padding: 24px 12px 40px; }}
      .report-hero {{ padding: 24px 18px; border-radius: 22px; }}
      .card {{ padding: 16px; border-radius: 18px; }}
      .report-table {{ min-width: 620px; }}
      .chart-row {{ grid-template-columns: 120px 1fr 72px; }}
    }}
  </style>
  {document.head_html}
</head>
<body>
  <main class='report-shell'>
    <header class='report-hero'>
      <p class='report-hero__eyebrow'>Market Helper HTML Report</p>
      <h1>{html.escape(document.title)}</h1>
      {subtitle_html}
      <p class='report-hero__subtitle'>As of {html.escape(format_local_datetime(document.as_of))}</p>
    </header>
    {warnings_html}
    <nav class='report-nav' aria-label='Report Sections'>
      {nav_html}
    </nav>
    {sections_html}
  </main>
  <script>
    (function () {{
      const buttons = Array.from(document.querySelectorAll('[data-report-tab]'));
      const sections = Array.from(document.querySelectorAll('[data-report-section]'));
      const activate = function (target) {{
        buttons.forEach((button) => {{
          const active = button.getAttribute('data-report-tab') === target;
          button.classList.toggle('is-active', active);
          button.setAttribute('aria-selected', active ? 'true' : 'false');
        }});
        sections.forEach((section) => {{
          const active = section.getAttribute('data-report-section') === target;
          if (active) {{
            section.removeAttribute('hidden');
          }} else {{
            section.setAttribute('hidden', '');
          }}
        }});
        const plots = document.querySelectorAll('.perf-plot');
        if (typeof window.__marketHelperResizePerformancePlots === 'function') {{
          plots.forEach(() => window.__marketHelperResizePerformancePlots(document));
        }}
      }};
      buttons.forEach((button) => {{
        button.addEventListener('click', () => activate(button.getAttribute('data-report-tab')));
      }});
    }})();
  </script>
  {document.body_end_html}
</body>
</html>
"""


def _render_nav_button(section: ReportSection, *, active: bool) -> str:
    classes = "report-nav__button is-active" if active else "report-nav__button"
    return (
        f"<button type='button' class='{classes}' data-report-tab='{html.escape(section.key)}' "
        f"aria-selected='{'true' if active else 'false'}'>{html.escape(section.title)}</button>"
    )


def _render_section(section: ReportSection, *, active: bool) -> str:
    summary = ""
    if section.summary:
        summary = f"<p class='report-section__summary'>{html.escape(section.summary)}</p>"
    hidden_attr = "" if active else " hidden"
    return (
        f"<section class='report-section' data-report-section='{html.escape(section.key)}'{hidden_attr}>"
        "<header class='report-section__header'>"
        f"<h2 class='report-section__title'>{html.escape(section.title)}</h2>"
        f"{summary}"
        "</header>"
        f"{section.body_html}"
        "</section>"
    )
