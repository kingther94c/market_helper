"""FX Hedging advisor → umbrella adapter (+ FX Carry Tilt sub-module).

Wraps the existing ``domain/portfolio_monitor/services/fx_hedge_advisor`` two-
surface engine. In the umbrella it runs **cached** by default (reads the shared
artifact — no Yahoo refresh, no network), so a plain "Run advisor" is fast; an
on-demand ``refresh=True`` force-recomputes (the slow OLS path). Emits the
uniform :class:`~..contracts.Suggestion` shape:

* a **hedge-target** suggestion (target allocation across CME FX futures), and
* a **FX Carry Tilt** sub-module suggestion (rank currencies by indicative
  overnight-rate carry → tilt the hedge toward higher-carry legs).

FX detail rides under non-colliding keys (``fx_legs`` / ``totals`` / ``ranking``)
so the generic card renders without option-specific assumptions.
"""

from __future__ import annotations

from market_helper.domain.portfolio_monitor.services.fx_carry_tilt import (
    DEFAULT_TILT_STRENGTH,
    compute_fx_carry_tilt,
)

from ..contracts import (
    LABEL_INFO,
    LABEL_MONITOR,
    AdvisorContext,
    AdvisorResult,
    Suggestion,
)


def _carry_bps(leg) -> float:
    notional = abs(getattr(leg, "target_notional_usd", 0.0) or 0.0)
    carry = getattr(leg, "expected_annual_carry_usd", 0.0) or 0.0
    return (10_000.0 * carry / notional) if notional else 0.0


def _hedge_suggestion(alloc, *, as_of: str, data_mode: str) -> Suggestion:
    totals = dict(getattr(alloc, "totals", {}) or {})
    regression = dict(getattr(alloc, "regression", {}) or {})
    carry_bps = totals.get("expected_annual_carry_bps")
    r2 = regression.get("r_squared")
    notional = float(getattr(alloc, "hedge_notional_usd", 0.0) or 0.0)
    pair = getattr(alloc, "hedge_target_pair", "")
    legs = [
        {
            "currency": l.currency, "instrument": l.instrument, "beta": round(l.beta, 4),
            "target_contracts": l.target_contracts,
            "target_notional_usd": round(l.target_notional_usd, 0),
            "expiry": l.expiry, "carry_usd": round(l.expected_annual_carry_usd, 0),
            "carry_bps": round(_carry_bps(l), 1), "on_rate": l.on_rate,
        }
        for l in getattr(alloc, "legs", [])
    ]
    return Suggestion(
        advisor="fx_hedge",
        suggestion_id=f"fx_hedge:target:{getattr(alloc, 'run_date', '')}",
        as_of=as_of,
        title=f"FX hedge target · {pair}",
        subject=pair or "FX",
        category="FX_HEDGE",
        label=LABEL_MONITOR,
        score=0.70,
        thesis=f"Hedge ${notional:,.0f} USD exposure across CME FX futures (betas vs {pair}).",
        why_now=f"Target as of {getattr(alloc, 'run_date', '?')} · {getattr(alloc, 'hedge_notional_source', '')}.",
        headline_metrics={
            "notional": f"${notional:,.0f}",
            "carry": f"{carry_bps:.0f}bps" if carry_bps is not None else "—",
            "R2": f"{r2:.2f}" if r2 is not None else "—",
            "legs": str(len(legs)),
        },
        rationale="Per-ccy contracts: " + ", ".join(f"{l['currency']} {l['target_contracts']:+d}" for l in legs),
        data_mode=data_mode,
        body_kind="fx_alloc",
        detail={"hedge_notional_usd": notional, "pair": pair, "fx_legs": legs, "totals": totals},
    )


