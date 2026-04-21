from __future__ import annotations

"""Headless UI snapshot of the portfolio dashboard.

Drives the NiceGUI dashboard with Playwright, waits for the render sentinel
(``#snapshot-ready``), extracts the fully-rendered DOM plus all inline CSS,
inlines any ``/_nicegui/...`` stylesheets and fonts captured during
navigation, strips all runtime ``<script>`` tags (the DOM is already
hydrated), and writes a single self-contained HTML file.

The output is intentionally non-interactive: Plotly charts, Quasar buttons,
and NiceGUI event handlers are baked into the DOM at capture time, and no
JavaScript runs when the snapshot is viewed later. This keeps the result
fully offline-capable without the complexity of re-hydrating NiceGUI's
runtime from inlined assets.

Playwright is an optional dependency: install it with
``pip install playwright && playwright install chromium`` (the project
``scripts/setup_python_env.sh`` does this automatically).
"""

import asyncio
import base64
import re
import socket
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Mapping
from urllib.parse import urlsplit


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
    overrides: Mapping[str, str] | None = None
    launch_server: bool = True


@dataclass
class _Asset:
    url_path: str
    body: bytes
    content_type: str


def pick_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _start_dashboard(
    host: str,
    port: int,
    overrides: Mapping[str, str] | None = None,
) -> threading.Thread:
    from market_helper.presentation.dashboard.app import create_app, patch_nicegui_process_pool_setup
    from market_helper.presentation.dashboard.pages.portfolio import set_snapshot_overrides
    from nicegui import ui

    create_app()
    patch_nicegui_process_pool_setup()
    set_snapshot_overrides(dict(overrides) if overrides else None)

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
    assets: Dict[str, _Asset] = {}

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            context = await browser.new_context(
                viewport={"width": request.viewport_width, "height": request.viewport_height}
            )
            page = await context.new_page()

            async def _on_response(response) -> None:
                try:
                    path = urlsplit(response.url).path
                    if not path.startswith("/_nicegui/"):
                        return
                    if response.status >= 400:
                        return
                    body = await response.body()
                except Exception:
                    return
                content_type = (response.headers or {}).get("content-type", "")
                assets[path] = _Asset(url_path=path, body=body, content_type=content_type)

            page.on("response", lambda r: asyncio.create_task(_on_response(r)))

            await page.goto(url, wait_until="networkidle")
            await page.wait_for_selector(
                request.sentinel,
                state="attached",
                timeout=int(request.wait_seconds * 1000),
            )
            # Give late-loading stylesheets a moment to settle (NiceGUI loads
            # quasar + fonts after the initial render completes).
            await page.wait_for_timeout(500)
            html = await page.content()
        finally:
            await browser.close()

    return _ossify(html, assets)


# ---------------------------------------------------------------------------
# HTML post-processing
# ---------------------------------------------------------------------------

_SCRIPT_TAG_RE = re.compile(r"<script\b[^>]*>.*?</script>", re.IGNORECASE | re.DOTALL)
_SELF_CLOSING_SCRIPT_RE = re.compile(r"<script\b[^>]*/>", re.IGNORECASE)
_LINK_TAG_RE = re.compile(r"<link\b[^>]*?/?>", re.IGNORECASE)
_LINK_HREF_RE = re.compile(r'href="([^"]+)"', re.IGNORECASE)
_LINK_REL_RE = re.compile(r'rel="([^"]+)"', re.IGNORECASE)
_META_CHARSET_RE = re.compile(r"<meta\b[^>]*charset=", re.IGNORECASE)
_CSS_URL_RE = re.compile(r"url\(\s*(['\"]?)(?P<url>/_nicegui/[^)'\"\s]+)\1\s*\)")


