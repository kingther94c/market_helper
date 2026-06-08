"""Static HTML snapshot of the trade-advisor decision journal.

A read-only, self-contained page listing the operator's flagged
(Proceed / Monitor) ideas. Written to ``data/artifacts/trade_advisor/`` and
mirrored to GDrive (cross-device, like the combined report) — the interactive
``/advisor`` page stays localhost/Tailscale.

Pure string rendering (unit-tested); inline ``<script>``-free so it opens via
``file://`` or the dashboard's sandboxed HTML route.
"""

from __future__ import annotations

import html

from market_helper.trade_advisor.journal import Decision

_LABEL_COLOR = {"PROMOTE": "#1a7f37", "WATCH": "#9a6700", "DISMISS": "#cf222e"}

_STYLE = (
    "body{font-family:system-ui,Segoe UI,Arial,sans-serif;margin:24px;color:#1f2328}"
    ".muted{color:#57606a}.banner{color:#57606a;font-size:12px;margin:8px 0 16px}"
    ".ta-table{border-collapse:collapse;width:100%}"
    ".ta-table th,.ta-table td{border:1px solid #d0d7de;padding:6px 10px;text-align:left;font-size:13px}"
    ".ta-table th{background:#f6f8fa}"
)


def render_trade_advisor_section_body(decisions: list[Decision]) -> str:
    """HTML table of the flagged decisions (or an empty-state note)."""
    if not decisions:
        return "<p class='muted'>No flagged ideas yet — use the Advisor page to Promote/Watch an idea.</p>"
    rows = []
    for d in decisions:
        color = _LABEL_COLOR.get(d.decision, "#57606a")
        rows.append(
            "<tr>"
            f"<td><span style='color:{color};font-weight:600'>{html.escape(d.decision)}</span></td>"
            f"<td>{html.escape(d.advisor)}</td>"
            f"<td>{html.escape(d.subject)}</td>"
            f"<td>{html.escape(d.title)}</td>"
            f"<td>{html.escape(d.ts[:16])}</td>"
            f"<td>{html.escape(d.note)}</td>"
            "</tr>"
        )
    return (
        "<table class='ta-table'><thead><tr>"
        "<th>Decision</th><th>Advisor</th><th>Subject</th><th>Idea</th><th>When</th><th>Note</th>"
        f"</tr></thead><tbody>{''.join(rows)}</tbody></table>"
    )


def render_trade_advisor_snapshot(decisions: list[Decision], *, as_of: str = "") -> str:
    """Full standalone HTML document for the flagged-ideas snapshot."""
    return (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        "<title>Trade Advisor — flagged ideas</title>"
        f"<style>{_STYLE}</style></head><body>"
        "<h2>Trade Advisor — flagged ideas (Promote / Watch)</h2>"
        f"<div class='banner'>Read-only advisory snapshot · as of {html.escape(as_of or '—')} · "
        "ideas, not orders · generated from the decision journal</div>"
        f"{render_trade_advisor_section_body(decisions)}"
        "</body></html>"
    )