def _carry_tilt_suggestion(
    alloc, *, as_of: str, data_mode: str, tilt_strength: float = DEFAULT_TILT_STRENGTH
) -> Suggestion | None:
    legs = list(getattr(alloc, "legs", []))
    if not legs:
        return None
    ranked = sorted(((l.currency, _carry_bps(l), l.on_rate) for l in legs), key=lambda x: x[1], reverse=True)
    best, worst = ranked[0], ranked[-1]
    tilt = compute_fx_carry_tilt(alloc, tilt_strength=tilt_strength)

    # Back-compat ranking + the full before/after tilt overlay under one detail.
    detail = {"ranking": [{"currency": c, "carry_bps": round(b, 1), "on_rate": r} for c, b, r in ranked]}
    if tilt is not None:
        detail["tilt"] = tilt.as_detail()
        impact_bps = tilt.carry_impact_bps
        impact_usd = tilt.carry_impact_usd
        dev = tilt.hedge_deviation_pct
        thesis = (
            f"Carry tilt on the {best[0]}/{worst[0]} legs: "
            f"{impact_bps:+.0f}bps (${impact_usd:+,.0f}/yr) extra carry for a {dev:.0%} deviation from the "
            "hedge-optimal allocation."
        )
        headline = {
            "carry+": f"{impact_bps:+.0f}bps",
            "$/yr": f"{impact_usd:+,.0f}",
            "deviation": f"{dev:.0%}",
            "strength": f"{tilt.tilt_strength:.0%}",
        }
        rationale = (
            "Before → after (annual carry): "
            f"${tilt.before.get('annual_carry_usd', 0):,.0f} → ${tilt.after.get('annual_carry_usd', 0):,.0f}; "
            f"gross ${tilt.before.get('gross_notional_usd', 0):,.0f} → "
            f"${tilt.after.get('gross_notional_usd', 0):,.0f}. " + tilt.note
        )
    else:
        thesis = f"Tilt the hedge toward higher-carry legs — {best[0]} carries the most, {worst[0]} the least."
        headline = {"top": f"{best[0]} {best[1]:+.0f}bps", "bottom": f"{worst[0]} {worst[1]:+.0f}bps"}
        rationale = "Annualized carry (bps of leg notional): " + ", ".join(f"{c} {b:+.0f}" for c, b, _ in ranked)

    return Suggestion(
        advisor="fx_hedge",
        suggestion_id="fx_hedge:carry_tilt",
        as_of=as_of,
        title="FX carry tilt",
        subject="FX",
        category="FX_CARRY",
        label=LABEL_MONITOR,
        score=0.60,
        thesis=thesis,
        why_now="Carry rate-approximated from configured overnight-rate differentials vs USD (no forward curve in-repo).",
        headline_metrics=headline,
        rationale=rationale,
        data_mode=data_mode,
        body_kind="fx_carry",
        detail=detail,
    )


def _missing(as_of: str, why: str, warnings: list[str]) -> AdvisorResult:
    return AdvisorResult(
        advisor="fx_hedge", as_of=as_of, data_mode="missing", warnings=warnings,
        suggestions=[Suggestion(
            advisor="fx_hedge", suggestion_id="fx_hedge:missing", as_of=as_of,
            title="FX hedge allocation not available", subject="FX", category="FX_HEDGE",
            label=LABEL_INFO, thesis="No cached FX hedge allocation found.", why_now=why, body_kind="fx_alloc",
        )],
    )


class FxHedgeAdvisorPlugin:
    """Umbrella advisor wrapping the FX hedge engine (cached-by-default)."""

    key = "fx_hedge"
    title = "FX Hedging"

    def produce(
        self,
        context: AdvisorContext,
        *,
        mode: str = "cached",
        refresh: bool = False,
        tilt_strength: float = DEFAULT_TILT_STRENGTH,
        artifact_path=None,
        config_path=None,
        provider=None,  # injectable for tests
    ) -> AdvisorResult:
        as_of = context.as_of
        if provider is None:
            from market_helper.domain.portfolio_monitor.services.fx_hedge_advisor import (
                provide_fx_hedge_allocation as provider,  # lazy: keep heavy deps out of registry build
            )
        kwargs = {"mode": "force-refresh" if refresh else mode}
        if artifact_path is not None:
            kwargs["artifact_path"] = artifact_path
        if config_path is not None:
            kwargs["config_path"] = config_path

        try:
            state = provider(**kwargs)
        except Exception as exc:  # noqa: BLE001 — never crash the umbrella run
            return _missing(as_of, f"FX hedge provider error: {type(exc).__name__}: {str(exc)[:120]}", [str(exc)[:200]])

        alloc = getattr(state, "allocation", None)
        if alloc is None:
            return _missing(
                as_of,
                "Run `fx-hedge-report` (or trigger a refresh) to compute the allocation.",
                [state.error_message] if getattr(state, "error_message", None) else [],
            )

        data_mode = (
            "fresh" if getattr(state, "computed_fresh", False)
            else (f"cached_{state.age_days}d" if getattr(state, "age_days", None) is not None else "cached")
        )
        run_as_of = as_of or getattr(alloc, "run_date", "")
        suggestions = [_hedge_suggestion(alloc, as_of=run_as_of, data_mode=data_mode)]
        tilt = _carry_tilt_suggestion(alloc, as_of=run_as_of, data_mode=data_mode, tilt_strength=tilt_strength)
        if tilt is not None:
            suggestions.append(tilt)
        return AdvisorResult(
            advisor="fx_hedge", as_of=run_as_of, data_mode=data_mode, suggestions=suggestions,
            meta={"source": getattr(state, "source_label", ""), "n_legs": len(getattr(alloc, "legs", []))},
        )
