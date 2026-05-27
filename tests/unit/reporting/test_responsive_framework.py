"""Contract tests for the centralized responsive framework.

The responsive framework lives in :mod:`market_helper.reporting._design_tokens`
and is consumed by every HTML surface in `market_helper` (combined report,
regime/perf/risk sections, and the live dashboard chrome). These tests pin the
*shape* of that contract so the framework can be safely extended without
silently dropping the pieces other modules depend on.

If you intentionally rename a token / class / breakpoint, update both the
framework and this test in the same change.
"""
from __future__ import annotations

import re

import pytest

from market_helper.presentation.dashboard.components.common import add_dashboard_styles
from market_helper.reporting import _design_tokens, portfolio_html, report_document
from market_helper.reporting._design_tokens import (
    design_tokens_css,
    design_tokens_style_block,
)


# ---- Layout custom properties (the "magic numbers" sticky stacks consume) ----


REQUIRED_LAYOUT_VARS: tuple[tuple[str, str], ...] = (
    ("--shell-max", "1540px"),
    ("--content-pad", "24px"),
    ("--content-pad-mobile", "12px"),
    ("--app-bar-height", "49px"),
    ("--app-bar-height-mobile", "108px"),
)


@pytest.mark.parametrize("var_name,expected_value", REQUIRED_LAYOUT_VARS)
def test_layout_vars_declared_with_expected_default(var_name: str, expected_value: str) -> None:
    css = design_tokens_css()
    pattern = re.escape(var_name) + r"\s*:\s*" + re.escape(expected_value) + r"\s*;"
    assert re.search(pattern, css), f"missing or changed default for {var_name}"


# ---- Breakpoint values + literal/var lock-step ------------------------------


REQUIRED_BREAKPOINT_VARS: tuple[tuple[str, str], ...] = (
    ("--bp-phone", "480px"),
    ("--bp-mobile", "768px"),
    ("--bp-tablet", "1024px"),
)


@pytest.mark.parametrize("var_name,expected_value", REQUIRED_BREAKPOINT_VARS)
def test_breakpoint_var_declared(var_name: str, expected_value: str) -> None:
    css = design_tokens_css()
    pattern = re.escape(var_name) + r"\s*:\s*" + re.escape(expected_value) + r"\s*;"
    assert re.search(pattern, css), f"breakpoint var {var_name} not declared as {expected_value}"


def test_media_queries_use_declared_breakpoints() -> None:
    """`@media (max-width: ...)` must match a declared `--bp-*` value.

    CSS `@media` cannot interpolate vars, so the literal pixel value has to be
    repeated. This test catches the case where someone bumps the var but forgets
    the @media rule (or vice versa) — they would silently desync.

    The framework CSS itself must use only the declared `--bp-*` values; the
    `tests/unit/reporting/test_framework_breakpoints_used_section_wide` check
    asserts the report sections also align (no 720 / 760 / 800 stragglers).
    """
    css = design_tokens_css()
    declared_widths = {value for _, value in REQUIRED_BREAKPOINT_VARS}
    found = set(re.findall(r"@media\s*\(\s*max-width:\s*(\d+px)\s*\)", css))
    drift = found - declared_widths
    assert not drift, (
        f"framework @media rules use undocumented breakpoints {sorted(drift)}; "
        f"either add to `--bp-*` or remove."
    )


def test_framework_breakpoints_used_section_wide() -> None:
    """Every per-section CSS in `market_helper.reporting` must use the framework
    breakpoint (768) rather than its own legacy value (720 / 760). Promoting
    everything to one breakpoint means the perf / risk / regime sections flip
    to mobile in lock-step with the report shell instead of staggering between
    720 and 768. Calibration (workflows/) is out-of-scope.
    """
    import importlib
    import inspect

    targets = (
        "market_helper.reporting.performance_html",
        "market_helper.reporting.risk_html",
        "market_helper.reporting.regime_html",
        "market_helper.reporting.portfolio_html",
        "market_helper.reporting.report_document",
    )
    declared_widths = {value for _, value in REQUIRED_BREAKPOINT_VARS}
    for module_name in targets:
        module = importlib.import_module(module_name)
        source = inspect.getsource(module)
        widths = set(re.findall(r"@media\s*\(\s*max-width:\s*(\d+px)\s*\)", source))
        drift = widths - declared_widths
        assert not drift, (
            f"{module_name} uses non-framework breakpoint(s) {sorted(drift)} — "
            f"align to {sorted(declared_widths)} (`--bp-*` in _design_tokens.py)."
        )


