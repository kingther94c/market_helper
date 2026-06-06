"""HTML rendering for the FX Hedging Advisor (Risk → FX section).

Renders the *Target FX Allocation* card from a
:class:`~market_helper.domain.portfolio_monitor.services.fx_hedge_advisor.FxHedgeArtifactState`.
The state already carries the computed allocation plus the freshly-computed /
loaded-from-cache flag the report is required to surface, so this module is a
thin presenter — no second view-model layer.
"""

from __future__ import annotations

import html
from typing import Any

from market_helper.common.datetime_display import format_local_datetime
from market_helper.domain.portfolio_monitor.services.fx_hedge_advisor import (
    FxHedgeAllocation,
    FxHedgeArtifactState,
    FxHedgeLeg,
)
from market_helper.reporting.html_tables import (
    HtmlTableColumn,
    HtmlTableRow,
    render_html_table,
)


def _fmt_usd(value: float | None, *, signed: bool = False) -> str:
    if value is None:
        return "—"
    sign = "+" if signed and value > 0 else ""
    return f"{sign}${value:,.0f}"


def _fmt_pct(value: float | None, *, places: int = 1) -> str:
    if value is None:
        return "—"
    return f"{value * 100:.{places}f}%"


def _fmt_contracts(value: int) -> str:
    if value == 0:
        return "0"
    side = "Long" if value > 0 else "Short"
    return f"{side} {abs(value)}"


def _fmt_beta(leg: FxHedgeLeg) -> str:
    se = "" if leg.beta_std_error is None else f" ±{leg.beta_std_error:.3f}"
    t = "" if leg.t_stat is None else f" · t={leg.t_stat:.1f}"
    return f"{leg.beta:+.3f}{se}{t}"


def _badge_html(state: FxHedgeArtifactState) -> str:
    if state.computed_fresh:
        tone, text = "fx-badge--fresh", "Freshly computed"
    elif state.state == "stale":
        tone, text = "fx-badge--stale", state.source_label
    else:
        tone, text = "fx-badge--cache", state.source_label
    return f"<span class='fx-badge {tone}'>{html.escape(text)}</span>"


def render_fx_hedge_section(state: FxHedgeArtifactState) -> str:
    """Render the Risk → FX *Target FX Allocation* block.

    Always returns a section (anchored ``#fx-hedge``). Missing / error states
    render an actionable explainer card instead of disappearing.
    """
    if state.allocation is None:
        return _render_unavailable(state)
    return _render_allocation(state, state.allocation)


def _render_allocation(state: FxHedgeArtifactState, alloc: FxHedgeAllocation) -> str:
    legs_table = render_html_table(
        columns=_leg_columns(),
        rows=_leg_rows(alloc) + [_totals_row(alloc)],
        empty_message="No hedge legs",
        data_attributes={"fx-hedge-table": "1"},
    )
    reg = alloc.regression
    totals = alloc.totals
    window = alloc.data_window
    metrics = (
        "<div class='metrics'>"
        f"<div class='metric'><span>Hedge Notional (USD)</span>"
        f"<strong>{_fmt_usd(alloc.hedge_notional_usd)}</strong></div>"
        f"<div class='metric'><span>Hedge Quality (R²)</span>"
        f"<strong>{_fmt_pct(reg.get('r_squared'))}</strong></div>"
        f"<div class='metric'><span>Unhedged (basis risk)</span>"
        f"<strong>{_fmt_pct(totals.get('statistical_unhedged_fraction'))}</strong></div>"
        f"<div class='metric'><span>Expected Carry (annual)</span>"
        f"<strong>{_fmt_usd(totals.get('expected_annual_carry_usd'), signed=True)}"
        f" <small>({totals.get('expected_annual_carry_bps', 0.0):+.0f} bps)</small></strong></div>"
        "</div>"
    )
    meta = (
        "<ul class='fx-meta'>"
        f"<li><span>Hedge target</span><strong>{html.escape(alloc.hedge_target_pair)}</strong>"
        f" <small>({html.escape(alloc.hedge_target_yahoo)})</small></li>"
        f"<li><span>Base currency</span><strong>{html.escape(alloc.base_currency)}</strong></li>"
        f"<li><span>Notional source</span><strong>{html.escape(alloc.hedge_notional_source)}</strong></li>"
        f"<li><span>Run date</span><strong>{html.escape(alloc.run_date)}</strong></li>"
        f"<li><span>Data window</span><strong>{html.escape(str(window.get('start')))} → "
        f"{html.escape(str(window.get('end')))}</strong>"
        f" <small>({window.get('observations', 0)} weekly obs)</small></li>"
        f"<li><span>Contract expiry</span><strong>{html.escape(_first_expiry(alloc))}</strong>"
        " <small>(front IMM quarter)</small></li>"
        "</ul>"
    )
    return (
        "<section id='fx-hedge' class='card fx-hedge-card'>"
        "<div class='fx-hedge-head'>"
        "<p class='fx-eyebrow'>FX Hedging Advisor</p>"
        f"<h2>Target FX Allocation — {html.escape(alloc.hedge_target_pair)}</h2>"
        f"{_badge_html(state)}"
        "</div>"
        "<p class='fx-lede'>Regression-replicated hedge for the SGD-base investor's "
        "USD AUM, sized into liquid CME FX futures. Positive contracts are "
        "<strong>long the foreign currency / short USD</strong>.</p>"
        f"{metrics}"
        f"{meta}"
        f"{legs_table}"
        f"{_conventions_block(alloc)}"
        "</section>"
    )


