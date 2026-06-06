"""Sandboxed artifact-serving FastAPI routes + dashboard-relative URL resolution.

Chrome blocks navigation from ``http://`` (the dashboard) to ``file://`` URLs,
so the legacy ``report_path.as_uri()`` link silently fails. Serve any file under
``DATA_DIR`` through a NiceGUI / FastAPI route instead — the browser stays on
``http://`` and the artifact opens in a new tab as a real text/html / text/csv
response. Path traversal is blocked by ``resolve()`` + ``relative_to(DATA_DIR)``.
"""
from __future__ import annotations

from pathlib import Path
from urllib.parse import quote

from fastapi import HTTPException, Query
from fastapi.responses import FileResponse
from nicegui import app as nicegui_app

from market_helper.app.paths import DATA_DIR
from market_helper.application.portfolio_monitor.services import (
    DEFAULT_COMBINED_REPORT_PATH,
)
from market_helper.presentation.dashboard.pages.portfolio_monitor.state import (
    PortfolioPageState,
    _optional_text,
)

_GENERATED_HTML_ROUTE = "/portfolio/generated-html"
_GENERATED_HTML_ROUTE_REGISTERED = False
# Pretty alias for the canonical combined report. Lets users share /
# bookmark `http://<host>:<port>/portfolio/portfolio_dashboard_report.html`
# instead of the legacy `?path=<absolute-fs-path>` form. Accessing the same
# file via either URL is fine; we just prefer the clean one for the iframe
# embed + any external sharing (e.g. via Tailscale).
_DASHBOARD_REPORT_ROUTE = "/portfolio/portfolio_dashboard_report.html"
_DASHBOARD_REPORT_ROUTE_REGISTERED = False


def _register_generated_html_route() -> None:
    """Register a single FastAPI route that serves any file under `DATA_DIR`.

    The route is idempotent: subsequent registration calls noop. Path traversal
    is blocked by `Path.resolve()` + `is_relative_to(DATA_DIR.resolve())`, so the
    route can only return artifacts the rest of the dashboard could already see.
    """
    global _GENERATED_HTML_ROUTE_REGISTERED
    if _GENERATED_HTML_ROUTE_REGISTERED:
        return

    @nicegui_app.get(_GENERATED_HTML_ROUTE)
    async def serve_generated_html(path: str = Query(...)) -> FileResponse:  # type: ignore[no-redef]
        target = Path(path).expanduser()
        if not target.is_absolute():
            target = (DATA_DIR / target).resolve()
        else:
            target = target.resolve()
        try:
            target.relative_to(DATA_DIR.resolve())
        except ValueError as exc:
            raise HTTPException(status_code=403, detail="Path is outside the allowed artifact root") from exc
        if not target.is_file():
            raise HTTPException(status_code=404, detail=f"Artifact not found: {target}")
        suffix = target.suffix.lower()
        media_type = {
            ".html": "text/html; charset=utf-8",
            ".csv": "text/csv; charset=utf-8",
            ".json": "application/json; charset=utf-8",
            ".feather": "application/octet-stream",
        }.get(suffix, "application/octet-stream")
        # `no-cache` lets the browser keep the body but forces it to revalidate
        # with the server on every request (304 when the file is unchanged, 200
        # with the new body when the dashboard regenerates the artifact). Without
        # this, browsers keep serving the stale copy after a regenerate.
        return FileResponse(
            target,
            media_type=media_type,
            headers={"Cache-Control": "no-cache"},
        )

    _GENERATED_HTML_ROUTE_REGISTERED = True


def _register_dashboard_report_route() -> None:
    """Register the pretty alias for the canonical combined report.

    A GET to ``/portfolio/portfolio_dashboard_report.html`` serves the file
    at :data:`DEFAULT_COMBINED_REPORT_PATH` directly — no query string, no
    absolute-path leak in the URL. Mirrors the headers of the legacy
    generated-html route so cross-device refresh (e.g. via Tailscale) keeps
    working: ``Cache-Control: no-cache`` forces the browser to revalidate
    on every load instead of serving a stale cached body.

    Idempotent: subsequent calls noop.
    """
    global _DASHBOARD_REPORT_ROUTE_REGISTERED
    if _DASHBOARD_REPORT_ROUTE_REGISTERED:
        return

    @nicegui_app.get(_DASHBOARD_REPORT_ROUTE)
    async def serve_dashboard_report() -> FileResponse:  # type: ignore[no-redef]
        target = DEFAULT_COMBINED_REPORT_PATH
        if not target.is_file():
            raise HTTPException(
                status_code=404,
                detail=(
                    f"Combined report not yet generated at {target}. Click "
                    "'Generate Combined Report' in the dashboard to produce it."
                ),
            )
        return FileResponse(
            target,
            media_type="text/html; charset=utf-8",
            headers={"Cache-Control": "no-cache"},
        )

    _DASHBOARD_REPORT_ROUTE_REGISTERED = True


def _served_artifact_url(target: Path | str | None) -> str | None:
    """Return a dashboard-relative URL that serves `target`.

    Prefers the pretty alias ``/portfolio/portfolio_dashboard_report.html``
    when ``target`` IS the canonical combined report; falls back to the
    generic ``/portfolio/generated-html?path=...`` route for any other
    artifact under ``DATA_DIR`` (CSVs, JSON, feather, etc.).

    Returns None when the path is empty / outside ``DATA_DIR`` / does not
    exist on disk — callers should fall back to a plain label rather than
    render a broken link.
    """
    if target is None:
        return None
    candidate = Path(str(target)).expanduser()
    if not candidate.is_absolute() or not candidate.exists():
        return None
    resolved = candidate.resolve()
    try:
        resolved.relative_to(DATA_DIR.resolve())
    except ValueError:
        return None
    if resolved == DEFAULT_COMBINED_REPORT_PATH.resolve():
        return _DASHBOARD_REPORT_ROUTE
    return f"{_GENERATED_HTML_ROUTE}?path={quote(str(candidate))}"


def _current_report_output_path(state: PortfolioPageState) -> Path | None:
    candidates = [
        str(state.generated_report.output_path) if state.generated_report is not None else None,
        _optional_text(state.action_statuses["combined"].last_output_path),
        _optional_text(state.export_form.output_path),
    ]
    for candidate in candidates:
        if candidate:
            return Path(candidate)
    return None
