"""Shared dashboard shell: chrome, top-level nav, and the landing page.

Thin by design (see ADR 0008). The shell:

- injects the shared dashboard styles **once** per page render;
- renders the brand + cross-surface navigation;
- provides a content container the page body renders into;
- owns the ``/`` landing page.

It holds **no** business state (no IBKR / report / advisor services), **no**
lifecycle hooks, and **no** surface registry. The two product lines
(``portfolio_monitor`` → ``/portfolio``, ``trade_advisor`` → ``/advisor``) are a
fixed pair, intentionally *not* a plugin point: research / backtest / screener
workflows live in a separate project and must not accrete here.
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from nicegui import ui

from market_helper.presentation.dashboard.components.common import add_dashboard_styles

PORTFOLIO_ROUTE = "/portfolio"
ADVISOR_ROUTE = "/advisor"

# The two parallel product lines: (nav key, label, route). A fixed tuple — not a
# registry. Adding a third top-level surface is a deliberate decision, not a
# drop-in (ADR 0008).
NAV_ITEMS: tuple[tuple[str, str, str], ...] = (
    ("portfolio", "Portfolio Monitor", PORTFOLIO_ROUTE),
    ("advisor", "Trade Advisor", ADVISOR_ROUTE),
)

_LANDING_REGISTERED = False

# Shell chrome reuses the design tokens injected by ``add_dashboard_styles``
# (palette / radius / shadow / --content-pad). The shell nav is intentionally
# **not** sticky: the portfolio page keeps its own sticky ``.pm-app-bar`` at
# ``top: 0`` (and the progress strip keys off ``--app-bar-height``), so a second
# sticky bar would fight it. Keeping the nav as a top strip preserves that
# behavior untouched.
_SHELL_STYLES = """
<style id='mh-shell-styles'>
  .mh-shell-nav {
    display: flex; align-items: center; gap: 16px;
    padding: 10px var(--content-pad);
    background: var(--surface);
    border-bottom: 1px solid var(--panel-border);
  }
  .mh-shell-brand { display: flex; align-items: center; gap: 8px; color: var(--ink); font-weight: 700; }
  .mh-shell-brand:hover { text-decoration: none; }
  .mh-shell-brand-dot { width: 9px; height: 9px; border-radius: 999px; background: var(--accent); box-shadow: 0 0 0 3px var(--accent-soft); }
  .mh-shell-brand-name { font-size: 14px; letter-spacing: 0.02em; }
  .mh-shell-spacer { flex: 1; }
  .mh-shell-links { display: flex; align-items: center; gap: 8px; }
  .mh-nav-item {
    font-size: 13px; font-weight: 600; color: var(--ink-2);
    background: var(--surface); border: 1px solid var(--panel-border);
    border-radius: 999px; padding: 5px 14px;
  }
  .mh-nav-item:hover { border-color: var(--accent); color: var(--accent); text-decoration: none; }
  .mh-nav-item--active, .mh-nav-item--active:hover { background: var(--ink); color: #fff; border-color: var(--ink); }
  .mh-shell-content { width: 100%; }

  /* Landing page */
  .mh-landing { max-width: 900px; margin: 0 auto; padding: 48px var(--content-pad) 64px; }
  .mh-landing-title { font-size: 30px; font-weight: 700; letter-spacing: -0.01em; color: var(--ink); }
  .mh-landing-sub { font-size: 15px; color: var(--muted-ink); margin-top: 4px; }
  .mh-landing-cards { display: grid; gap: 18px; margin-top: 32px; grid-template-columns: 1fr; }
  @media (min-width: 720px) { .mh-landing-cards { grid-template-columns: 1fr 1fr; } }
  .mh-landing-card {
    display: block; color: var(--ink);
    background: var(--surface); border: 1px solid var(--panel-border);
    border-radius: var(--r-3); box-shadow: var(--shadow-1);
    padding: 22px 24px; transition: border-color 140ms ease, box-shadow 140ms ease, transform 140ms ease;
  }
  .mh-landing-card:hover { border-color: var(--accent); box-shadow: 0 4px 16px rgba(15,23,42,.10); transform: translateY(-2px); text-decoration: none; }
  .mh-landing-card__title { font-size: 18px; font-weight: 700; }
  .mh-landing-card__blurb { font-size: 13.5px; color: var(--muted-ink); margin-top: 6px; line-height: 1.5; }
  .mh-landing-card__cta { font-size: 13px; font-weight: 600; color: var(--accent); margin-top: 14px; display: inline-block; }

  @media (max-width: 768px) {
    .mh-shell-nav { gap: 12px; padding: 8px var(--content-pad-mobile); flex-wrap: wrap; }
    .mh-landing { padding: 32px var(--content-pad-mobile) 48px; }
    .mh-landing-title { font-size: 25px; }
  }
</style>
"""


def render_shell_nav(active: str = "") -> None:
    """Render the brand + cross-surface nav with the active item highlighted."""
    with ui.element("header").classes("mh-shell-nav"):
        with ui.link(target="/").classes("mh-shell-brand"):
            ui.element("span").classes("mh-shell-brand-dot")
            ui.label("Market Helper").classes("mh-shell-brand-name")
        ui.element("div").classes("mh-shell-spacer")
        with ui.element("nav").classes("mh-shell-links"):
            for key, label, route in NAV_ITEMS:
                css = "mh-nav-item mh-nav-item--active" if key == active else "mh-nav-item"
                ui.link(label, route).classes(css)


@contextmanager
def app_shell(active: str = "") -> Iterator[None]:
    """Wrap a page body in the shared shell.

    Injects styles once, renders the nav (``active`` ∈ {``portfolio``,
    ``advisor``, ``home``}), and opens a content container the caller renders
    into::

        with app_shell(active="portfolio"):
            ...page body...
    """
    add_dashboard_styles()
    ui.add_head_html(_SHELL_STYLES)
    render_shell_nav(active)
    with ui.element("div").classes("mh-shell-content"):
        yield


def _landing_card(title: str, route: str, blurb: str) -> None:
    with ui.link(target=route).classes("mh-landing-card"):
        ui.label(title).classes("mh-landing-card__title")
        ui.label(blurb).classes("mh-landing-card__blurb")
        ui.label("Open →").classes("mh-landing-card__cta")


def render_landing() -> None:
    """Lightweight, resilient landing page — two cards, no live data loads."""
    with app_shell(active="home"):
        with ui.element("div").classes("mh-landing"):
            ui.label("Market Helper").classes("mh-landing-title")
            ui.label("Read-only portfolio monitoring and advisory.").classes("mh-landing-sub")
            with ui.element("div").classes("mh-landing-cards"):
                _landing_card(
                    "Portfolio Monitor",
                    PORTFOLIO_ROUTE,
                    "Positions, performance, risk and regime — embedded HTML reports.",
                )
                _landing_card(
                    "Trade Advisor",
                    ADVISOR_ROUTE,
                    "Bounded-control, read-only trade ideas with live what-if and optional AI+.",
                )


def register_landing_page() -> None:
    """Register the ``/`` landing page (idempotent)."""
    global _LANDING_REGISTERED
    if _LANDING_REGISTERED:
        return
    _LANDING_REGISTERED = True

    @ui.page("/")
    def landing_page() -> None:
        render_landing()


__all__ = [
    "ADVISOR_ROUTE",
    "NAV_ITEMS",
    "PORTFOLIO_ROUTE",
    "app_shell",
    "register_landing_page",
    "render_landing",
    "render_shell_nav",
]