# ---- Required utility classes other HTML can opt into -----------------------


REQUIRED_UTILITY_CLASSES: tuple[str, ...] = (
    ".responsive-cluster",
    ".scroll-x-on-narrow",
    ".responsive-grid-2",
    ".responsive-grid-3",
    ".responsive-grid-4",
    ".responsive-hide-sm",
    ".responsive-stack-sm",
)


@pytest.mark.parametrize("utility_class", REQUIRED_UTILITY_CLASSES)
def test_utility_class_exposed(utility_class: str) -> None:
    css = design_tokens_css()
    assert utility_class in css, (
        f"utility class {utility_class} dropped — downstream HTML may rely on it"
    )


def test_responsive_grid_collapses_to_one_column_on_mobile() -> None:
    css = design_tokens_css()
    # Look for the @media block that collapses `.responsive-grid-2` to a
    # single column. Capture the entire 768px block so we can search within it.
    match = re.search(
        r"@media\s*\(\s*max-width:\s*768px\s*\)\s*\{(.*?)\n\}",
        css,
        flags=re.DOTALL,
    )
    assert match, "expected a @media (max-width: 768px) block in the framework CSS"
    mobile_block = match.group(1)
    assert ".responsive-grid-2 { grid-template-columns: 1fr; }" in mobile_block, (
        "`.responsive-grid-2` should collapse to a single column on mobile"
    )


# ---- Touch-target floor for coarse pointers ---------------------------------


def test_pointer_coarse_floor_present() -> None:
    css = design_tokens_css()
    assert "@media (pointer: coarse)" in css, (
        "Touch-target floor for phones/tablets is missing — see "
        "`_RESPONSIVE_FRAMEWORK_CSS` in _design_tokens.py"
    )
    # Confirm the floor binds to buttons (not just decorative selectors).
    assert re.search(
        r"@media\s*\(pointer:\s*coarse\)\s*\{[^}]*?\bbutton\b[^}]*?min-height:\s*40px",
        css,
        flags=re.DOTALL,
    ), "coarse-pointer block should set min-height on buttons"


# ---- Sticky-stack must consume `var(--app-bar-height)` ----------------------


def test_dashboard_progress_strip_uses_app_bar_height_var() -> None:
    style_block = _capture_dashboard_head_html()
    assert "top: var(--app-bar-height)" in style_block, (
        "pm-progress-strip must use the shared `--app-bar-height` var rather "
        "than a magic 49px so the sticky stack stays in sync."
    )
    # And the magic number should be gone from the dashboard chrome.
    assert "top: 49px" not in style_block, (
        "Magic `top: 49px` reintroduced in dashboard chrome — replace with var."
    )


def test_regime_ribbon_uses_app_bar_height_var() -> None:
    ribbon_css = portfolio_html._REGIME_RIBBON_STYLES
    assert "top: var(--app-bar-height)" in ribbon_css, (
        "regime-ribbon must consume `--app-bar-height` instead of `top: 49px`."
    )
    assert "top: 49px" not in ribbon_css, "magic 49px reintroduced in regime ribbon"


def test_report_section_scroll_margin_tracks_app_bar_height() -> None:
    css = report_document.render_report_document.__globals__["design_tokens_css"]()
    # The report_document html template embeds `.report-section { scroll-margin-top: ... }`
    # using the var — test that the template literal still contains the var form.
    from market_helper.reporting import report_document as rd_module
    import inspect

    source = inspect.getsource(rd_module)
    assert "scroll-margin-top: calc(var(--app-bar-height)" in source, (
        ".report-section scroll-margin-top must be derived from --app-bar-height"
    )
    assert "scroll-margin-top: 64px" not in source, (
        "Magic `scroll-margin-top: 64px` reintroduced — should use the var."
    )
    # Silence "unused" complaint on `css`.
    assert css


# ---- The dashboard injects the framework into NiceGUI head ------------------


