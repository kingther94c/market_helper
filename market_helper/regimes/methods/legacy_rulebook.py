"""Legacy 7-regime rulebook wrapped as a ``RegimeMethod``.

Runs :func:`market_helper.regimes.rulebook.classify_regimes` over the existing
VIX/MOVE/HY_OAS/UST/EQ/FI factor pipeline and projects each label onto the new
2D quadrant plus an orthogonal crisis flag, so the ensemble layer can compare
it directly with the macro_rules method.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Mapping, Sequence

from market_helper.regimes.axes import (
    GrowthInflationAxes,
    QUADRANT_DEFLATIONARY_SLOWDOWN,
    QUADRANT_GOLDILOCKS,
    QUADRANT_REFLATION,
    QUADRANT_STAGFLATION,
    QuadrantSnapshot,
    compute_duration_days,
)
from market_helper.regimes.indicators import compute_factor_snapshots
from market_helper.regimes.models import FactorSnapshot, RegimeSnapshot
from market_helper.regimes.rulebook import RulebookConfig, classify_regimes
from market_helper.regimes.sources import RegimeInputBundle
from market_helper.regimes.taxonomy import (
    REGIME_DEFLATIONARY_CRISIS,
    REGIME_DEFLATIONARY_SLOWDOWN,
    REGIME_GOLDILOCKS,
    REGIME_INFLATIONARY_CRISIS,
    REGIME_RECOVERY_PIVOT,
    REGIME_REFLATION_TIGHTENING,
    REGIME_STAGFLATION,
)
from market_helper.regimes.methods.base import MethodResult


# Crisis regimes are reported with crisis_flag=True and a projected quadrant
# consistent with their inflation character. See the plan for the full mapping.
_CRISIS_LABELS = {REGIME_DEFLATIONARY_CRISIS, REGIME_INFLATIONARY_CRISIS}


def project_to_quadrant(
    regime_label: str,
    rates_score: float,
    *,
    recovery_rates_threshold: float = 0.20,
) -> tuple[str, bool]:
    """Return (quadrant, crisis_flag) for a legacy 7-regime label."""
    if regime_label == REGIME_GOLDILOCKS:
        return QUADRANT_GOLDILOCKS, False
    if regime_label == REGIME_REFLATION_TIGHTENING:
        return QUADRANT_REFLATION, False
    if regime_label == REGIME_STAGFLATION:
        return QUADRANT_STAGFLATION, False
    if regime_label == REGIME_DEFLATIONARY_SLOWDOWN:
        return QUADRANT_DEFLATIONARY_SLOWDOWN, False
    if regime_label == REGIME_RECOVERY_PIVOT:
        if rates_score > recovery_rates_threshold:
            return QUADRANT_REFLATION, False
        return QUADRANT_GOLDILOCKS, False
    if regime_label == REGIME_DEFLATIONARY_CRISIS:
        return QUADRANT_DEFLATIONARY_SLOWDOWN, True
    if regime_label == REGIME_INFLATIONARY_CRISIS:
        return QUADRANT_STAGFLATION, True
    # Unknown label — be conservative.
    return QUADRANT_DEFLATIONARY_SLOWDOWN, False


def _crisis_intensity(stress: float, enter_threshold: float) -> float:
    """Linear ramp from 0 at ``enter_threshold`` to 1 at stress=1.0."""
    if stress <= enter_threshold:
        return 0.0
    if enter_threshold >= 1.0:
        return 1.0
    return max(0.0, min(1.0, (stress - enter_threshold) / (1.0 - enter_threshold)))


@dataclass(frozen=True)
class LegacyRulebookConfig:
    stress_weight_vol: float = 0.55
    stress_weight_credit: float = 0.45
    rulebook: RulebookConfig = RulebookConfig()


class LegacyRulebookMethod:
    """v1 legacy 7-regime rulebook, wrapped to emit 2D quadrants."""

    name = "legacy_rulebook"

    def __init__(self, config: LegacyRulebookConfig | None = None) -> None:
        self.config = config or LegacyRulebookConfig()

    def _factor_snapshots(self, bundle: RegimeInputBundle) -> List[FactorSnapshot]:
        return compute_factor_snapshots(
            dates=list(bundle.dates),
            vix=list(bundle.vix),
            move=list(bundle.move),
            hy_oas=list(bundle.hy_oas),
            y2=list(bundle.y2),
            y10=list(bundle.y10),
            eq_returns=list(bundle.eq_returns),
            fi_returns=list(bundle.fi_returns),
            stress_weight_vol=self.config.stress_weight_vol,
            stress_weight_credit=self.config.stress_weight_credit,
        )

    def _result_from_pair(
        self,
        factor: FactorSnapshot,
        regime: RegimeSnapshot,
        duration: int,
    ) -> MethodResult:
        quadrant_label, crisis = project_to_quadrant(
            regime.regime,
            rates_score=factor.rates,
            recovery_rates_threshold=self.config.rulebook.inflationary_rates_threshold,
        )
        intensity = (
            _crisis_intensity(factor.stress, self.config.rulebook.crisis_enter_threshold)
            if crisis
            else 0.0
        )
        axes = GrowthInflationAxes(
            as_of=factor.as_of,
            growth_score=float(factor.growth),
            inflation_score=float(factor.rates),
            growth_drivers={
                "growth_factor": float(factor.growth),
                "trend_factor": float(factor.trend),
            },
            inflation_drivers={"rates_factor": float(factor.rates)},
            confidence=min(
                1.0,
                0.5 * (abs(float(factor.growth)) + abs(float(factor.rates))),
            ),
        )
        quadrant = QuadrantSnapshot(
            as_of=factor.as_of,
            quadrant=quadrant_label,
            axes=axes,
            crisis_flag=bool(crisis),
            crisis_intensity=float(intensity),
            duration_days=int(duration),
            diagnostics={
                "legacy_regime": regime.regime,
                "stress": float(factor.stress),
                "vol": float(factor.vol),
                "credit": float(factor.credit),
            },
        )
        return MethodResult(
            as_of=factor.as_of,
            method_name=self.name,
            quadrant=quadrant,
            native_label=regime.regime,
            native_detail={
                "flags": dict(regime.flags),
                "scores": dict(regime.scores),
                "diagnostics": dict(regime.diagnostics or {}),
            },
        )

    def classify(self, bundle: RegimeInputBundle) -> List[MethodResult]:
        factors = self._factor_snapshots(bundle)
        regimes = classify_regimes(factors, self.config.rulebook)
        if len(factors) != len(regimes):
            raise RuntimeError(
                "classify_regimes must return one snapshot per factor snapshot"
            )
        # Duration on the projected quadrant (not the native label) so the
        # ensemble can reason about quadrant persistence across methods.
        projected = [
            project_to_quadrant(
                r.regime,
                rates_score=f.rates,
                recovery_rates_threshold=self.config.rulebook.inflationary_rates_threshold,
            )[0]
            for f, r in zip(factors, regimes)
        ]
        durations = compute_duration_days(projected)
        return [
            self._result_from_pair(f, r, d)
            for f, r, d in zip(factors, regimes, durations)
        ]


__all__ = [
    "LegacyRulebookConfig",
    "LegacyRulebookMethod",
    "project_to_quadrant",
]