def _ossify(html: str, assets: Dict[str, _Asset]) -> str:
    """Freeze the rendered DOM: strip all scripts, inline or strip all link tags."""

    html = _ensure_meta_charset(html)

    # 1. Strip every <script> tag - the DOM is already hydrated.
    rewritten = _SCRIPT_TAG_RE.sub("", html)
    rewritten = _SELF_CLOSING_SCRIPT_RE.sub("", rewritten)

    # 2. Process every <link> tag: inline captured stylesheets as <style> blocks,
    #    convert captured icons/fonts to data URIs, and drop modulepreload hints.
    css_blocks_to_prepend: list[str] = []

    def _link_replacement(match: re.Match[str]) -> str:
        tag = match.group(0)
        href_match = _LINK_HREF_RE.search(tag)
        rel_match = _LINK_REL_RE.search(tag)
        if not href_match:
            return tag
        href = href_match.group(1)
        rel = (rel_match.group(1) if rel_match else "").lower()

        if not href.startswith("/_nicegui/"):
            return tag  # external or already-data-URI link left alone
        if "modulepreload" in rel or "preload" in rel:
            return ""  # no runtime => no preloads needed

        asset = assets.get(href)
        if asset is None:
            # Unknown reference; drop to avoid broken file:// fetch offline.
            return ""

        if "stylesheet" in rel:
            css_text = _safe_decode(asset.body)
            css_text = _inline_css_urls(css_text, assets)
            css_blocks_to_prepend.append(css_text)
            return ""

        if "icon" in rel:
            mime = _classify_mime(href, asset.content_type)
            data_uri = _data_uri(asset.body, mime)
            return tag.replace(href, data_uri)

        # Other rel values we don't care about in a static snapshot.
        return ""

    rewritten = _LINK_TAG_RE.sub(_link_replacement, rewritten)

    # 3. Inline <style>-inlined CSS urls that reference /_nicegui/ assets
    #    (existing style tags, e.g. tailwind JIT output or Quasar imports).
    def _existing_style_sub(match: re.Match[str]) -> str:
        style_tag = match.group(0)
        open_idx = style_tag.find(">")
        close_idx = style_tag.rfind("</style")
        if open_idx < 0 or close_idx < 0 or close_idx <= open_idx:
            return style_tag
        head = style_tag[: open_idx + 1]
        body = style_tag[open_idx + 1 : close_idx]
        tail = style_tag[close_idx:]
        return head + _inline_css_urls(body, assets) + tail

    rewritten = re.sub(r"<style\b[^>]*>.*?</style>", _existing_style_sub, rewritten, flags=re.IGNORECASE | re.DOTALL)

    # 4. Prepend captured stylesheets at the top of <head> so they come before
    #    any existing <style> tags (whose rules take precedence).
    if css_blocks_to_prepend:
        combined = "\n".join(css_blocks_to_prepend)
        rewritten = _inject_into_head(rewritten, f"<style>{combined}</style>")

    rewritten = rewritten.replace("\u2212", "-")
    rewritten = _inject_static_tab_runtime(rewritten)
    return rewritten


def _inline_css_urls(css_text: str, assets: Dict[str, _Asset]) -> str:
    """Replace `url(/_nicegui/...)` inside CSS with data URIs."""

    def _repl(match: re.Match[str]) -> str:
        url_path = match.group("url")
        asset = assets.get(url_path)
        if asset is None:
            return match.group(0)
        mime = _classify_mime(url_path, asset.content_type)
        return f"url({_data_uri(asset.body, mime)})"

    return _CSS_URL_RE.sub(_repl, css_text)


def _data_uri(body: bytes, mime: str) -> str:
    return f"data:{mime};base64,{base64.b64encode(body).decode('ascii')}"


def _classify_mime(path: str, declared: str) -> str:
    declared = (declared or "").split(";")[0].strip().lower()
    if declared:
        return declared
    if path.endswith(".css"):
        return "text/css"
    if path.endswith(".svg"):
        return "image/svg+xml"
    if path.endswith(".ico"):
        return "image/x-icon"
    if path.endswith(".woff2"):
        return "font/woff2"
    if path.endswith(".woff"):
        return "font/woff"
    if path.endswith(".js") or path.endswith(".mjs"):
        return "application/javascript"
    return "application/octet-stream"


def _safe_decode(body: bytes) -> str:
    try:
        return body.decode("utf-8")
    except UnicodeDecodeError:  # pragma: no cover - defensive
        return body.decode("utf-8", errors="replace")