def _leg_columns() -> list[HtmlTableColumn]:
    return [
        HtmlTableColumn("instrument", "Instrument"),
        HtmlTableColumn("beta", "Beta (hedge ratio)", align="end"),
        HtmlTableColumn("target_notional", "Target Notional", align="end"),
        HtmlTableColumn("contract_size", "Contract Size", align="end"),
        HtmlTableColumn("usd_per_contract", "USD / Contract", align="end"),
        HtmlTableColumn("contracts", "Target Contracts", align="end"),
        HtmlTableColumn("realized", "Realized Notional", align="end"),
        HtmlTableColumn("residual", "Residual", align="end"),
        HtmlTableColumn("on_rate", "ON Rate", align="end"),
        HtmlTableColumn("carry", "Exp. Carry", align="end"),
        HtmlTableColumn("expiry", "Expiry", align="end"),
    ]


def _leg_rows(alloc: FxHedgeAllocation) -> list[HtmlTableRow]:
    rows: list[HtmlTableRow] = []
    for leg in alloc.legs:
        rows.append(
            HtmlTableRow(
                cells={
                    "instrument": leg.instrument,
                    "beta": _fmt_beta(leg),
                    "target_notional": _fmt_usd(leg.target_notional_usd, signed=True),
                    "contract_size": f"{leg.contract_size:,.0f} {leg.contract_size_currency}",
                    "usd_per_contract": _fmt_usd(leg.usd_notional_per_contract),
                    "contracts": _fmt_contracts(leg.target_contracts),
                    "realized": _fmt_usd(leg.realized_notional_usd, signed=True),
                    "residual": _fmt_usd(leg.residual_notional_usd, signed=True),
                    "on_rate": _fmt_pct(leg.on_rate, places=2),
                    "carry": _fmt_usd(leg.expected_annual_carry_usd, signed=True),
                    "expiry": leg.expiry,
                }
            )
        )
    return rows


def _totals_row(alloc: FxHedgeAllocation) -> HtmlTableRow:
    totals = alloc.totals
    return HtmlTableRow(
        row_class="fx-hedge-total",
        cells={
            "instrument": "Total (gross)",
            "beta": "",
            "target_notional": _fmt_usd(totals.get("target_notional_usd_gross")),
            "contract_size": "",
            "usd_per_contract": "",
            "contracts": "",
            "realized": _fmt_usd(totals.get("realized_notional_usd_gross")),
            "residual": _fmt_usd(totals.get("rounding_residual_usd"), signed=True),
            "on_rate": "",
            "carry": _fmt_usd(totals.get("expected_annual_carry_usd"), signed=True),
            "expiry": "",
        },
    )


def _first_expiry(alloc: FxHedgeAllocation) -> str:
    return alloc.legs[0].expiry if alloc.legs else "—"


