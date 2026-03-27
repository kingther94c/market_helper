from __future__ import annotations

from dataclasses import dataclass

from .models import FactorSnapshot, RegimeSnapshot
from .taxonomy import (
    REGIME_DEFLATIONARY_CRISIS,
    REGIME_DEFLATIONARY_SLOWDOWN,
    REGIME_GOLDILOCKS,
    REGIME_INFLATIONARY_CRISIS,
    REGIME_RECOVERY_PIVOT,
    REGIME_REFLATION_TIGHTENING,
    REGIME_STAGFLATION,
)


@dataclass(frozen=True)
class RulebookConfig:
    """Threshold and persistence controls for deterministic v1 regime classification."""

    crisis_enter_threshold: float = 0.75
    crisis_exit_threshold: float = 0.60
    inflationary_rates_threshold: float = 0.20
    recovery_window_days: int = 20
    min_non_crisis_days: int = 5


def classify_regimes(
    factor_snapshots: list[FactorSnapshot],
    config: RulebookConfig | None = None,
) -> list[RegimeSnapshot]:
    """Classify factor snapshots into a single mutually-exclusive regime time series."""
    cfg = config or RulebookConfig()

    in_crisis = False
    current_regime: str | None = None
    regime_duration = 0
    days_since_crisis_exit = cfg.recovery_window_days + 1

    outputs: list[RegimeSnapshot] = []
    for snapshot in factor_snapshots:
        proposed = _propose_regime(
            snapshot=snapshot,
            cfg=cfg,
            in_crisis=in_crisis,
            days_since_crisis_exit=days_since_crisis_exit,
        )

        stress = snapshot.stress
        entering_crisis = (not in_crisis) and stress >= cfg.crisis_enter_threshold
        leaving_crisis = in_crisis and stress < cfg.crisis_exit_threshold

        if entering_crisis:
            in_crisis = True
            proposed = _crisis_subtype(snapshot, cfg)
            regime_duration = 0
        elif leaving_crisis:
            in_crisis = False
            days_since_crisis_exit = 0
            proposed = REGIME_RECOVERY_PIVOT

        if current_regime is None:
            current_regime = proposed
            regime_duration = 1
        elif proposed == current_regime:
            regime_duration += 1
        elif in_crisis or proposed in {REGIME_DEFLATIONARY_CRISIS, REGIME_INFLATIONARY_CRISIS}:
            current_regime = proposed
            regime_duration = 1
        else:
            if regime_duration >= cfg.min_non_crisis_days:
                current_regime = proposed
                regime_duration = 1
            else:
                regime_duration += 1

        if not in_crisis:
            days_since_crisis_exit += 1

        flags = {
            "in_crisis": in_crisis,
            "crisis_override": in_crisis,
            "recovery_window": days_since_crisis_exit <= cfg.recovery_window_days,
        }

        outputs.append(
            RegimeSnapshot(
                as_of=snapshot.as_of,
                regime=current_regime,
                scores={
                    "VOL": snapshot.vol,
                    "CREDIT": snapshot.credit,
                    "RATES": snapshot.rates,
                    "GROWTH": snapshot.growth,
                    "TREND": snapshot.trend,
                    "STRESS": snapshot.stress,
                },
                inputs=snapshot.inputs,
                flags=flags,
                diagnostics={
                    "proposed_regime": proposed,
                    "regime_duration": float(regime_duration),
                    "days_since_crisis_exit": float(days_since_crisis_exit),
                },
            )
        )
    return outputs


def _propose_regime(
    *,
    snapshot: FactorSnapshot,
    cfg: RulebookConfig,
    in_crisis: bool,
    days_since_crisis_exit: int,
) -> str:
    if in_crisis:
        return _crisis_subtype(snapshot, cfg)

    if snapshot.stress >= cfg.crisis_enter_threshold:
        return _crisis_subtype(snapshot, cfg)

    if days_since_crisis_exit <= cfg.recovery_window_days and snapshot.growth > -0.2 and snapshot.trend > -0.4:
        return REGIME_RECOVERY_PIVOT

    if snapshot.growth >= 0.35 and snapshot.rates > 0.20:
        return REGIME_REFLATION_TIGHTENING
    if snapshot.growth >= 0.35 and snapshot.rates <= 0.20 and snapshot.vol < 0.60 and snapshot.credit < 0.60:
        return REGIME_GOLDILOCKS
    if snapshot.growth < 0 and snapshot.rates > 0.20:
        return REGIME_STAGFLATION
    return REGIME_DEFLATIONARY_SLOWDOWN


def _crisis_subtype(snapshot: FactorSnapshot, cfg: RulebookConfig) -> str:
    if snapshot.rates >= cfg.inflationary_rates_threshold:
        return REGIME_INFLATIONARY_CRISIS
    return REGIME_DEFLATIONARY_CRISIS