def _capture_dashboard_head_html() -> str:
    """Run `add_dashboard_styles` against a fake `ui` shim, return joined CSS."""
    captured: list[str] = []

    class _FakeUi:
        @staticmethod
        def add_head_html(html: str) -> None:
            captured.append(html)

    import market_helper.presentation.dashboard.components.common as common

    real_ui = common.ui
    common.ui = _FakeUi  # type: ignore[assignment]
    try:
        add_dashboard_styles()
    finally:
        common.ui = real_ui
    return "\n".join(captured)


def test_dashboard_injects_design_tokens_and_pm_overrides() -> None:
    head = _capture_dashboard_head_html()
    # 1. The shared framework arrives via the token style block.
    assert design_tokens_style_block() in head, (
        "add_dashboard_styles must inject design_tokens_style_block so the "
        "dashboard chrome inherits the shared responsive framework."
    )
    # 2. The dashboard-specific mobile overrides also arrive.
    assert "@media (max-width: 768px)" in head, (
        "dashboard chrome must declare its own mobile overrides "
        "(pm-app-bar, pm-status-card, pm-drawer__body, pm-history__row, ...)"
    )
    # 3. Desktop `.pm-status-card` keeps the 180px floor so paired toolbar cards
    #    don't sprawl. Mobile collapse happens inside the @media block — we
    #    confirm that below in `test_pm_status_card_collapses_on_mobile`.
    assert "min-width: 180px" in head, (
        ".pm-status-card desktop floor was removed — paired cards will sprawl."
    )


def test_pm_status_card_collapses_on_mobile() -> None:
    """Inside the dashboard mobile @media block, `.pm-status-card` must release
    the desktop 180px floor (either via `min-width: 0` or `flex-basis: 100%`) so
    the card stacks full-width on phones instead of pushing horizontal overflow.

    The head contains *two* `@media (max-width: 768px)` blocks — one from the
    shared framework, one from the dashboard chrome itself. We anchor on the
    dashboard block by its banner comment.
    """
    head = _capture_dashboard_head_html()
    anchor = head.find("Dashboard chrome — mobile")
    assert anchor != -1, (
        "dashboard chrome banner comment is missing; the mobile block lost its "
        "label. Re-add `/* === Dashboard chrome — mobile (≤ 768px) === ... */` "
        "above the `@media` block in `add_dashboard_styles`."
    )
    dashboard_mobile_tail = head[anchor:]
    # Strict selector: `.pm-status-card` directly followed by whitespace + `{`.
    # The `[^{]*` form is too loose — it spans neighbouring selectors and matches
    # the body of whichever rule comes next.
    card_rule = re.search(
        r"\.pm-status-card\s*\{([^}]*)\}",
        dashboard_mobile_tail,
        flags=re.DOTALL,
    )
    assert card_rule, (
        "no `.pm-status-card { ... }` override in the dashboard chrome mobile "
        "block — the desktop 180px floor will pin paired cards on phones."
    )
    body = card_rule.group(1)
    assert "min-width: 0" in body or "flex-basis: 100%" in body, (
        f".pm-status-card mobile rule must release the desktop floor "
        f"(got: {body.strip()!r})"
    )


def test_dashboard_drawer_collapses_grids_on_mobile() -> None:
    """The operate drawer holds 2-col grids for action / artifact / regime forms.

    On phones those grids must collapse to one column — there is no horizontal
    room for paired inputs. Regex over nested `{...}` blocks is fragile, so we
    instead require that a `.pm-drawer__body ... grid-template-columns: 1fr`
    rule appears *after* the start of the dashboard's `@media (max-width: 768px)`
    block.
    """
    head = _capture_dashboard_head_html()
    media_start = head.find("@media (max-width: 768px)")
    assert media_start != -1, "dashboard chrome is missing its mobile @media block"
    mobile_tail = head[media_start:]
    # Must collapse the drawer's grids inside the mobile block.
    drawer_rule = re.search(
        r"\.pm-drawer__body[^{]*\{[^}]*grid-template-columns:\s*1fr[^}]*\}",
        mobile_tail,
        flags=re.DOTALL,
    )
    assert drawer_rule, (
        "operate drawer body grids should collapse to 1 column on mobile so "
        "action / artifact / regime forms stack vertically on phones."
    )


# ---- Primitive auto-adapts — `.kpi-strip` overrides inline grid -------------


