"""Trade Ideas advisor — general (non-option) regime-aligned sleeve tilts.

Reuses the existing regime→policy mapping (`suggest.quadrant_policy`): given the
current regime label, surface the target asset-class mix + vol multiplier as a
**read-only advisory tilt** (ADR 0006 — guidance, not an allocation directive,
not auto-execution). Rule-based and explainable; no optimiser, no ML.

This is the 4th advisor and completes the "all advisors under one UI" bar item;
it slots in via the registry with no advisor-specific UI.
"""

from __future__ import annotations

from ..contracts import (
    LABEL_INFO,
    LABEL_WATCHLIST,
    TIER_RESEARCH,
    AdvisorContext,
    AdvisorResult,
    IdeaAssessment,
    Suggestion,
)


def _info(as_of: str, why: str) -> AdvisorResult:
    return AdvisorResult(
        advisor="ideas", as_of=as_of, data_mode="regime",
        suggestions=[Suggestion(
            advisor="ideas", suggestion_id="ideas:no_regime", as_of=as_of,
            title="Set a regime for allocation tilts", subject="Portfolio", category="TILT",
            label=LABEL_INFO, decision_tier=TIER_RESEARCH,
            thesis="No regime selected (or unknown).", why_now=why, body_kind="ideas",
        )],
    )


class TradeIdeasAdvisorPlugin:
    """Regime-aligned portfolio-tilt ideas (reuses suggest.quadrant_policy)."""

    key = "ideas"
    title = "Trade Ideas"

    def produce(
        self,
        context: AdvisorContext,
        *,
        policy: dict | None = None,
        policy_path: str | None = None,
    ) -> AdvisorResult:
        as_of = context.as_of
        regime = (context.regime_label or "").strip()
        if policy is None:
            from market_helper.suggest.quadrant_policy import load_quadrant_policy

            policy = load_quadrant_policy(policy_path)  # path=None → in-code defaults, no IO

        if not regime:
            return _info(as_of, "Pick a regime to see regime-aligned sleeve tilts.")
        if regime not in policy:
            return _info(as_of, f"Regime '{regime}' has no policy entry — choose a known regime.")

        entry = dict(policy[regime])
        targets = dict(entry.get("asset_class_targets", {}))
        vol_mult = entry.get("vol_multiplier")
        notes = str(entry.get("notes", ""))
        tilt_str = ", ".join(f"{k} {v:.0%}" for k, v in targets.items())

        metrics = {"vol_mult": f"{vol_mult:g}" if vol_mult is not None else "—"}
        for k, v in list(targets.items())[:4]:
            metrics[k] = f"{v:.0%}"

        return AdvisorResult(
            advisor="ideas", as_of=as_of, data_mode="regime",
            suggestions=[Suggestion(
                advisor="ideas", suggestion_id=f"ideas:tilt:{regime}", as_of=as_of,
                title=f"Regime-aligned tilt · {regime}", subject="Portfolio", category="TILT",
                label=LABEL_WATCHLIST, decision_tier=TIER_RESEARCH, score=0.55,
                thesis=f"{regime} regime → target sleeve mix: {tilt_str}.",
                why_now=notes or f"Advisory tilt for the {regime} regime.",
                rationale=(
                    f"Vol multiplier {vol_mult}. Read-only guidance, not an allocation directive "
                    "or auto-execution (ADR 0006); compare against your current sleeve weights."
                ),
                headline_metrics=metrics,
                data_mode="regime",
                assessment=IdeaAssessment(confidence="low", actionability="watch",
                                          risk_boundedness="undefined", data_quality="stale"),
                instrument_family="allocation_tilt",
                body_kind="ideas",
                detail={"regime": regime, "asset_class_targets": targets, "vol_multiplier": vol_mult, "notes": notes},
            )],
            meta={"regime": regime},
        )
