from market_helper.regimes.models import FactorSnapshot
from market_helper.regimes.rulebook import RulebookConfig, classify_regimes
from market_helper.regimes.taxonomy import (
    REGIME_DEFLATIONARY_CRISIS,
    REGIME_GOLDILOCKS,
    REGIME_RECOVERY_PIVOT,
)


def _snap(day: int, *, stress: float, rates: float, growth: float = 0.4, trend: float = 0.4) -> FactorSnapshot:
    return FactorSnapshot(
        as_of=f"2026-02-{day:02d}",
        vol=stress,
        credit=stress,
        rates=rates,
        growth=growth,
        trend=trend,
        stress=stress,
        inputs={},
    )


def test_crisis_enter_exit_hysteresis() -> None:
    factors = [
        _snap(1, stress=0.50, rates=-0.1),
        _snap(2, stress=0.80, rates=-0.2),
        _snap(3, stress=0.70, rates=-0.2),
        _snap(4, stress=0.55, rates=-0.1),
        _snap(5, stress=0.45, rates=-0.1),
    ]
    out = classify_regimes(factors, config=RulebookConfig(min_non_crisis_days=1))
    assert out[1].regime == REGIME_DEFLATIONARY_CRISIS
    assert out[2].regime == REGIME_DEFLATIONARY_CRISIS
    assert out[3].regime == REGIME_RECOVERY_PIVOT


def test_regime_mutual_exclusivity_and_persistence() -> None:
    factors = [
        _snap(1, stress=0.20, rates=0.0, growth=0.6, trend=0.6),
        _snap(2, stress=0.22, rates=0.0, growth=0.6, trend=0.6),
        _snap(3, stress=0.24, rates=0.0, growth=-0.6, trend=-0.5),
    ]
    out = classify_regimes(factors, config=RulebookConfig(min_non_crisis_days=5))
    assert len({row.regime for row in out[:2]}) == 1
    assert out[0].regime in {REGIME_GOLDILOCKS, REGIME_RECOVERY_PIVOT}
    assert out[2].regime == out[1].regime
