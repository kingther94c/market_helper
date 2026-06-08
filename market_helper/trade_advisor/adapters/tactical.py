"""Tactical Trade Ideas advisor → umbrella adapter.

Emits the rule-based tactical idea anchors (from :mod:`market_helper.domain.tactical_ideas`)
as the uniform :class:`~..contracts.Suggestion` shape. Offline + fast: ``produce``
runs only the deterministic signal layer (no network). The **AI synthesis** brief
is opt-in and lives in the cockpit's Tactical tab (via
``tactical_ideas.request_tactical_brief``), mirroring the AI+ pattern — research /
synthesis only, never orders.

These are *independent directional trades* (distinct from the Option Strategy
module's base-position overlays), so every anchor is advisory and capped at MONITOR.
"""

from __future__ import annotations

from market_helper.domain.tactical_ideas import (
    build_tactical_context,
    generate_tactical_ideas,
)

from ..contracts import (
    LABEL_INFO,
    LABEL_WATCHLIST,
    TIER_RESEARCH,
    AdvisorContext,
    AdvisorResult,
    AuditEntry,
    IdeaAssessment,
    Suggestion,
    data_quality_for_mode,
)

_CONF_SCORE = {"High": 0.62, "Medium": 0.50, "Low": 0.40}
_CONF_AXIS = {"High": "high", "Medium": "medium", "Low": "low"}
_TACTICAL_FAMILY = {
    "SHORT_USD": "fx", "STEEPENER": "rates_curve", "SECTOR_ROTATION": "equity_rotation",
    "CM_RV": "commodity_rv", "SHORT_VIX": "volatility", "RISK_OFF": "volatility", "TREND": "equity_beta",
}


def _tactical_assessment(idea) -> IdeaAssessment:
    """Honest multi-axis read of a rule anchor — research-tier, so never act_now."""
    expr = (idea.expression or "").lower()
    bounded = "capped" if ("spread" in expr or "call spread" in expr or "put spread" in expr) else "undefined"
    return IdeaAssessment(
        confidence=_CONF_AXIS.get(idea.confidence, "low"),
        actionability="watch",   # a research hypothesis is studied, not acted on, from the rule layer
        risk_boundedness=bounded,
        data_quality=data_quality_for_mode(idea.data_mode),
        notes={
            "confidence": idea.why_now,
            "risk_boundedness": "defined-risk expression" if bounded == "capped" else "directional macro — size the loss yourself",
            "actionability": "T4 research hypothesis — pressure-test before acting",
        },
    )


class TacticalIdeasPlugin:
    """Umbrella advisor for independent short-term macro/market trade ideas."""

    key = "tactical"
    title = "Tactical Trade Ideas"

    def produce(
        self,
        context: AdvisorContext,
        *,
        regime_path=None,
        prediction=None,
        trending=None,
    ) -> AdvisorResult:
        as_of = context.as_of
        try:
            ctx = build_tactical_context(regime_path=regime_path, prediction=prediction, trending=trending)
        except Exception as exc:  # noqa: BLE001 — never crash the umbrella run
            return AdvisorResult(
                advisor=self.key, as_of=as_of, data_mode="regime",
                warnings=[f"tactical context error: {type(exc).__name__}: {str(exc)[:120]}"],
                suggestions=[Suggestion(
                    advisor=self.key, suggestion_id="tactical:error", as_of=as_of,
                    title="Tactical ideas unavailable", subject="Macro", category="TACTICAL",
                    label=LABEL_INFO, decision_tier=TIER_RESEARCH,
                    thesis="Could not assemble the tactical context.",
                    why_now="Run the regime report to populate the snapshot.", body_kind="tactical",
                )],
            )

        ideas = generate_tactical_ideas(ctx)
        data_mode = "regime+model" if (ctx.expert_available or ctx.trend_available) else "regime"
        if not ideas:
            return AdvisorResult(
                advisor=self.key, as_of=as_of, data_mode=data_mode,
                suggestions=[Suggestion(
                    advisor=self.key, suggestion_id="tactical:none", as_of=as_of,
                    title="No tactical signals fired", subject="Macro", category="TACTICAL",
                    label=LABEL_INFO, decision_tier=TIER_RESEARCH,
                    thesis="The current regime/context did not trigger a grounded tactical anchor.",
                    why_now=f"regime={ctx.regime or '?'}; sources={', '.join(ctx.sources) or 'regime defaults'}.",
                    body_kind="tactical",
                )],
                meta={"sources": ctx.sources},
            )

        return AdvisorResult(
            advisor=self.key, as_of=as_of, data_mode=data_mode,
            suggestions=[self._to_suggestion(idea, ctx, as_of) for idea in ideas],
            meta={"sources": ctx.sources, "n_ideas": len(ideas)},
        )

    def _to_suggestion(self, idea, ctx, as_of: str) -> Suggestion:
        audit = [AuditEntry("signal", True, "info", ev) for ev in idea.evidence]
        audit.append(AuditEntry("invalidation", True, "info", idea.invalidation))
        return Suggestion(
            advisor=self.key,
            suggestion_id=f"tactical:{idea.theme}",
            as_of=as_of,
            title=idea.title,
            subject=idea.theme.replace("_", " ").title(),
            category="TACTICAL",
            label=LABEL_WATCHLIST,  # research hypotheses (T4) never exceed WATCHLIST
            decision_tier=TIER_RESEARCH,
            score=_CONF_SCORE.get(idea.confidence, 0.45),
            thesis=idea.thesis,
            why_now=idea.why_now,
            rationale=f"{idea.expression}  ·  Edge: {idea.edge or '—'}",
            headline_metrics={
                "stance": idea.direction,
                "conf": idea.confidence,
                "basis": idea.data_mode,
            },
            audit=audit,
            data_mode=idea.data_mode,
            assessment=_tactical_assessment(idea),
            instrument_family=_TACTICAL_FAMILY.get(idea.theme, "macro"),
            evidence=list(idea.evidence),
            risk=idea.regime_kill or idea.invalidation,
            invalidation=idea.invalidation,
            portfolio_interaction=idea.overlap,
            journal_note=f"Edge: {idea.edge or '—'}. Confirm: {idea.confirm or '—'}.",
            body_kind="tactical",
            detail=idea.as_detail(),
        )
