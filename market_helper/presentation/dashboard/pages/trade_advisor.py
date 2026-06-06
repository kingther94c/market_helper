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
from datetime import datetime

from nicegui import ui

from market_helper.application.trade_advisor import (
    TradeAdvisorService,
    context_from_positions_csv,
    current_regime_seed,
    default_decision_journal,
    write_decision_snapshot,
)
from market_helper.domain.option_advisor.structures import whatif_from_detail
from market_helper.trade_advisor.ai import (
    GatewayAuthMissing,
    GatewayConfig,
    GatewayError,
    request_ai_advisory,
    resolve_gateway_token,
)
from market_helper.trade_advisor.contracts import (
    LABEL_INFO,
    LABEL_MONITOR,
    LABEL_ORDER,
    LABEL_PROCEED,
    LABEL_REJECT,
    AdvisorContext,
    Suggestion,
)
from market_helper.trade_advisor.journal import DecisionJournal, decision_from_suggestion

# Bounded option sets — the universe is a fixed, validated list (no free text).
LIQUID_UNIVERSE = [
    "SPY", "QQQ", "IWM", "DIA", "XLK", "XLF", "XLE",
    "AAPL", "MSFT", "NVDA", "TSLA", "AMZN", "GOOGL", "META",
]
REGIME_OPTIONS = ["", "Goldilocks", "Reflation", "Stagflation", "Deflationary Slowdown"]
CONFIDENCE_OPTIONS = ["", "High", "Medium", "Low"]
# AI+ tab: bounded model choices (the OpenClaw gateway routes these ids to personas).
AI_MODELS = ["openclaw/trade-advisor", "openclaw/trade-advisor-panel"]
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
    check_earnings: bool = False


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
    return {"option": {"fetch_realized": bool(inp.fetch_realized), "fetch_events": bool(inp.check_earnings)}}


def build_run_context(inp: AdvisorInputs, *, use_portfolio: bool) -> tuple[AdvisorContext, str]:
    """Resolve the advisor context (+ a short book note) from bounded inputs.

    ``use_portfolio`` seeds held stock/options + funded AUM from the live
    positions CSV (degrading to a watchlist-only scan when none is found);
    otherwise the manual Universe / Held / AUM controls are used. Shared by the
    rule-based and AI+ tabs so both see the same book.
    """
    if use_portfolio:
        from dataclasses import replace as _replace

        context = context_from_positions_csv(
            watchlist=inp.symbols, regime_label=inp.regime,
            regime_confidence=inp.confidence, crisis_flag=inp.crisis,
        )
        if context.aum is None:
            context = _replace(context, aum=inp.aum)
        book_note = (
            f" · book: {len(context.holdings)} stk / {len(context.held_options)} opt"
            if (context.holdings or context.held_options)
            else " · no live positions found (watchlist only)"
        )
        return context, book_note
    return build_context(inp), ""


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


# --- Body-specific table / fact builders (pure, unit-tested) --------------- #


def _num(x, spec: str = "g") -> str:
    """Format a number, or ``—`` when it's missing. Integer specs ('d') round."""
    if x is None or x == "":
        return "—"
    try:
        val = float(x)
    except (TypeError, ValueError):
        return str(x)
    if spec.endswith("d"):
        return format(int(round(val)), spec)
    return format(val, spec)


def _pct(x) -> str:
    return "—" if x is None else f"{float(x) * 100:.2f}"


def option_legs_lines(detail: dict) -> list[str]:
    """One readable line per resolved option leg."""
    out: list[str] = []
    for leg in detail.get("legs") or []:
        out.append(
            f"{str(leg.get('action', '')).upper()} {leg.get('right', '')}"
            f"{leg.get('resolved_strike', '')} @ {leg.get('est_price')} "
            f"({leg.get('resolved_dte')}DTE)"
        )
    return out


def fx_alloc_table(detail: dict) -> tuple[list[str], list[list[str]]]:
    """Headers + formatted rows for an FX hedge allocation (``detail['fx_legs']``)."""
    headers = ["Ccy", "Instrument", "Beta", "Contracts", "Notional $", "Carry bps", "ON %", "Expiry"]
    rows = [
        [
            str(l.get("currency", "")),
            str(l.get("instrument", "")),
            _num(l.get("beta"), "+.3f"),
            _num(l.get("target_contracts"), "+d"),
            _num(l.get("target_notional_usd"), ",.0f"),
            _num(l.get("carry_bps"), "+.0f"),
            _pct(l.get("on_rate")),
            str(l.get("expiry", "")),
        ]
        for l in (detail.get("fx_legs") or [])
    ]
    return headers, rows


