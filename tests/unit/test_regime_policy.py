from market_helper.regimes.models import RegimeSnapshot
from market_helper.regimes.taxonomy import REGIME_GOLDILOCKS
from market_helper.suggest.regime_policy import DEFAULT_POLICY, resolve_policy


def test_policy_mapping_returns_expected_structure() -> None:
    snapshot = RegimeSnapshot(
        as_of="2026-03-20",
        regime=REGIME_GOLDILOCKS,
        scores={},
        inputs={},
        flags={},
    )
    decision = resolve_policy(snapshot)
    assert decision.regime == REGIME_GOLDILOCKS
    assert decision.vol_multiplier > 0
    assert abs(sum(decision.asset_class_targets.values()) - 1.0) < 1e-9


def test_policy_falls_back_for_unknown_regime() -> None:
    snapshot = RegimeSnapshot(
        as_of="2026-03-20",
        regime="Unknown",
        scores={},
        inputs={},
        flags={},
    )
    decision = resolve_policy(snapshot, policy=DEFAULT_POLICY)
    assert decision.vol_multiplier > 0
    assert "EQ" in decision.asset_class_targets