def test_kpi_strip_overrides_inline_grid_on_mobile() -> None:
    """portfolio_html / report_document emit `style="grid-template-columns: repeat(N,...)"`
    inline on `.kpi-strip`. Without `!important`, the mobile rule loses to the
    inline style and the strip overflows on phones. This test pins that the
    `!important` wins back.
    """
    css = design_tokens_css()
    assert re.search(
        r"\.kpi-strip\s*\{[^}]*?grid-template-columns:[^;}]*?!important",
        css,
    ), (
        ".kpi-strip mobile override must use `!important` to defeat the inline "
        "`style=\"grid-template-columns: repeat(N, ...)\"` emitted by portfolio_html."
    )


# ---- Sanity: design_tokens_css concatenates all blocks ----------------------


def test_design_tokens_css_contains_all_blocks() -> None:
    css = design_tokens_css()
    # Cheap fingerprint per concern so a regression that drops one shows up here.
    # All four concerns now live in three blocks: _TOKENS_CSS (vars),
    # _COMPONENT_PRIMITIVES_CSS (component CSS), _RESPONSIVE_FRAMEWORK_CSS
    # (utility classes + touch-target + mobile primitive overrides + table
    # mobile rules — formerly _MOBILE_OVERRIDES_CSS, folded in to keep all
    # mobile behaviour under one banner).
    assert ":root {" in css, "missing _TOKENS_CSS block"
    assert ".report-table {" in css, "missing _COMPONENT_PRIMITIVES_CSS block"
    assert ".responsive-cluster" in css, "missing _RESPONSIVE_FRAMEWORK_CSS block"
    assert ".heat-table th" in css, (
        "table mobile rules missing from _RESPONSIVE_FRAMEWORK_CSS — they "
        "used to live in a separate `_MOBILE_OVERRIDES_CSS` block but were "
        "folded in so there is one canonical mobile entry point."
    )


def test_no_orphan_mobile_block_in_design_tokens() -> None:
    """The framework should expose exactly one mobile overrides surface.

    `_MOBILE_OVERRIDES_CSS` was the legacy name for the table-mobile block;
    it was folded into `_RESPONSIVE_FRAMEWORK_CSS` so consumers don't have to
    pick between two adjacent mobile concerns. Re-introducing it (or any
    similarly-named sibling) drifts the doctrine — fail loudly if it returns.
    """
    assert not hasattr(_design_tokens, "_MOBILE_OVERRIDES_CSS"), (
        "`_MOBILE_OVERRIDES_CSS` re-introduced; merge it into "
        "`_RESPONSIVE_FRAMEWORK_CSS` so the framework keeps one mobile block."
    )


# ---- Shell-width primitives use the var, not a literal ----------------------


SHELL_WIDTH_SOURCES: tuple[tuple[str, str], ...] = (
    ("report_document", "report_document.py"),
    ("portfolio_html", "portfolio_html.py"),
)


@pytest.mark.parametrize("module_name,_filename", SHELL_WIDTH_SOURCES)
def test_shell_width_uses_var(module_name: str, _filename: str) -> None:
    import importlib
    import inspect

    module = importlib.import_module(f"market_helper.reporting.{module_name}")
    source = inspect.getsource(module)
    # Any string that contains `max-width: 1540px` directly is a regression —
    # the framework defines `--shell-max: 1540px` and consumers should reference it.
    assert "max-width: 1540px" not in source, (
        f"{module_name} hard-codes `max-width: 1540px` — switch to var(--shell-max)"
    )
    # Equally, the desktop gutter `padding: ... 24px` (where 24 is the literal
    # content padding) should be expressed as `var(--content-pad)` for the shell
    # primitives. We can't safely grep every 24px (charts/spacing use it too),
    # but for the explicit `padding: 16px 24px ...` shell pattern we can.
    assert "padding: 16px 24px " not in source, (
        f"{module_name} uses literal shell padding `16px 24px ...` — "
        f"replace with `16px var(--content-pad) ...` so mobile gutter follows."
    )


# ---- Iframe-embedded report overrides app-bar height vars locally ----------