def fx_carry_table(detail: dict) -> tuple[list[str], list[list[str]]]:
    """Headers + formatted rows for the FX carry ranking (``detail['ranking']``)."""
    headers = ["Ccy", "Carry bps", "ON %"]
    rows = [
        [str(r.get("currency", "")), _num(r.get("carry_bps"), "+.0f"), _pct(r.get("on_rate"))]
        for r in (detail.get("ranking") or [])
    ]
    return headers, rows


def roll_facts(detail: dict) -> list[tuple[str, str]]:
    """Label/value pairs describing a held option position for the Roll body."""
    qty = detail.get("qty")
    side = "short" if (qty is not None and qty < 0) else "long"
    itm = detail.get("itm")
    moneyness = "—" if itm is None else ("ITM" if itm else "OTM")
    dte = detail.get("dte")
    return [
        ("Underlying", str(detail.get("underlying", "—"))),
        ("Contract", f"{side} {detail.get('right', '')}{_num(detail.get('strike'))} {detail.get('expiry', '—')}"),
        ("Quantity", _num(qty)),
        ("DTE", "—" if dte is None else f"{dte}d"),
        ("Moneyness", moneyness),
        ("Underlying px", _num(detail.get("underlying_price"))),
    ]


def _render_option_whatif(detail: dict) -> None:
    """Interactive payoff chart + bounded what-if controls (qty / IV / spot).

    Chart starts at the engine curve; moving a control re-prices via Black–Scholes
    and updates in place. When the idea carries a chain skew (``iv_skew``), the
    *Link IV to chain skew* toggle (default on) makes spot moves track the chain's
    observed skew (sticky-moneyness) rather than holding IV flat.
    """
    chart = ui.plotly(payoff_figure(detail)).classes("w-full")
    spot0 = float(detail.get("spot") or 0.0)
    if spot0 <= 0:
        return  # no spot anchor → static chart only

    chain_skew = detail.get("iv_skew")
    metrics = ui.label("").classes("text-caption")
    ui.label("What-if · bounded · Black–Scholes re-price (model view)").classes("text-caption pm-muted")
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
        link_skew = None
        if chain_skew is not None:
            link_skew = ui.switch("Link IV to chain skew", value=True).props("dense")
            link_skew.tooltip(
                f"As spot moves, leg IV follows the chain skew ∂IV/∂lnK ≈ {float(chain_skew):+.2f} "
                "(sticky-moneyness). Off = flat-vol model view."
            )

    def recompute(_e=None) -> None:
        use_skew = bool(link_skew.value) if link_skew is not None else False
        try:
            m = whatif_from_detail(
                detail,
                iv_shift=float(iv.value or 0.0),
                iv_skew=(float(chain_skew) if (use_skew and chain_skew is not None) else 0.0),
                spot_override=float(spot.value or spot0),
                qty_scale=int(qty.value or 1),
            )
        except Exception as exc:  # noqa: BLE001 — surface, don't crash the card
            metrics.text = f"what-if error: {exc}"
            return
        g = m.get("net_greeks", {})
        skew_note = " · IV tracks chain skew" if use_skew else ""
        metrics.text = (
            f"net {m['net_credit']:,.0f} · max loss {m['max_loss']:,.0f} · "
            f"max gain {m['max_gain']:,.0f} · BE {m['breakevens']} · "
            f"Δ {g.get('delta', 0.0):.1f}  vega {g.get('vega', 0.0):.1f}{skew_note}"
        )
        chart.figure = _payoff_fig(m["payoff_curve"], m["breakevens"])
        chart.update()

    for element in (qty, iv, spot, link_skew):
        if element is not None:
            element.on_value_change(recompute)


# --------------------------------------------------------------------------- #
# Rendering
# --------------------------------------------------------------------------- #


def _render_inbox(box, journal: DecisionJournal) -> None:
    """Cross-advisor Inbox: the journal's latest Proceed/Monitor decisions."""
    box.clear()
    with box:
        items = journal.inbox()
        with ui.card().classes("w-full pm-card"):
            ui.label(f"Inbox · {len(items)} flagged (Proceed / Monitor)").classes("text-subtitle1")
            if not items:
                ui.label("Nothing flagged yet — run an advisor and Proceed/Monitor an idea.").classes("text-caption pm-muted")
            for d in items[:25]:
                note = f" — {d.note}" if d.note else ""
                ui.label(f"[{d.decision}] {d.title} · {d.subject} · {d.ts[:16]}{note}").classes("text-caption")


