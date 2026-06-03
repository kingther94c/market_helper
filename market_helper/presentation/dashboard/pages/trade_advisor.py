"""Interactive Trade Advisor page (NiceGUI).

The first genuinely two-way dashboard surface: **bounded controls** (no
free-form input — there is no AI to interpret it) → run → ranked idea cards →
expandable payoff / Greeks / audit. Read-only: it shows labelled ideas and a
data-mode banner, never an order ticket.

Logic that can be unit-tested lives in module-level pure helpers
(:func:`build_context`, :func:`payoff_figure`, :func:`option_run_params`); the
``ui.*`` rendering is exercised by launching the page.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from nicegui import ui

from market_helper.application.trade_advisor import TradeAdvisorService
from market_helper.domain.option_advisor.structures import whatif_from_detail
from market_helper.trade_advisor.contracts import (
    LABEL_INFO,
    LABEL_MONITOR,
    LABEL_PROCEED,
    LABEL_REJECT,
    AdvisorContext,
    Suggestion,
)

# Bounded option sets — the universe is a fixed, validated list (no free text).
LIQUID_UNIVERSE = [
    "SPY", "QQQ", "IWM", "DIA", "XLK", "XLF", "XLE",
    "AAPL", "MSFT", "NVDA", "TSLA", "AMZN", "GOOGL", "META",
]
REGIME_OPTIONS = ["", "Goldilocks", "Reflation", "Stagflation", "Deflationary Slowdown"]
CONFIDENCE_OPTIONS = ["", "High", "Medium", "Low"]
_LABEL_COLOR = {
    LABEL_PROCEED: "positive",
    LABEL_MONITOR: "warning",
    LABEL_REJECT: "negative",
    LABEL_INFO: "info",
}

_REGISTERED = False
_SERVICE: TradeAdvisorService | None = None


@dataclass
class AdvisorInputs:
    symbols: list[str] = field(default_factory=lambda: ["SPY", "QQQ"])
    held: list[str] = field(default_factory=lambda: ["SPY"])
    aum: float = 250_000.0
    regime: str = ""
    confidence: str = ""
    crisis: bool = False
    fetch_realized: bool = False


# --------------------------------------------------------------------------- #
# Pure helpers (unit-tested)
# --------------------------------------------------------------------------- #


def build_context(inp: AdvisorInputs) -> AdvisorContext:
    """Map bounded inputs → AdvisorContext. Held = 100 sh each (∩ chosen universe)."""
    holdings = {s: 100.0 for s in inp.held if s in inp.symbols}
    watchlist = [s for s in inp.symbols if s not in holdings]
    return AdvisorContext(
        holdings=holdings,
        aum=float(inp.aum or 0.0),
        watchlist=watchlist,
        regime_label=inp.regime or "",
        regime_confidence=inp.confidence or "",
        crisis_flag=bool(inp.crisis),
    )


def option_run_params(inp: AdvisorInputs) -> dict:
    return {"option": {"fetch_realized": bool(inp.fetch_realized)}}


def _payoff_fig(curve, breakevens):
    import plotly.graph_objects as go

    xs = [pt[0] for pt in curve]
    ys = [pt[1] for pt in curve]
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=xs, y=ys, mode="lines", name="P&L @ expiry"))
    if xs:
        fig.add_hline(y=0.0, line_dash="dot", line_color="gray")
    for be in breakevens or []:
        fig.add_vline(x=be, line_dash="dash", line_color="orange")
    fig.update_layout(
        margin={"l": 40, "r": 10, "t": 10, "b": 36},
        height=240,
        showlegend=False,
        xaxis_title="underlying at expiry",
        yaxis_title="P&L ($)",
    )
    return fig


def payoff_figure(detail: dict):
    """Plotly P&L-at-expiry figure from a suggestion's payoff curve."""
    return _payoff_fig(detail.get("est_payoff_curve") or [], detail.get("est_breakevens") or [])