def _conventions_block(alloc: FxHedgeAllocation) -> str:
    conv = alloc.return_convention
    items = [
        f"<strong>Target.</strong> {html.escape(alloc.target_definition)}",
        (
            "<strong>Price basis.</strong> All spot series normalised to "
            f"<em>{html.escape(str(conv.get('price_basis')))}</em> (USD per 1 unit of "
            "currency). Inverted Yahoo quotes (SGD=X, JPY=X, CNH=X) are flipped to "
            "this basis; note this is the inverse of the repo's SGD-per-USD "
            "<code>fx_usdsgd_eod</code>."
        ),
        (
            "<strong>Returns.</strong> "
            f"{html.escape(str(conv.get('return_method')))} returns on "
            f"{html.escape(str(conv.get('frequency')))}-resampled spot, "
            f"{'overlapping' if conv.get('overlapping') else 'non-overlapping'} weekly "
            f"windows, {conv.get('lookback_weeks')}-week lookback."
        ),
        (
            "<strong>Sizing &amp; rounding.</strong> Target notional = beta × hedge "
            "notional; contracts = nearest whole of (target ÷ USD-per-contract), "
            "halves away from zero. Residual = target − realized after rounding."
        ),
        (
            "<strong>Carry (shown, not optimised).</strong> Indicative annual carry = "
            "realized notional × (foreign ON − USD ON) using configured ON rates as of "
            f"{html.escape(alloc.on_rates_as_of or 'n/a')} "
            f"({html.escape(alloc.on_rates_source)})."
        ),
        (
            "<strong>Limitations (V1).</strong> First-order USD/SGD hedge only — the "
            "hedge legs' own USD-P&amp;L→SGD conversion (second order), margin, and "
            "transaction costs are not optimised. Majors are collinear, so individual "
            "betas are less stable than the basket's overall fit (R²). Data source: "
            f"{html.escape(alloc.data_source)}."
        ),
    ]
    lis = "".join(f"<li>{item}</li>" for item in items)
    return (
        "<details class='fx-conventions'>"
        "<summary>Conventions, sizing &amp; limitations</summary>"
        f"<ul>{lis}</ul>"
        "</details>"
    )


def _render_unavailable(state: FxHedgeArtifactState) -> str:
    if state.state == "error":
        title = "FX hedge advisor failed"
        hint = (
            "The advisor could not refresh (data feed or fit error). "
            f"Details: {state.error_message or 'unknown error'}."
        )
    else:
        title = "FX hedge allocation not yet computed"
        hint = (
            "No cached allocation found. Run "
            "<code>python -m market_helper.cli.main fx-hedge-report</code> "
            "or open the dashboard FX refresh to produce it."
        )
    last_run = (
        format_local_datetime(state.last_run_at.isoformat())
        if state.last_run_at is not None
        else "never"
    )
    return (
        "<section id='fx-hedge' class='card fx-hedge-card fx-hedge-card--unavailable'>"
        "<p class='fx-eyebrow'>FX Hedging Advisor</p>"
        f"<h2>{html.escape(title)}</h2>"
        f"<p class='fx-lede'>{hint}</p>"
        f"<p class='fx-meta-note'>Last run: {html.escape(last_run)}</p>"
        "</section>"
    )


def fx_hedge_section_styles() -> str:
    """Scoped CSS for the FX section, injected once into the report head."""
    return """
.fx-hedge-card { margin-top: 16px; }
.fx-hedge-head { display: flex; align-items: baseline; gap: 12px; flex-wrap: wrap; }
.fx-hedge-head h2 { margin: 0; }
.fx-eyebrow { text-transform: uppercase; letter-spacing: .08em; font-size: .72rem;
  font-weight: 700; color: var(--muted, #64748b); margin: 0 0 2px; }
.fx-badge { font-size: .72rem; font-weight: 700; padding: 2px 10px; border-radius: 999px;
  border: 1px solid transparent; white-space: nowrap; }
.fx-badge--fresh { background: #dcfce7; color: #166534; border-color: #86efac; }
.fx-badge--cache { background: #e2e8f0; color: #334155; border-color: #cbd5e1; }
.fx-badge--stale { background: #fef3c7; color: #92400e; border-color: #fcd34d; }
.fx-lede { color: var(--muted, #475569); margin: 6px 0 12px; max-width: 70ch; }
.fx-meta { list-style: none; display: flex; flex-wrap: wrap; gap: 8px 24px;
  padding: 0; margin: 0 0 14px; }
.fx-meta li { display: flex; flex-direction: column; }
.fx-meta li span { font-size: .72rem; color: var(--muted, #64748b); }
.fx-meta li strong { font-variant-numeric: tabular-nums; }
.fx-hedge-total .report-table__cell { font-weight: 700; border-top: 2px solid #e2e8f0; }
.fx-conventions { margin-top: 12px; font-size: .82rem; color: var(--muted, #475569); }
.fx-conventions summary { cursor: pointer; font-weight: 600; }
.fx-conventions ul { margin: 8px 0 0; padding-left: 18px; }
.fx-conventions li { margin: 4px 0; }
.fx-hedge-card--unavailable .fx-lede { color: #92400e; }
""".strip()


__all__ = ["fx_hedge_section_styles", "render_fx_hedge_section"]