# Per-body expansion titles (so an FX/Roll card doesn't say "payoff · Greeks").
_BODY_TITLE = {
    "option_payoff": "Detail · payoff · Greeks · audit",
    "fx_alloc": "Detail · hedge legs · audit",
    "fx_carry": "Detail · carry ranking · audit",
    "roll": "Detail · position · audit",
}


def _ui_table(headers: list[str], rows: list[list[str]]) -> None:
    columns = [{"name": f"c{i}", "label": h, "field": f"c{i}", "align": "left"} for i, h in enumerate(headers)]
    ui_rows = [{f"c{i}": v for i, v in enumerate(r)} for r in rows]
    ui.table(columns=columns, rows=ui_rows).props("dense flat bordered").classes("w-full")


def _render_greeks(detail: dict) -> None:
    greeks = detail.get("net_greeks") or {}
    if greeks:
        ui.label("Greeks: " + "  ".join(f"{k} {float(v):.3f}" for k, v in greeks.items())).classes("text-caption")


def _render_option_body(detail: dict) -> None:
    if detail.get("est_payoff_curve"):
        _render_option_whatif(detail)
    for line in option_legs_lines(detail):
        ui.label(line).classes("text-caption")
    _render_greeks(detail)


def _render_fx_alloc_body(detail: dict) -> None:
    headers, rows = fx_alloc_table(detail)
    if rows:
        _ui_table(headers, rows)
    else:
        ui.label("No hedge legs in this allocation.").classes("text-caption pm-muted")
    totals = detail.get("totals") or {}
    if totals:
        ui.label("Totals: " + "   ".join(f"{k}: {v}" for k, v in totals.items())).classes("text-caption pm-muted")


def _render_fx_carry_body(detail: dict) -> None:
    headers, rows = fx_carry_table(detail)
    if rows:
        _ui_table(headers, rows)
    else:
        ui.label("No carry ranking available.").classes("text-caption pm-muted")


def _render_roll_body(detail: dict) -> None:
    with ui.grid(columns=2).classes("gap-x-6 gap-y-1"):
        for label, value in roll_facts(detail):
            ui.label(label).classes("text-caption pm-muted")
            ui.label(value).classes("text-caption")


def _render_generic_body(detail: dict) -> None:
    for line in option_legs_lines(detail):
        ui.label(line).classes("text-caption")
    _render_greeks(detail)


def _render_detail_body(s: Suggestion, detail: dict) -> None:
    """Dispatch the body-specific detail renderer by ``body_kind``."""
    if s.body_kind == "option_payoff":
        _render_option_body(detail)
    elif s.body_kind == "fx_alloc":
        _render_fx_alloc_body(detail)
    elif s.body_kind == "fx_carry":
        _render_fx_carry_body(detail)
    elif s.body_kind == "roll":
        _render_roll_body(detail)
    else:
        _render_generic_body(detail)


def _render_card(s: Suggestion, journal: DecisionJournal, on_decision) -> None:
    latest = journal.latest_by_suggestion().get(s.suggestion_id) if journal else None
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
        with ui.expansion(_BODY_TITLE.get(s.body_kind, "Detail · audit")).classes("w-full"):
            detail = s.detail or {}
            _render_detail_body(s, detail)
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
        # Decision controls (always visible) — record to the journal. The note
        # is a human memo, never interpreted (so it's not a free-form *control*).
        with ui.row().classes("items-center gap-2 w-full wrap"):
            note_in = ui.input(placeholder="note (optional)").props("dense").classes("grow")
            decided = ui.label(
                f"last: {latest.decision} · {latest.ts[:16]}" if latest else ""
            ).classes("text-caption pm-muted")

            def _record(decision_label: str) -> None:
                journal.record(
                    decision_from_suggestion(
                        s,
                        decision_label,
                        ts=datetime.now().isoformat(timespec="seconds"),
                        note=str(note_in.value or ""),
                    )
                )
                decided.text = f"✓ {decision_label} recorded"
                on_decision()
                try:
                    write_decision_snapshot(journal, as_of=s.as_of)  # refresh + mirror static snapshot
                except Exception:  # noqa: BLE001 — snapshot/mirror is best-effort, never block a decision
                    pass

            ui.button("Proceed", color="positive", on_click=lambda: _record("PROCEED")).props("dense")
            ui.button("Monitor", color="warning", on_click=lambda: _record("MONITOR")).props("dense")
            ui.button("Reject", color="negative", on_click=lambda: _record("REJECT")).props("dense")


