from __future__ import annotations

"""Headless UI snapshot of the portfolio dashboard.

Drives the NiceGUI dashboard with Playwright, waits for the render sentinel
(``#snapshot-ready``), and writes a self-contained HTML file. Used by the
`risk-html-report` / `combined-html-report` CLI commands once the legacy
Jinja-style HTML renderer is retired.

Playwright is an optional dependency: install it with
``pip install playwright && playwright install chromium`` (the project
``scripts/setup_python_env.sh`` does this automatically).
"""

import asyncio
import socket
import threading
import time
from dataclasses import dataclass
from pathlib import Path


DEFAULT_SENTINEL = "#snapshot-ready"
DEFAULT_WAIT_SECONDS = 60.0


@dataclass(frozen=True)
class SnapshotRequest:
    output_path: Path
    route: str = "/portfolio"
    query: str = "snapshot=1"
    host: str = "127.0.0.1"
    port: int | None = None
    sentinel: str = DEFAULT_SENTINEL
    wait_seconds: float = DEFAULT_WAIT_SECONDS
    viewport_width: int = 1600
    viewport_height: int = 900


def pick_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _start_dashboard(host: str, port: int) -> threading.Thread:
    from market_helper.presentation.dashboard.app import create_app, patch_nicegui_process_pool_setup
    from nicegui import ui

    create_app()
    patch_nicegui_process_pool_setup()

    def _serve() -> None:
        ui.run(host=host, port=port, reload=False, show=False, title="Portfolio Monitor")

    thread = threading.Thread(target=_serve, name="market-helper-snapshot-ui", daemon=True)
    thread.start()
    _wait_for_port(host, port, timeout=30.0)
    return thread


def _wait_for_port(host: str, port: int, *, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((host, port), timeout=1.0):
                return
        except OSError:
            time.sleep(0.2)
    raise RuntimeError(f"Dashboard at {host}:{port} did not come up within {timeout:.0f}s")


async def _capture(request: SnapshotRequest) -> str:
    try:
        from playwright.async_api import async_playwright
    except ImportError as exc:  # pragma: no cover - optional dep
        raise RuntimeError(
            "playwright is not installed. Install with `pip install playwright && playwright install chromium`."
        ) from exc

    url = f"http://{request.host}:{request.port}{request.route}?{request.query}"
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            context = await browser.new_context(
                viewport={"width": request.viewport_width, "height": request.viewport_height}
            )
            page = await context.new_page()
            await page.goto(url, wait_until="networkidle")
            await page.wait_for_selector(request.sentinel, timeout=int(request.wait_seconds * 1000))
            return await page.content()
        finally:
            await browser.close()


def capture_snapshot(request: SnapshotRequest) -> Path:
    """Start the dashboard in-process, navigate, capture HTML, write to disk."""
    port = request.port or pick_free_port()
    resolved = SnapshotRequest(
        output_path=request.output_path,
        route=request.route,
        query=request.query,
        host=request.host,
        port=port,
        sentinel=request.sentinel,
        wait_seconds=request.wait_seconds,
        viewport_width=request.viewport_width,
        viewport_height=request.viewport_height,
    )
    _start_dashboard(resolved.host, port)
    html = asyncio.run(_capture(resolved))
    resolved.output_path.parent.mkdir(parents=True, exist_ok=True)
    resolved.output_path.write_text(html, encoding="utf-8")
    return resolved.output_path


__all__ = [
    "DEFAULT_SENTINEL",
    "DEFAULT_WAIT_SECONDS",
    "SnapshotRequest",
    "capture_snapshot",
    "pick_free_port",
]
