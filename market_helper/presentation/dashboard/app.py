from __future__ import annotations

"""NiceGUI bootstrap for the portfolio-monitor dashboard."""

import argparse
import logging
import os
from typing import Sequence

from fastapi.responses import RedirectResponse
from nicegui import run as nicegui_run
from nicegui import app as nicegui_app
from nicegui import ui

from market_helper.application.portfolio_monitor import (
    PortfolioMonitorActionService,
    PortfolioMonitorQueryService,
)
from market_helper.presentation.dashboard.pages.portfolio import register_portfolio_page

_ROOT_REGISTERED = False
_PROCESS_POOL_PATCHED = False
DEFAULT_PORTFOLIO_ROUTE = "/portfolio"


def resolve_show_target(show: bool | str | None = None) -> bool | str:
    if show is not None:
        return show
    raw = os.environ.get("MARKET_HELPER_UI_SHOW", DEFAULT_PORTFOLIO_ROUTE).strip()
    if raw.lower() in {"0", "false", "off", "no"}:
        return False
    if raw in {"1", "true", "on", "yes"}:
        return DEFAULT_PORTFOLIO_ROUTE
    return raw or DEFAULT_PORTFOLIO_ROUTE


def create_app(
    *,
    query_service: PortfolioMonitorQueryService | None = None,
    action_service: PortfolioMonitorActionService | None = None,
):
    global _ROOT_REGISTERED

    register_portfolio_page(query_service=query_service, action_service=action_service)
    if not _ROOT_REGISTERED:
        @nicegui_app.get("/")
        async def root_redirect() -> RedirectResponse:
            return RedirectResponse("/portfolio")

        _ROOT_REGISTERED = True
    return nicegui_app


def patch_nicegui_process_pool_setup() -> None:
    global _PROCESS_POOL_PATCHED

    if _PROCESS_POOL_PATCHED:
        return

    original_setup = nicegui_run.setup

    def safe_setup() -> None:
        try:
            original_setup()
        except (PermissionError, OSError) as exc:
            logging.warning("Failed to initialize NiceGUI process pool; continuing without cpu_bound support: %s", exc)

    nicegui_run.setup = safe_setup
    _PROCESS_POOL_PATCHED = True


def run(
    *,
    host: str = "127.0.0.1",
    port: int = 8080,
    reload: bool = False,
    show: bool | str | None = None,
) -> None:
    create_app()
    patch_nicegui_process_pool_setup()
    ui.run(host=host, port=port, reload=reload, show=resolve_show_target(show), title="Portfolio Monitor")


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="market-helper-dashboard")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--reload", action="store_true")
    parser.add_argument("--show", default=None, help="Browser auto-open target; use /portfolio, true, or false.")
    parser.add_argument("--no-show", action="store_true", help="Disable browser auto-open.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    resolved_show: bool | str | None = False if args.no_show else args.show
    run(host=args.host, port=args.port, reload=bool(args.reload), show=resolved_show)
    return 0


if __name__ in {"__main__", "__mp_main__"}:
    raise SystemExit(main())


__all__ = [
    "DEFAULT_PORTFOLIO_ROUTE",
    "build_arg_parser",
    "create_app",
    "main",
    "patch_nicegui_process_pool_setup",
    "resolve_show_target",
    "run",
]
