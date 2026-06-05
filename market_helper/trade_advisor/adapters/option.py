"""Option advisor → umbrella adapter.

Wraps :mod:`market_helper.domain.option_advisor.service` and maps each
``OptionIdea`` onto the shared :class:`~..contracts.Suggestion`. No behavior
change to the option engine — this is a pure projection (M1).
"""

from __future__ import annotations

from dataclasses import asdict

from market_helper.domain.option_advisor import service as option_service
from market_helper.domain.option_advisor.contracts import OptionAdvisoryResult, OptionIdea

from ..contracts import AdvisorContext, AdvisorResult, AuditEntry, Sizing, Suggestion


def _sizing_from(idea: OptionIdea) -> Sizing | None:
    s = idea.sizing
    if s is None:
        return None
    return Sizing(
        basis=s.basis,
        max_units=s.max_contracts,
        capital_at_risk_usd=s.capital_at_risk_usd,
        notional_pct_of_aum=s.notional_pct_of_aum,
        notes=s.notes,
    )


def _headline_metrics(idea: OptionIdea) -> dict[str, str]:
    m: dict[str, str] = {}
    cf = idea.est_net_debit_credit
    if cf is not None:
        m["net"] = f"{'credit' if cf >= 0 else 'debit'} {abs(cf):,.0f}"
    if idea.est_max_loss is not None:
        m["max_loss"] = f"{idea.est_max_loss:,.0f}"
    if idea.est_max_gain is not None:
        m["max_gain"] = f"{idea.est_max_gain:,.0f}"
    if idea.est_breakevens:
        m["breakeven"] = ", ".join(f"{b:g}" for b in idea.est_breakevens)
    er = idea.event_risk
    if er is not None and er.event_status == "known" and er.days_to_earnings is not None:
        m["earnings"] = f"{er.days_to_earnings}d"
    return m


def suggestion_from_idea(idea: OptionIdea, data_mode: str) -> Suggestion:
    return Suggestion(
        advisor="option",
        suggestion_id=idea.idea_id,
        as_of=idea.as_of,
        title=f"{idea.structure_type} · {idea.underlying_symbol}",
        subject=idea.underlying_symbol,
        category=idea.category,
        label=idea.label,
        score=idea.score,
        thesis=idea.thesis,
        why_now=idea.why_now,
        rationale=idea.rationale,
        headline_metrics=_headline_metrics(idea),
        drivers=list(idea.drivers),
        audit=[AuditEntry(f.filter_name, f.passed, f.severity, f.detail) for f in idea.filters_applied],
        data_mode=data_mode,
        sizing=_sizing_from(idea),
        body_kind="option_payoff",
        detail=asdict(idea),
    )


class OptionAdvisorPlugin:
    """Umbrella plugin for the option advisor."""

    key = "option"
    title = "Option Advisor"

    def produce(
        self,
        context: AdvisorContext,
        *,
        symbols: list[str] | None = None,
        overrides: dict[str, dict] | None = None,
        rules_path: str | None = None,
        prefer: tuple[str, ...] = ("cboe", "yfinance"),
        fetch_realized: bool = False,
        fetch_events: bool = False,
    ) -> AdvisorResult:
        syms = symbols if symbols is not None else context.symbols()
        result: OptionAdvisoryResult = option_service.run_advisor(
            syms,
            rules_path=rules_path,
            aum=context.aum,
            holdings=context.holdings,
            sectors=context.sectors,
            regime_label=context.regime_label,
            regime_confidence=context.regime_confidence,
            crisis_flag=context.crisis_flag,
            overrides=overrides,
            prefer=prefer,
            fetch_realized=fetch_realized,
            fetch_events=fetch_events,
            as_of=context.as_of or None,
        )
        suggestions = [suggestion_from_idea(i, result.data_mode) for i in result.ideas]
        return AdvisorResult(
            advisor="option",
            as_of=result.as_of,
            suggestions=suggestions,
            data_mode=result.data_mode,
            warnings=list(result.warnings),
            config_version=result.config_version,
            meta={"universe_scanned": result.universe_scanned},
        )