def test_embedded_overrides_redeclare_app_bar_height() -> None:
    """The dashboard's `_inject_embedded_overrides` hides the report's brand +
    meta inside the iframe, so the visible `.app-bar` collapses to just the
    section-nav. The sticky `.regime-ribbon` reads its `top` from
    `--app-bar-height`, so the iframe context must override that var locally —
    otherwise the ribbon leaves a 50+ px gap on mobile when the outer-shell
    value (108px mobile) is much taller than the actual iframe app-bar (~48px).

    Values must also stay within the realistic range for a section-nav-only
    `.app-bar` so an accidental bump (e.g. someone copying the shell defaults
    back in) trips this test.
    """
    from market_helper.presentation.dashboard.pages import portfolio as portfolio_page

    overrides = portfolio_page._EMBEDDED_REPORT_OVERRIDES
    assert ":root" in overrides, (
        "_EMBEDDED_REPORT_OVERRIDES must re-declare `:root` vars so the iframe's "
        "regime-ribbon sticky offset matches the visible (collapsed) app-bar."
    )
    desktop = re.search(
        r"--app-bar-height\s*:\s*(\d+)px", overrides
    )
    mobile = re.search(
        r"--app-bar-height-mobile\s*:\s*(\d+)px", overrides
    )
    assert desktop and mobile, (
        "iframe must redeclare both --app-bar-height and --app-bar-height-mobile."
    )
    desktop_px = int(desktop.group(1))
    mobile_px = int(mobile.group(1))
    # Iframe app-bar = section-nav only. Pill button row is ~28-32px content +
    # 4-8px padding ≈ 36-48px. Anything ≥60 means the override wasn't really
    # an override — it's the outer-shell value pasted in by mistake.
    assert desktop_px <= 60, (
        f"iframe --app-bar-height = {desktop_px}px is too tall — the iframe "
        f"only shows the section-nav, the value should be ≤60px."
    )
    assert mobile_px <= 60, (
        f"iframe --app-bar-height-mobile = {mobile_px}px is too tall — the "
        f"iframe section-nav with touch padding is ≤60px on phones."
    )


# ---- Sticky `top` invariant: 0 or app-bar var ------------------------------


def test_sticky_top_uses_anchor_zero_or_app_bar_var() -> None:
    """Every `position: sticky` rule in the reporting + dashboard CSS must use
    either `top: 0` (the element is itself a sticky anchor — app-bar, table
    header, drawer header) or `top: var(--app-bar-height...)` (the element pins
    underneath an anchor). A literal `top: 49px` or similar magic number is a
    regression: when the anchor resizes the offset drifts and the pinned
    element overlaps the anchor.
    """
    import importlib
    import inspect

    targets = (
        "market_helper.reporting._design_tokens",
        "market_helper.reporting.report_document",
        "market_helper.reporting.portfolio_html",
        "market_helper.reporting.performance_html",
        "market_helper.reporting.risk_html",
        "market_helper.reporting.regime_html",
        "market_helper.presentation.dashboard.components.common",
    )
    # Capture every `position: sticky` rule's full body, then check the `top`
    # inside it. Cross-rule layout (sticky in one rule, top in another) is rare
    # enough we can require co-location.
    sticky_block_re = re.compile(
        r"\{[^{}]*?position:\s*sticky[^{}]*?\}", flags=re.DOTALL
    )
    top_re = re.compile(r"top:\s*([^;\n]+?);")
    for module_name in targets:
        module = importlib.import_module(module_name)
        source = inspect.getsource(module)
        for block in sticky_block_re.findall(source):
            top_match = top_re.search(block)
            if top_match is None:
                continue  # sticky without `top` is `top: auto`, harmless
            value = top_match.group(1).strip()
            if value == "0":
                continue
            if value.startswith("var(--app-bar-height"):
                continue
            raise AssertionError(
                f"{module_name}: sticky rule uses non-standard `top: {value}`. "
                f"Stack anchors must use `top: 0`; pinned elements must use "
                f"`top: var(--app-bar-height)` / `var(--app-bar-height-mobile)`. "
                f"Block: {block!r}"
            )


# ---- Iframe override wins the CSS cascade ----------------------------------