def _render_results(box, run_result, journal: DecisionJournal, on_decision) -> None:
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
        # Render every advisor's output, PROCEED → MONITOR → INFO → REJECT, so the
        # operator sees that each advisor ran (even when it has nothing actionable).
        ordered = sorted(run_result.all_suggestions(), key=lambda s: (LABEL_ORDER.get(s.label, 9), -s.score))
        if not ordered:
            ui.label("No ideas generated for these inputs.").classes("text-caption")
            return
        for suggestion in ordered:
            _render_card(suggestion, journal, on_decision)


def _render_ai_unavailable(box, message: str) -> None:
    box.clear()
    with box:
        with ui.card().classes("w-full pm-card"):
            ui.label("AI+ unavailable").classes("text-subtitle1")
            ui.label(message).classes("text-caption pm-muted")


def _render_ai_advisory(box, advisory, *, book_note: str = "", n_ideas: int = 0) -> None:
    box.clear()
    with box:
        with ui.card().classes("w-full pm-card"):
            with ui.row().classes("items-center gap-2"):
                ui.badge("AI+", color="purple")
                ui.label("AI-generated synthesis · analysis only, not orders").classes("text-caption pm-muted")
            meta = f"model {advisory.model}"
            if advisory.prompt_tokens is not None:
                meta += f" · tokens {advisory.prompt_tokens}+{advisory.completion_tokens or 0}"
            meta += f" · {n_ideas} rule-based ideas in context{book_note}"
            ui.label(meta).classes("text-caption pm-muted")
            # Display-only rendering of the gateway's own output (no execution).
            ui.markdown(advisory.advice).classes("w-full")


def _render_rule_based_tab(journal: DecisionJournal, refresh_inbox) -> None:
    """The deterministic, no-AI advisor surface (inputs → run → ranked cards)."""
    with ui.row().classes("w-full gap-4 items-start no-wrap"):
        with ui.card().classes("p-4").style("min-width: 300px"):
            ui.label("Inputs").classes("text-subtitle1")
            sym_sel = ui.select(LIQUID_UNIVERSE, value=["SPY", "QQQ"], multiple=True, label="Universe").props("use-chips").classes("w-full")
            held_sel = ui.select(LIQUID_UNIVERSE, value=["SPY"], multiple=True, label="Treat as held (100 sh)").props("use-chips").classes("w-full")
            aum_in = ui.number("AUM (USD)", value=250_000, min=0, step=10_000, format="%.0f").classes("w-full")
            seed = current_regime_seed()  # default the regime controls to the live snapshot (overridable)
            regime_sel = ui.select(REGIME_OPTIONS, value=seed.regime, label="Regime").classes("w-full")
            conf_sel = ui.select(CONFIDENCE_OPTIONS, value=seed.confidence, label="Confidence").classes("w-full")
            crisis_sw = ui.switch("Crisis overlay", value=seed.crisis)
            if seed.is_seeded:
                ui.label(
                    f"Regime auto-seeded from latest snapshot: {seed.regime}"
                    f"{' · ' + seed.confidence if seed.confidence else ''}"
                    f"{' · stress overlay' if seed.crisis else ''} (override above)"
                ).classes("text-caption pm-muted")
            rv_sw = ui.switch("Fetch realized vol (slower)", value=False)
            earnings_sw = ui.switch("Check earnings (slower)", value=False)
            portfolio_sw = ui.switch("Use my portfolio (live positions)", value=True)
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
            check_earnings=bool(earnings_sw.value),
        )
        if not inp.symbols:
            status.text = "Pick at least one symbol."
            run_btn.enable()
            return
        context, book_note = build_run_context(inp, use_portfolio=bool(portfolio_sw.value))
        try:
            run_result = await asyncio.to_thread(
                _SERVICE.run, context, advisors=None, params_by_advisor=option_run_params(inp)
            )
        except Exception as exc:  # noqa: BLE001 — surface, don't crash the page
            status.text = f"Failed: {type(exc).__name__}: {exc}"
            run_btn.enable()
            return
        _render_results(results_box, run_result, journal, refresh_inbox)
        status.text = f"Done · {len(run_result.all_suggestions())} ideas{book_note}"
        run_btn.enable()

    run_btn.on_click(run)