def _inject_into_head(html: str, fragment: str) -> str:
    head_match = re.search(r"<head\b[^>]*>", html, re.IGNORECASE)
    if head_match:
        idx = head_match.end()
        return html[:idx] + fragment + html[idx:]
    return fragment + html


def _ensure_meta_charset(html: str) -> str:
    if _META_CHARSET_RE.search(html):
        return html
    return _inject_into_head(html, '<meta charset="utf-8">')


def _inject_static_tab_runtime(html: str) -> str:
    if (
        "data-static-tab-buttons" not in html
        and "data-risk-vol-buttons" not in html
        and "data-risk-method-table" not in html
    ):
        return html

    style = """
<style>
[data-static-tab-panel][hidden] { display: none !important; }
.pm-static-tab-button.is-active { background: #0f172a !important; color: #fff !important; }
</style>
"""
    script = """
<script>
(function () {
  const groups = document.querySelectorAll('[data-static-tab-buttons]');
  groups.forEach((group) => {
    const name = group.getAttribute('data-static-tab-buttons');
    const buttons = Array.from(group.querySelectorAll('[data-tab-target]'));
    const panels = Array.from(document.querySelectorAll('[data-static-tab-panel="' + name + '"]'));
    const activate = (target) => {
      buttons.forEach((button) => {
        const active = button.getAttribute('data-tab-target') === target;
        button.classList.toggle('is-active', active);
      });
      panels.forEach((panel) => {
        const active = panel.getAttribute('data-tab-key') === target;
        if (active) {
          panel.removeAttribute('hidden');
        } else {
          panel.setAttribute('hidden', '');
        }
      });
    };
    buttons.forEach((button) => {
      button.addEventListener('click', () => activate(button.getAttribute('data-tab-target')));
    });
  });

  const applyVolColumns = (selectedVol) => {
    const wrappers = document.querySelectorAll('[data-risk-method-table]');
    wrappers.forEach((wrapper) => {
      const map = wrapper.getAttribute('data-vol-column-map') || '';
      const fixedColumns = Number(wrapper.getAttribute('data-fixed-columns') || '0');
      const tailColumns = Number(wrapper.getAttribute('data-tail-columns') || '0');
      const table = wrapper.querySelector('table');
      if (!table) return;
      const parts = map.split(';').filter(Boolean);
      const visible = new Set();
      parts.forEach((part) => {
        const tuple = part.split(':');
        if (tuple.length !== 2) return;
        const key = tuple[0];
        const index = Number(tuple[1]);
        if (Number.isNaN(index)) return;
        const baseKey = key.replace('_rc', '');
        if (baseKey === selectedVol) visible.add(index);
      });
      table.querySelectorAll('tr').forEach((row) => {
        const totalColumns = row.children.length;
        Array.from(row.children).forEach((cell, idx) => {
          const col = idx + 1;
          if (col <= fixedColumns) return;
          if (tailColumns > 0 && col > totalColumns - tailColumns) return;
          const isVisible = visible.has(col);
          cell.style.display = isVisible ? '' : 'none';
        });
      });
    });
  };

  const volGroups = document.querySelectorAll('[data-risk-vol-buttons]');
  volGroups.forEach((group) => {
    const buttons = Array.from(group.querySelectorAll('[data-risk-vol-target]'));
    const activate = (target) => {
      buttons.forEach((button) => {
        const active = button.getAttribute('data-risk-vol-target') === target;
        button.classList.toggle('is-active', active);
      });
      applyVolColumns(target);
    };
    buttons.forEach((button) => {
      button.addEventListener('click', () => activate(button.getAttribute('data-risk-vol-target')));
    });
    const initial = buttons.find((button) => button.classList.contains('is-active'));
    if (initial) activate(initial.getAttribute('data-risk-vol-target'));
  });
})();
</script>
"""
    with_style = _inject_into_head(html, style)
    body_close = re.search(r"</body>", with_style, re.IGNORECASE)
    if body_close:
        idx = body_close.start()
        return with_style[:idx] + script + with_style[idx:]
    return with_style + script


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
        overrides=request.overrides,
        launch_server=request.launch_server,
    )
    if resolved.launch_server:
        _start_dashboard(resolved.host, port, overrides=resolved.overrides)
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