def test_iframe_override_appears_after_framework_default() -> None:
    """CSS custom properties with equal specificity follow source order — the
    iframe-specific `:root { --app-bar-height-mobile: 56px }` only wins if it
    is injected *after* the framework's `:root { --app-bar-height-mobile: 108px }`.
    `_inject_embedded_overrides` puts the override block immediately before
    `</head>`; this test verifies the cascade actually flips in the rendered
    srcdoc, not just in isolation.
    """
    from market_helper.presentation.dashboard.pages.portfolio import (
        _inject_embedded_overrides,
    )
    from market_helper.reporting.report_document import (
        ReportDocument,
        ReportSection,
        render_report_document,
    )

    bare = render_report_document(ReportDocument(
        title="Cascade probe",
        as_of="2026-05-27T00:00:00+00:00",
        sections=(ReportSection(key="overview", title="Overview", body_html="<p>x</p>"),),
    ))
    iframe = _inject_embedded_overrides(bare)
    default_pos = iframe.find("--app-bar-height-mobile: 108px")
    override_pos = iframe.find("--app-bar-height-mobile: 56px")
    assert default_pos != -1, "framework default --app-bar-height-mobile missing from iframe srcdoc"
    assert override_pos != -1, "iframe override --app-bar-height-mobile missing from srcdoc"
    assert override_pos > default_pos, (
        f"iframe override (pos {override_pos}) must follow the framework "
        f"default (pos {default_pos}) so the cascade flips. If the override "
        f"is injected too early, `.regime-ribbon`'s sticky `top` will use the "
        f"108px default and overlap the section-nav on phones."
    )


# ---- Standalone mobile `.app-bar__row` uses compact two-row layout ----------


def test_standalone_mobile_app_bar_uses_grid_areas() -> None:
    """The standalone report shell's mobile `.app-bar__row` must use the compact
    `grid-template-areas` layout (brand + meta on row 1, section-nav on row 2).

    A naive `grid-template-columns: 1fr` would stack brand / nav / meta into
    three separate rows, lifting the app-bar to ~140px on phones — at that
    point `--app-bar-height-mobile (108px)` is too short and the sticky
    `.regime-ribbon` overlaps the bottom of the app-bar.
    """
    css = design_tokens_css()
    # Find the 768 block opening, scan its tail for the .app-bar__row rule.
    media_start = css.find("@media (max-width: 768px)")
    assert media_start != -1, "framework missing @media (max-width: 768px) block"
    tail = css[media_start:]
    rule = re.search(
        r"\.app-bar__row\s*\{([^}]*)\}",
        tail,
        flags=re.DOTALL,
    )
    assert rule, ".app-bar__row mobile override missing from the framework block"
    body = rule.group(1)
    assert "grid-template-areas" in body, (
        ".app-bar__row mobile must use `grid-template-areas` to keep "
        "brand+meta on one row and section-nav on another (single-column "
        "stacking lifts the bar to ~140px and breaks the sticky ribbon offset)."
    )
    # Confirm the two areas we depend on are declared.
    assert '"brand meta"' in body, "missing `brand meta` grid area row"
    assert '"nav   nav"' in body or '"nav nav"' in body, (
        "section-nav should occupy a full row of its own on mobile"
    )


# ---- Mobile breakpoint is generous enough for two-row wrap ------------------


def test_app_bar_height_mobile_leaves_room_for_wrap() -> None:
    """The dashboard chrome's `.pm-app-bar` can wrap to two rows on 360–390px
    viewports (brand + actions don't always fit beside each other after the
    touch-target floor lifts buttons to 40px). The mobile var must leave room
    for that worst case so the sticky progress strip / regime ribbon don't
    overlap the app-bar's bottom edge.
    """
    css = design_tokens_css()
    match = re.search(r"--app-bar-height-mobile\s*:\s*(\d+)px", css)
    assert match, "`--app-bar-height-mobile` missing"
    value_px = int(match.group(1))
    # Worst case: 2 rows × (40px touch button + ~8px wrap gap) + ~16px padding.
    assert value_px >= 100, (
        f"--app-bar-height-mobile = {value_px}px is too small for a wrapped "
        f"app-bar on 360px viewports — bump to >= 100px."
    )


# Keep this last so it shows up at the bottom of failure output as a hint when
# anything above breaks: read the module docstring before fixing.
def test_module_docstring_pins_responsive_contract() -> None:
    doc = _design_tokens.__doc__ or ""
    for needle in ("Breakpoints", "--app-bar-height", "Touch-target", "Utility classes"):
        assert needle in doc, f"_design_tokens docstring should mention {needle!r}"
