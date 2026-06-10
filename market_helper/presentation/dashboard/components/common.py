from __future__ import annotations

from datetime import datetime
import re
from typing import Any

from nicegui import ui

from market_helper.reporting._design_tokens import design_tokens_style_block

_ISO_UTC_TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?\+00:00$")


def add_dashboard_styles() -> None:
    # Inject shared design tokens first so the dashboard-specific `.pm-*` rules below
    # consume the same palette/type/radius scale as the embedded HTML report. P6
    # closes the iframe seam by aligning the dashboard chrome with the report's
    # `.app-bar` pattern; the editorial slate-blue gradient hero is retired here.
    ui.add_head_html(design_tokens_style_block())
    ui.add_head_html(
        """
        <style>
          body { background: var(--bg); color: var(--ink); font-family: var(--font-ui); font-size: 14px; line-height: 1.45; -webkit-font-smoothing: antialiased; }
          .pm-shell { gap: 16px; }

          /* Sticky app-bar — mirrors the report's `.app-bar` so the iframe seam closes.
             Padding uses `--content-pad` so mobile gutter automatically follows the
             framework override in `_design_tokens._RESPONSIVE_FRAMEWORK_CSS`. */
          .pm-app-bar {
            position: sticky; top: 0; z-index: 30;
            background: rgba(255,255,255,0.85);
            backdrop-filter: saturate(140%) blur(8px);
            border-bottom: 1px solid var(--panel-border);
            padding: 12px var(--content-pad);
            display: flex; align-items: center; gap: 20px;
            flex-wrap: wrap;
          }
          .pm-app-bar__brand { display: flex; align-items: center; gap: 8px; font-weight: 700; }
          .pm-app-bar__brand-dot { width: 8px; height: 8px; border-radius: 999px; background: var(--accent); box-shadow: 0 0 0 3px var(--accent-soft); }
          .pm-app-bar__brand-name { font-size: 13px; letter-spacing: 0.02em; }
          .pm-app-bar__brand-sep { color: var(--muted-2); }
          .pm-app-bar__brand-title { font-weight: 600; }
          .pm-app-bar__spacer { flex: 1; }
          .pm-app-bar__meta { font-size: 12px; color: var(--muted-ink); font-variant-numeric: tabular-nums; }
          .pm-app-bar__actions { display: flex; align-items: center; gap: 8px; }

          /* Cards re-skinned to match report `.card` token output. */
          .pm-card {
            background: var(--surface);
            border: 1px solid var(--panel-border);
            border-radius: var(--r-3);
            box-shadow: var(--shadow-1);
          }
          .pm-muted { color: var(--muted-ink); }
          .pm-warning { background: var(--warn-soft); border-left: 4px solid var(--warning-border); padding: 10px 12px; border-radius: var(--r-2); color: var(--warn); }
          .pm-error { background: var(--neg-soft); border-left: 4px solid var(--neg); padding: 10px 12px; border-radius: var(--r-2); color: var(--neg); }
          .pm-loading { background: var(--info-soft); border-left: 4px solid var(--info); padding: 10px 12px; border-radius: var(--r-2); color: var(--info); }
          .pm-log { max-height: 260px; overflow: auto; }

          /* Status chips — same semantic palette as the report. */
          .pm-status-chip { border-radius: 999px; padding: 2px 8px; font-size: 11px; font-weight: 600; }
          .pm-status-neutral { background: var(--surface-2); color: var(--muted-ink); }
          .pm-status-running { background: var(--info-soft); color: var(--info); }
          .pm-status-success { background: var(--pos-soft); color: var(--pos); }
          .pm-status-warning { background: var(--warn-soft); color: var(--warn); }
          .pm-status-error { background: var(--neg-soft); color: var(--neg); }

          /* Static tab buttons (used by the embedded reports' fallbacks). */
          .pm-static-tab-buttons { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 14px; }
          .pm-static-tab-button { appearance: none; border: 1px solid var(--border-soft); border-radius: 999px; padding: 6px 12px; background: var(--surface); color: var(--ink-2); font-weight: 600; font-size: 13px; cursor: pointer; }
          .pm-static-tab-button.is-active { background: var(--ink); color: #fff; border-color: var(--ink); }
          .pm-static-tab-panel { width: 100%; }
          .pm-static-tab-panel[hidden] { display: none !important; }

          /* KpiCard-style status card (replaces the slate-50 card chrome).
             Desktop keeps the `min-width: 180px` floor so paired cards in the
             toolbar look balanced; mobile (≤768px) drops it via the @media block
             below so the card can collapse to full-width without overflowing. */
          .pm-status-card { background: var(--surface); border: 1px solid var(--border-soft); border-radius: var(--r-2); padding: 12px 14px; box-shadow: var(--shadow-1); display: flex; flex-direction: column; gap: 4px; min-width: 180px; }
          .pm-status-card__title { font-size: 11px; letter-spacing: 0.04em; text-transform: uppercase; color: var(--muted-ink); font-weight: 600; }
          .pm-status-card__value { font-size: 14px; font-weight: 600; color: var(--ink); }
          .pm-status-card__detail { font-size: 11px; color: var(--muted-ink); font-variant-numeric: tabular-nums; }

          /* Embedded report iframe — bleeds into the dashboard chrome via solid surface bg.
             On mobile we drop the corner radius (the iframe goes edge-to-edge so the
             radius would carve into already-tight content) and grow the min-height a
             notch so the report doesn't compete with the address-bar collapse. */
          .pm-report-iframe { width: 100%; min-height: 78vh; border: 0; border-radius: var(--r-3); background: var(--surface); }

          /* P7 — operate drawer (slides over the right edge so /portfolio first-paint stays clean) */
          .pm-app-bar__primary { padding: 6px 14px; border-radius: var(--r-2); border: 1px solid var(--ink); background: var(--ink); color: #fff; font-size: 13px; font-weight: 600; cursor: pointer; }
          .pm-app-bar__primary:hover { background: #1e293b; }
          .pm-app-bar__primary[disabled] { opacity: 0.6; cursor: not-allowed; }
          .pm-app-bar__primary:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
          .pm-app-bar__operate { padding: 6px 12px; border-radius: var(--r-2); border: 1px solid var(--panel-border); background: var(--surface); color: var(--ink); font-size: 13px; font-weight: 600; cursor: pointer; }
          .pm-app-bar__operate:hover { background: var(--surface-2); }
          .pm-app-bar__operate:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
          .pm-drawer__close:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
          .pm-static-tab-button:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }

          .pm-drawer-backdrop {
            position: fixed; inset: 0; background: rgba(15,23,42,0.4);
            opacity: 0; pointer-events: none; transition: opacity 180ms ease;
            z-index: 40;
          }
          .pm-drawer {
            position: fixed; top: 0; right: 0; height: 100vh; width: min(520px, 92vw);
            background: var(--surface); border-left: 1px solid var(--panel-border);
            transform: translateX(100%); transition: transform 200ms ease;
            z-index: 50; overflow-y: auto;
            box-shadow: -12px 0 32px rgba(15,23,42,0.10);
            display: flex; flex-direction: column;
          }
          body.pm-drawer-open .pm-drawer { transform: translateX(0); }
          body.pm-drawer-open .pm-drawer-backdrop { opacity: 1; pointer-events: auto; }
          .pm-drawer__header { display: flex; align-items: center; justify-content: space-between; padding: 14px 18px; border-bottom: 1px solid var(--border-soft); position: sticky; top: 0; background: var(--surface); z-index: 1; }
          .pm-drawer__title { font-size: 14px; font-weight: 700; }
          .pm-drawer__close { appearance: none; border: 0; background: transparent; color: var(--muted-ink); font-size: 18px; line-height: 1; cursor: pointer; padding: 4px 8px; border-radius: var(--r-1); }
          .pm-drawer__close:hover { background: var(--surface-2); color: var(--ink); }
          .pm-drawer__body { padding: 16px 18px; display: flex; flex-direction: column; gap: 14px; }
          .pm-drawer__section-title { font-size: 11px; font-weight: 600; letter-spacing: 0.04em; text-transform: uppercase; color: var(--muted-ink); margin: 4px 0; }

          /* P8 — sticky progress strip directly under the app-bar while a job runs.
             `top` follows the shared `--app-bar-height` var so any future change to
             the app-bar height ripples through; mobile lifts to the mobile var via
             the responsive framework. */
          .pm-progress-strip { position: sticky; top: var(--app-bar-height); z-index: 25; background: var(--surface); border-bottom: 1px solid var(--border-soft); }
          .pm-progress-strip__row { max-width: var(--shell-max); margin: 0 auto; padding: 6px var(--content-pad) 4px; display: flex; align-items: baseline; justify-content: space-between; gap: 16px; font-size: 12px; flex-wrap: wrap; }
          .pm-progress-strip__label { font-weight: 600; color: var(--ink); }
          .pm-progress-strip__detail { color: var(--muted-ink); font-variant-numeric: tabular-nums; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
          .pm-progress-strip__bar { height: 3px; max-width: var(--shell-max); margin: 0 auto; }

          /* P10/P10.3 — light Quasar input/field overrides to align focus colour
             with the token system. Full ui.input → ui.element('input') swap is
             intentionally deferred (bind_value + label/validation behaviour are
             material rewrites for moderate visual win). */
          .pm-drawer .q-field--outlined .q-field__control:before { border-color: var(--panel-border); }
          .pm-drawer .q-field--outlined .q-field__control:hover:before { border-color: var(--ink-2); }
          .pm-drawer .q-field--focused .q-field__control:before { border-color: var(--accent); border-width: 2px; }
          .pm-drawer .q-field__label { color: var(--muted-ink); }
          .pm-drawer .q-field--focused .q-field__label { color: var(--accent); }

          /* P8 — recent-runs panel inside the operate drawer. */
          .pm-history { font-variant-numeric: tabular-nums; }
          .pm-history__row { display: grid; grid-template-columns: 80px 1fr auto auto; align-items: center; gap: 10px; }
          .pm-history__time { font-family: var(--font-num); font-size: 12px; color: var(--muted-ink); }
          .pm-history__action { font-size: 13px; font-weight: 600; }
          .pm-history__duration { font-family: var(--font-num); font-size: 11px; color: var(--muted-ink); }
          .pm-history__message { margin: 0 0 0 90px; }
          .pm-history__link, .pm-history__path { margin: 0 0 8px 90px; display: inline-block; }

          /* === Dashboard chrome — mobile (≤ 768px) ===========================
             Co-located with the shared framework so all `.pm-*` mobile rules live
             in one place. Anything that reuses `.pm-app-bar`, `.pm-status-card`,
             `.pm-drawer__body`, `.pm-history__row`, or the progress strip inherits
             these defaults — new dashboard surfaces don't need their own @media. */
          @media (max-width: 768px) {
            /* App-bar: keep spacer + actions on the natural flex row so actions
               are pushed to the right edge automatically. Meta sentence is hidden
               (the toolbar's "Report Data" card already surfaces `status_message`)
               so we avoid burning a third row on phones. */
            .pm-app-bar {
              padding: 8px var(--content-pad-mobile);
              gap: 12px;
              row-gap: 8px;
            }
            .pm-app-bar__meta { display: none; }
            .pm-app-bar__primary, .pm-app-bar__operate { padding: 8px 12px; }
            /* When actions wrap to a second row (brand + spacer + actions can't
               fit on 360px), the spacer stays on row 1 so without `margin-left:
               auto` actions land at the left edge of row 2 — visually broken.
               This pin keeps them right-aligned regardless of wrap. */
            .pm-app-bar__actions { margin-left: auto; }

            .pm-progress-strip { top: var(--app-bar-height-mobile); }
            .pm-progress-strip__row { padding: 6px var(--content-pad-mobile) 4px; }

            /* Stack status-card rows full-width — drops the desktop 180px floor. */
            .pm-status-card { min-width: 0; flex-basis: 100%; }

            /* Drawer body — collapse the NiceGUI `ui.grid(columns=N)` containers
               (artifact paths / live form / flex form / regime form / reference
               form) to a single column. `.nicegui-grid` is the class
               nicegui.ui.grid emits; no inline-style attribute fallback so we
               don't accidentally rewrite future inline-styled elements. */
            .pm-drawer__body .nicegui-grid {
              grid-template-columns: 1fr !important;
            }
            .pm-history__row { grid-template-columns: 70px 1fr; row-gap: 4px; }
            .pm-history__duration { grid-column: 2; justify-self: end; }
            .pm-history__message,
            .pm-history__link,
            .pm-history__path { margin-left: 0; }

            .pm-shell { gap: 12px; }
            .pm-report-iframe { min-height: 70vh; border-radius: 0; }
          }
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
        "warning": "pm-status-warning",
        "error": "pm-status-error",
    }.get(normalized, "pm-status-neutral")
    ui.label(status.title()).classes(f"pm-status-chip {css_class}")


def render_status_card(*, title: str, value: str, detail: str | None = None) -> None:
    # P6: switch from the legacy slate-50 ui.card to the token-driven `.pm-status-card`
    # primitive so dashboard status tiles match the report's `.metric` look.
    with ui.element("div").classes("pm-status-card"):
        ui.label(title).classes("pm-status-card__title")
        ui.label(value).classes("pm-status-card__value")
        if detail:
            ui.label(_format_status_detail(detail)).classes("pm-status-card__detail")


def _format_status_detail(detail: str) -> str:
    normalized = detail.strip()
    if not _ISO_UTC_TIMESTAMP_RE.match(normalized):
        return detail
    try:
        dt = datetime.fromisoformat(normalized)
    except ValueError:
        return detail
    return dt.astimezone().isoformat(timespec="seconds")