def _render_option_whatif(detail: dict) -> None:
    """Interactive payoff chart + bounded what-if controls (qty / IV / spot).

    Chart starts at the engine curve; moving a control re-prices via Black–Scholes
    (a *model* view, independent of live quotes) and updates in place.
    """
    chart = ui.plotly(payoff_figure(detail)).classes("w-full")
    spot0 = float(detail.get("spot") or 0.0)
    if spot0 <= 0:
        return  # no spot anchor → static chart only

    metrics = ui.label("").classes("text-caption")
    ui.label("What-if · bounded · Black–Scholes re-price (model, independent of live quotes)").classes("text-caption pm-muted")
    with ui.row().classes("items-center gap-4 w-full wrap"):
        qty = ui.number("Contracts", value=1, min=1, max=20, step=1).props("dense").style("width: 110px")
        with ui.column().classes("gap-0"):
            ui.label("IV shift (vol pts)").classes("text-caption")
            iv = ui.slider(min=-0.10, max=0.10, step=0.01, value=0.0).props("label-always").style("width: 150px")
        with ui.column().classes("gap-0"):
            ui.label("Spot").classes("text-caption")
            step = max(round(spot0 * 0.005, 2), 0.01)
            spot = ui.slider(
                min=round(spot0 * 0.85, 2), max=round(spot0 * 1.15, 2), step=step, value=round(spot0, 2)
            ).props("label-always").style("width: 170px")

    def recompute(_e=None) -> None:
        try:
            m = whatif_from_detail(
                detail,
                iv_shift=float(iv.value or 0.0),
                spot_override=float(spot.value or spot0),
                qty_scale=int(qty.value or 1),
            )
        except Exception as exc:  # noqa: BLE001 — surface, don't crash the card
            metrics.text = f"what-if error: {exc}"
            return
        g = m.get("net_greeks", {})
        metrics.text = (
            f"net {m['net_credit']:,.0f} · max loss {m['max_loss']:,.0f} · "
            f"max gain {m['max_gain']:,.0f} · BE {m['breakevens']} · "
            f"Δ {g.get('delta', 0.0):.1f}  vega {g.get('vega', 0.0):.1f}"
        )
        chart.figure = _payoff_fig(m["payoff_curve"], m["breakevens"])
        chart.update()

    for element in (qty, iv, spot):
        element.on_value_change(recompute)


# --------------------------------------------------------------------------- #
# Rendering
# --------------------------------------------------------------------------- #


def _render_card(s: Suggestion) -> None:
    with ui.card().classes("w-full pm-card"):
        with ui.row().classes("items-center justify-between w-full"):
            with ui.row().classes("items-center gap-2"):
                ui.badge(s.label, color=_LABEL_COLOR.get(s.label, "grey"))
                ui.label(f"{s.category} · {s.title}").classes("text-subtitle1")
            ui.label(f"score {s.score:.2f}").classes("text-caption")
        if s.headline_metrics:
            ui.label("   ".join(f"{k}: {v}" for k, v in s.headline_metrics.items())).classes("text-caption")
        if s.thesis:
            ui.label(s.thesis).classes("text-body2")
        if s.why_now:
            ui.label(f"Why now: {s.why_now}").classes("text-caption pm-muted")
        with ui.expansion("Detail · payoff · Greeks · audit").classes("w-full"):
            detail = s.detail or {}
            if s.body_kind == "option_payoff" and detail.get("est_payoff_curve"):
                _render_option_whatif(detail)
            for leg in detail.get("legs") or []:
                ui.label(
                    f"{str(leg.get('action', '')).upper()} {leg.get('right', '')}"
                    f"{leg.get('resolved_strike', '')} @ {leg.get('est_price')} "
                    f"({leg.get('resolved_dte')}DTE)"
                ).classes("text-caption")
            greeks = detail.get("net_greeks") or {}
            if greeks:
                ui.label("Greeks: " + "  ".join(f"{k} {float(v):.3f}" for k, v in greeks.items())).classes("text-caption")
            if s.sizing:
                ui.label(
                    f"Sizing: {s.sizing.basis} · max {s.sizing.max_units} · "
                    f"risk ${s.sizing.capital_at_risk_usd}"
                ).classes("text-caption")
            for entry in s.audit:
                mark = "✓" if entry.passed else "✗"
                ui.label(f"{mark} [{entry.severity}] {entry.name}: {entry.detail}").classes("text-caption pm-muted")
            if s.rationale:
                ui.label(s.rationale).classes("text-caption")


