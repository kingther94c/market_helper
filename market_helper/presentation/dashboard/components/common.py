from __future__ import annotations

from datetime import datetime
import re
from typing import Any

from nicegui import ui

_ISO_UTC_TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?\+00:00$")


def add_dashboard_styles() -> None:
    ui.add_head_html(
        """
        <style>
          body { background: linear-gradient(180deg, #f6f8fb 0%, #eef3f8 100%); }
          .pm-shell { gap: 20px; }
          .pm-hero { background: linear-gradient(135deg, #0f172a 0%, #1d4ed8 100%); color: white; border-radius: 18px; padding: 22px; }
          .pm-card { background: rgba(255,255,255,0.94); border-radius: 16px; border: 1px solid #dbe4ee; }
          .pm-muted { color: #5b6b7f; }
          .pm-warning { background: #fff7ed; border-left: 4px solid #f97316; padding: 10px 12px; border-radius: 10px; }
          .pm-error { background: #fef2f2; border-left: 4px solid #dc2626; padding: 12px 14px; border-radius: 10px; color: #991b1b; }
          .pm-loading { background: #eff6ff; border-left: 4px solid #2563eb; padding: 12px 14px; border-radius: 10px; color: #1d4ed8; }
          .pm-log { max-height: 260px; overflow: auto; }
          .pm-status-chip { border-radius: 999px; padding: 4px 10px; font-size: 12px; font-weight: 700; }
          .pm-status-neutral { background: #e2e8f0; color: #334155; }
          .pm-status-running { background: #dbeafe; color: #1d4ed8; }
          .pm-status-success { background: #dcfce7; color: #166534; }
          .pm-status-error { background: #fee2e2; color: #991b1b; }
          .pm-static-tab-buttons { display: flex; flex-wrap: wrap; gap: 10px; margin-bottom: 14px; }
          .pm-static-tab-button { appearance: none; border: 0; border-radius: 999px; padding: 10px 16px; background: #dbe4ee; color: #0f172a; font-weight: 700; cursor: pointer; }
          .pm-static-tab-button.is-active { background: #0f172a; color: white; }
          .pm-static-tab-panel { width: 100%; }
          .pm-static-tab-panel[hidden] { display: none !important; }
        </style>
        """
    )


def render_table(*, columns: list[dict[str, Any]], rows: list[dict[str, Any]], row_key: str) -> None:
    ui.table(columns=columns, rows=rows, row_key=row_key, pagination=10).classes("w-full")


def render_status_badge(status: str) -> None:
    normalized = status.strip().lower()
    css_class = {
        "running": "pm-status-running",
        "success": "pm-status-success",
        "error": "pm-status-error",
    }.get(normalized, "pm-status-neutral")
    ui.label(status.title()).classes(f"pm-status-chip {css_class}")


def render_status_card(*, title: str, value: str, detail: str | None = None) -> None:
    with ui.card().classes("min-w-[180px] p-3 bg-slate-50 shadow-none"):
        ui.label(title).classes("text-caption pm-muted")
        ui.label(value).classes("text-body2")
        if detail:
            ui.label(_format_status_detail(detail)).classes("text-caption pm-muted")


def _format_status_detail(detail: str) -> str:
    normalized = detail.strip()
    if not _ISO_UTC_TIMESTAMP_RE.match(normalized):
        return detail
    try:
        dt = datetime.fromisoformat(normalized)
    except ValueError:
        return detail
    return dt.astimezone().isoformat(timespec="seconds")