def _render_ai_tab() -> None:
    """The opt-in AI+ surface: rule-based context + ideas → OpenClaw synthesis.

    Parallel to (never replacing) the rule-based tab. Read-only — analysis text
    only. Degrades to an explainer when the gateway token is unset/unreachable.
    """
    token_present = bool(resolve_gateway_token())
    with ui.row().classes("w-full gap-4 items-start no-wrap"):
        with ui.card().classes("p-4").style("min-width: 300px"):
            ui.label("AI+ inputs").classes("text-subtitle1")
            ui.label(
                "Synthesizes the rule-based ideas + your book + regime via the local "
                "OpenClaw gateway. Analysis only — never orders."
            ).classes("text-caption pm-muted")
            sym_sel = ui.select(LIQUID_UNIVERSE, value=["SPY", "QQQ"], multiple=True, label="Universe").props("use-chips").classes("w-full")
            held_sel = ui.select(LIQUID_UNIVERSE, value=["SPY"], multiple=True, label="Treat as held (100 sh)").props("use-chips").classes("w-full")
            aum_in = ui.number("AUM (USD)", value=250_000, min=0, step=10_000, format="%.0f").classes("w-full")
            seed = current_regime_seed()
            regime_sel = ui.select(REGIME_OPTIONS, value=seed.regime, label="Regime").classes("w-full")
            conf_sel = ui.select(CONFIDENCE_OPTIONS, value=seed.confidence, label="Confidence").classes("w-full")
            crisis_sw = ui.switch("Crisis overlay", value=seed.crisis)
            portfolio_sw = ui.switch("Use my portfolio (live positions)", value=True)
            model_sel = ui.select(AI_MODELS, value=AI_MODELS[0], label="AI model").classes("w-full")
            include_ideas_sw = ui.switch("Include rule-based ideas as context", value=True)
            gen_btn = ui.button("Generate AI advisory")
            status = ui.label(
                "" if token_present
                else "AI+ disabled — set OPENCLAW_GATEWAY_TOKEN and start the OpenClaw gateway."
            ).classes("text-caption pm-muted")

        out_box = ui.column().classes("grow gap-3")

    async def generate() -> None:
        gen_btn.disable()
        status.text = "Thinking…"
        out_box.clear()
        inp = AdvisorInputs(
            symbols=list(sym_sel.value or []),
            held=list(held_sel.value or []),
            aum=float(aum_in.value or 0),
            regime=regime_sel.value or "",
            confidence=conf_sel.value or "",
            crisis=bool(crisis_sw.value),
        )
        if not inp.symbols:
            status.text = "Pick at least one symbol."
            gen_btn.enable()
            return
        context, book_note = build_run_context(inp, use_portfolio=bool(portfolio_sw.value))
        suggestions: list[Suggestion] = []
        if include_ideas_sw.value:
            try:
                run_result = await asyncio.to_thread(_SERVICE.run, context, advisors=None)
                suggestions = run_result.all_suggestions()
            except Exception:  # noqa: BLE001 — AI can still run on context alone
                suggestions = []
        config = GatewayConfig.from_env(model=str(model_sel.value or AI_MODELS[0]))
        try:
            advisory = await asyncio.to_thread(
                request_ai_advisory, context=context, suggestions=suggestions, config=config,
            )
        except GatewayAuthMissing:
            _render_ai_unavailable(
                out_box,
                "AI+ needs OPENCLAW_GATEWAY_TOKEN. Set it in the environment or local.env, "
                "then start the OpenClaw gateway.",
            )
            status.text = "AI+ disabled (no token)."
            gen_btn.enable()
            return
        except GatewayError as exc:
            _render_ai_unavailable(out_box, f"Could not reach the OpenClaw gateway: {exc}")
            status.text = "Gateway error."
            gen_btn.enable()
            return
        except Exception as exc:  # noqa: BLE001 — never crash the page
            _render_ai_unavailable(out_box, f"AI+ failed: {type(exc).__name__}: {exc}")
            status.text = "Failed."
            gen_btn.enable()
            return
        _render_ai_advisory(out_box, advisory, book_note=book_note, n_ideas=len(suggestions))
        status.text = f"Done · {advisory.model}{book_note}"
        gen_btn.enable()

    gen_btn.on_click(generate)


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

        journal = default_decision_journal()
        inbox_box = ui.column().classes("w-full")

        def refresh_inbox() -> None:
            _render_inbox(inbox_box, journal)

        refresh_inbox()

        # Two parallel surfaces, selectable via tab: the deterministic rule-based
        # advisor (default) and the opt-in AI+ synthesis layer.
        with ui.tabs().classes("w-full") as tabs:
            rb_tab = ui.tab("Rule-based")
            ai_tab = ui.tab("AI+")
        with ui.tab_panels(tabs, value=rb_tab).classes("w-full"):
            with ui.tab_panel(rb_tab):
                _render_rule_based_tab(journal, refresh_inbox)
            with ui.tab_panel(ai_tab):
                _render_ai_tab()