def _render_results(box, run_result) -> None:
    box.clear()
    with box:
        modes = sorted({r.data_mode for r in run_result.results.values() if r.data_mode})
        ui.label(f"data mode: {', '.join(modes) or 'n/a'} · ideas advisory only — not orders").classes("text-caption pm-muted")
        warnings = run_result.warnings()
        if warnings:
            with ui.card().classes("w-full pm-card"):
                ui.label("Warnings").classes("text-subtitle2")
                for w in warnings[:10]:
                    ui.label(f"• {w}").classes("text-caption")
        ordered = run_result.inbox() + [s for s in run_result.all_suggestions() if s.label == LABEL_REJECT]
        if not ordered:
            ui.label("No ideas generated for these inputs.").classes("text-caption")
            return
        for suggestion in ordered:
            _render_card(suggestion)


def register_trade_advisor_page(*, registry=None) -> None:
    """Register the /advisor interactive page (idempotent)."""
    global _REGISTERED, _SERVICE
    if registry is not None or _SERVICE is None:
        _SERVICE = TradeAdvisorService(registry=registry)
    if _REGISTERED:
        return
    _REGISTERED = True

    @ui.page("/advisor")
    def advisor_page() -> None:
        ui.label("Trade Advisor").classes("text-h5")
        ui.label("Read-only ideas, not orders. Explore within bounded controls.").classes("text-caption pm-muted")
        ui.link("← Portfolio dashboard", "/portfolio").classes("text-caption")

        with ui.row().classes("w-full gap-4 items-start no-wrap"):
            with ui.card().classes("p-4").style("min-width: 300px"):
                ui.label("Inputs").classes("text-subtitle1")
                sym_sel = ui.select(LIQUID_UNIVERSE, value=["SPY", "QQQ"], multiple=True, label="Universe").props("use-chips").classes("w-full")
                held_sel = ui.select(LIQUID_UNIVERSE, value=["SPY"], multiple=True, label="Treat as held (100 sh)").props("use-chips").classes("w-full")
                aum_in = ui.number("AUM (USD)", value=250_000, min=0, step=10_000, format="%.0f").classes("w-full")
                regime_sel = ui.select(REGIME_OPTIONS, value="", label="Regime").classes("w-full")
                conf_sel = ui.select(CONFIDENCE_OPTIONS, value="", label="Confidence").classes("w-full")
                crisis_sw = ui.switch("Crisis overlay", value=False)
                rv_sw = ui.switch("Fetch realized vol (slower)", value=False)
                run_btn = ui.button("Run advisor")
                status = ui.label("").classes("text-caption pm-muted")

            results_box = ui.column().classes("grow gap-3")

        async def run() -> None:
            run_btn.disable()
            status.text = "Running…"
            inp = AdvisorInputs(
                symbols=list(sym_sel.value or []),
                held=list(held_sel.value or []),
                aum=float(aum_in.value or 0),
                regime=regime_sel.value or "",
                confidence=conf_sel.value or "",
                crisis=bool(crisis_sw.value),
                fetch_realized=bool(rv_sw.value),
            )
            if not inp.symbols:
                status.text = "Pick at least one symbol."
                run_btn.enable()
                return
            context = build_context(inp)
            try:
                run_result = await asyncio.to_thread(
                    _SERVICE.run, context, advisors=["option"], params_by_advisor=option_run_params(inp)
                )
            except Exception as exc:  # noqa: BLE001 — surface, don't crash the page
                status.text = f"Failed: {type(exc).__name__}: {exc}"
                run_btn.enable()
                return
            _render_results(results_box, run_result)
            status.text = f"Done · {len(run_result.all_suggestions())} ideas"
            run_btn.enable()

        run_btn.on_click(run)
