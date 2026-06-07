"""Idea cards + body builders + live what-if + results/inbox rendering.

Pure table/fact builders (``fx_alloc_table``, ``fx_carry_table``, ``roll_facts``,
``option_legs_lines``, ``payoff_figure``, ``_num``, ``_pct``) are unit-tested as
the adapter→body contract; the ``ui.*`` wrappers stay thin around them.
"""
from __future__ import annotations

from datetime import datetime

from nicegui import ui

from market_helper.application.trade_advisor import write_decision_snapshot
from market_helper.domain.option_advisor.structures import whatif_from_detail
from market_helper.trade_advisor.contracts import (
    LABEL_INFO,
    LABEL_MONITOR,
    LABEL_ORDER,
    LABEL_PROCEED,
    LABEL_REJECT,
    Suggestion,
)
from market_helper.trade_advisor.journal import DecisionJournal, decision_from_suggestion

_LABEL_COLOR = {
    LABEL_PROCEED: "positive",
    LABEL_MONITOR: "warning",
    LABEL_REJECT: "negative",
    LABEL_INFO: "info",
}


# --------------------------------------------------------------------------- #
# Pure builders (unit-tested)
# --------------------------------------------------------------------------- #


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
            str(leg.get("currency", "")),
            str(leg.get("instrument", "")),
            _num(leg.get("beta"), "+.3f"),
            _num(leg.get("target_contracts"), "+d"),
            _num(leg.get("target_notional_usd"), ",.0f"),
            _num(leg.get("carry_bps"), "+.0f"),
            _pct(leg.get("on_rate")),
            str(leg.get("expiry", "")),
        ]
        for leg in (detail.get("fx_legs") or [])
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


def fx_carry_tilt_table(detail: dict) -> tuple[list[str], list[list[str]]]:
    """Headers + before/after rows for the FX carry tilt overlay (``detail['tilt']['rows']``)."""
    headers = ["Ccy", "Carry %", "Base ct", "Tilt ct", "Δ ct", "Base $", "Tilt $", "Δ $"]
    tilt = detail.get("tilt") or {}
    rows = [
        [
            str(r.get("currency", "")),
            _num(r.get("carry_rate_pct"), "+.2f"),
            _num(r.get("base_contracts"), "+d"),
            _num(r.get("tilted_contracts"), "+d"),
            _num(r.get("delta_contracts"), "+d"),
            _num(r.get("base_notional_usd"), ",.0f"),
            _num(r.get("tilted_notional_usd"), ",.0f"),
            _num(r.get("delta_notional_usd"), "+,.0f"),
        ]
        for r in (tilt.get("rows") or [])
    ]
    return headers, rows


def futures_roll_facts(detail: dict) -> list[tuple[str, str]]:
    """Label/value pairs describing a held future for the Roll & Carry Calendar body."""
    days = detail.get("days_to_roll")
    return [
        ("Root", str(detail.get("root", "—"))),
        ("Contract", str(detail.get("contract") or "—")),
        ("Exchange", str(detail.get("exchange") or "—")),
        ("Quantity", _num(detail.get("qty"))),
        ("Delivery", str(detail.get("delivery_label", "—"))),
        ("Roll target", str(detail.get("roll_target") or "—")),
        ("To roll", "—" if days is None else f"{days}d"),
        ("Schedule", "GSCI-like" if detail.get("schedule") == "gsci" else "expiry"),
    ]


def tactical_facts(detail: dict) -> list[tuple[str, str]]:
    """Label/value pairs describing a tactical idea for its detail body."""
    return [
        ("Stance", str(detail.get("direction", "—"))),
        ("Confidence", str(detail.get("confidence", "—"))),
        ("Expression", str(detail.get("expression", "—"))),
        ("Invalidation", str(detail.get("invalidation", "—"))),
    ]


# --------------------------------------------------------------------------- #
# Rendering
# --------------------------------------------------------------------------- #


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
    "fx_carry": "Detail · carry tilt before/after · audit",
    "roll": "Detail · position · audit",
    "futures_roll": "Detail · contract · roll target · audit",
    "tactical": "Detail · evidence · invalidation · audit",
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
    tilt = detail.get("tilt") or {}
    if tilt.get("rows"):
        before, after = tilt.get("before") or {}, tilt.get("after") or {}
        ui.label(
            f"Annual carry before → after: ${before.get('annual_carry_usd', 0):,.0f} → "
            f"${after.get('annual_carry_usd', 0):,.0f}  "
            f"({tilt.get('carry_impact_bps', 0):+.0f}bps · {tilt.get('hedge_deviation_pct', 0) * 100:.0f}% deviation "
            f"from the hedge-optimal)"
        ).classes("text-caption")
        headers, rows = fx_carry_tilt_table(detail)
        _ui_table(headers, rows)
        if tilt.get("note"):
            ui.label(tilt["note"]).classes("text-caption pm-muted")
        return
    # Fallback: the plain carry ranking (no tilt overlay present).
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


def _render_futures_roll_body(detail: dict) -> None:
    with ui.grid(columns=2).classes("gap-x-6 gap-y-1"):
        for label, value in futures_roll_facts(detail):
            ui.label(label).classes("text-caption pm-muted")
            ui.label(value).classes("text-caption")
    if detail.get("note"):
        ui.label(detail["note"]).classes("text-caption pm-muted")


def _render_tactical_body(detail: dict) -> None:
    with ui.grid(columns=2).classes("gap-x-6 gap-y-1"):
        for label, value in tactical_facts(detail):
            ui.label(label).classes("text-caption pm-muted")
            ui.label(value).classes("text-caption")
    evidence = detail.get("evidence") or []
    if evidence:
        ui.label("Evidence: " + " · ".join(str(e) for e in evidence)).classes("text-caption pm-muted")


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
    elif s.body_kind == "futures_roll":
        _render_futures_roll_body(detail)
    elif s.body_kind == "tactical":
        _render_tactical_body(detail)
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


def _render_module(box, suggestions: list[Suggestion], journal: DecisionJournal, on_decision, *, empty_note: str = "") -> None:
    """Render one cockpit module's suggestions as cards (PROCEED → MONITOR → INFO → REJECT)."""
    box.clear()
    with box:
        ordered = sorted(suggestions, key=lambda s: (LABEL_ORDER.get(s.label, 9), -s.score))
        if not ordered:
            ui.label(empty_note or "No ideas for these inputs yet — run the advisor.").classes("text-caption pm-muted")
            return
        for suggestion in ordered:
            _render_card(suggestion, journal, on_decision)


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
