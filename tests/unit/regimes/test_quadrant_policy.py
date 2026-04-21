from __future__ import annotations

from pathlib import Path

import pytest

from market_helper.regimes.axes import (
    GrowthInflationAxes,
    QUADRANT_DEFLATIONARY_SLOWDOWN,
    QUADRANT_GOLDILOCKS,
    QUADRANT_REFLATION,
    QUADRANT_STAGFLATION,
    QuadrantSnapshot,
)
from market_helper.suggest.quadrant_policy import (
    CrisisOverlay,
    DEFAULT_CRISIS_OVERLAY,
    DEFAULT_QUADRANT_POLICY,
    load_crisis_overlay,
    load_quadrant_policy,
    resolve_quadrant_policy,
)


def _snapshot(
    quadrant: str,
    *,
    crisis_flag: bool = False,
    crisis_intensity: float = 0.0,
) -> QuadrantSnapshot:
    axes = GrowthInflationAxes(
        as_of="2024-06-03",
        growth_score=1.0,
        inflation_score=-1.0,
    )
    return QuadrantSnapshot(
        as_of="2024-06-03",
        quadrant=quadrant,
        axes=axes,
        crisis_flag=crisis_flag,
        crisis_intensity=crisis_intensity,
        duration_days=1,
    )


def test_default_policy_covers_all_quadrants() -> None:
    for label in (
        QUADRANT_GOLDILOCKS,
        QUADRANT_REFLATION,
        QUADRANT_STAGFLATION,
        QUADRANT_DEFLATIONARY_SLOWDOWN,
    ):
        entry = DEFAULT_QUADRANT_POLICY[label]
        targets = entry["asset_class_targets"]
        assert pytest.approx(sum(targets.values()), abs=1e-9) == 1.0


def test_resolve_quadrant_policy_returns_base_when_no_crisis() -> None:
    snap = _snapshot(QUADRANT_GOLDILOCKS)
    decision = resolve_quadrant_policy(snap)
    assert decision.regime == QUADRANT_GOLDILOCKS
    assert decision.vol_multiplier == pytest.approx(1.05)
    assert decision.asset_class_targets == DEFAULT_QUADRANT_POLICY[
        QUADRANT_GOLDILOCKS
    ]["asset_class_targets"]
    assert "Crisis overlay" not in decision.notes


def test_resolve_quadrant_policy_falls_back_to_slowdown_on_unknown() -> None:
    snap = _snapshot("Unknown")
    decision = resolve_quadrant_policy(snap)
    assert decision.vol_multiplier == pytest.approx(
        DEFAULT_QUADRANT_POLICY[QUADRANT_DEFLATIONARY_SLOWDOWN]["vol_multiplier"]
    )


def test_resolve_quadrant_policy_applies_crisis_overlay() -> None:
    snap = _snapshot(
        QUADRANT_REFLATION, crisis_flag=True, crisis_intensity=1.0
    )
    decision = resolve_quadrant_policy(snap)
    base = DEFAULT_QUADRANT_POLICY[QUADRANT_REFLATION]
    expected_vol = base["vol_multiplier"] * (
        1 - DEFAULT_CRISIS_OVERLAY.vol_multiplier_reduction
    )
    assert decision.vol_multiplier == pytest.approx(expected_vol)
    base_eq = base["asset_class_targets"]["EQ"]
    taken = min(base_eq, DEFAULT_CRISIS_OVERLAY.equity_shift_pct)
    assert decision.asset_class_targets["EQ"] == pytest.approx(base_eq - taken)
    expected_cash = (
        base["asset_class_targets"]["CASH"] + taken * 0.50
    )
    expected_gold = (
        base["asset_class_targets"]["GOLD"] + taken * 0.30
    )
    expected_fi = base["asset_class_targets"]["FI"] + taken * 0.20
    assert decision.asset_class_targets["CASH"] == pytest.approx(expected_cash)
    assert decision.asset_class_targets["GOLD"] == pytest.approx(expected_gold)
    assert decision.asset_class_targets["FI"] == pytest.approx(expected_fi)
    assert "Crisis overlay applied" in decision.notes
    # Weight-preservation: the overlay should not mint or destroy weight.
    assert sum(decision.asset_class_targets.values()) == pytest.approx(1.0)


def test_resolve_quadrant_policy_partial_intensity_scales_linearly() -> None:
    snap = _snapshot(
        QUADRANT_STAGFLATION, crisis_flag=True, crisis_intensity=0.5
    )
    decision = resolve_quadrant_policy(snap)
    base = DEFAULT_QUADRANT_POLICY[QUADRANT_STAGFLATION]
    expected_vol = base["vol_multiplier"] * (
        1 - DEFAULT_CRISIS_OVERLAY.vol_multiplier_reduction * 0.5
    )
    assert decision.vol_multiplier == pytest.approx(expected_vol)
    taken = min(
        base["asset_class_targets"]["EQ"],
        DEFAULT_CRISIS_OVERLAY.equity_shift_pct * 0.5,
    )
    assert decision.asset_class_targets["EQ"] == pytest.approx(
        base["asset_class_targets"]["EQ"] - taken
    )


def test_resolve_quadrant_policy_crisis_flag_with_zero_intensity_is_noop() -> None:
    snap = _snapshot(
        QUADRANT_GOLDILOCKS, crisis_flag=True, crisis_intensity=0.0
    )
    decision = resolve_quadrant_policy(snap)
    base = DEFAULT_QUADRANT_POLICY[QUADRANT_GOLDILOCKS]
    assert decision.vol_multiplier == pytest.approx(base["vol_multiplier"])
    assert decision.asset_class_targets == base["asset_class_targets"]


def test_load_quadrant_policy_merges_yaml_overrides(tmp_path: Path) -> None:
    yml = tmp_path / "quadrant_policy.yml"
    yml.write_text(
        """
policy:
  Goldilocks:
    vol_multiplier: 1.25
    asset_class_targets: {EQ: 0.9, FI: 0.05, CASH: 0.05}
    notes: "override"
""",
        encoding="utf-8",
    )
    merged = load_quadrant_policy(yml)
    assert merged[QUADRANT_GOLDILOCKS]["vol_multiplier"] == pytest.approx(1.25)
    # Other quadrants preserved.
    assert merged[QUADRANT_STAGFLATION] == DEFAULT_QUADRANT_POLICY[
        QUADRANT_STAGFLATION
    ]


def test_load_crisis_overlay_parses_dict_allocation(tmp_path: Path) -> None:
    yml = tmp_path / "overlay.yml"
    yml.write_text(
        """
crisis_overlay:
  vol_multiplier_reduction: 0.4
  equity_shift_pct: 0.15
  shift_allocation:
    CASH: 0.6
    GOLD: 0.25
    FI: 0.15
""",
        encoding="utf-8",
    )
    ov = load_crisis_overlay(yml)
    assert ov.vol_multiplier_reduction == pytest.approx(0.4)
    assert ov.equity_shift_pct == pytest.approx(0.15)
    assert dict(ov.shift_allocation) == {
        "CASH": 0.6,
        "GOLD": 0.25,
        "FI": 0.15,
    }


def test_load_crisis_overlay_defaults_on_missing_file() -> None:
    assert load_crisis_overlay(None) is DEFAULT_CRISIS_OVERLAY


def test_resolve_quadrant_policy_custom_overlay_overrides_defaults() -> None:
    snap = _snapshot(
        QUADRANT_REFLATION, crisis_flag=True, crisis_intensity=1.0
    )
    overlay = CrisisOverlay(
        vol_multiplier_reduction=0.5,
        equity_shift_pct=0.2,
        shift_allocation=(("CASH", 1.0),),
    )
    decision = resolve_quadrant_policy(snap, overlay=overlay)
    base = DEFAULT_QUADRANT_POLICY[QUADRANT_REFLATION]
    assert decision.vol_multiplier == pytest.approx(
        base["vol_multiplier"] * 0.5
    )
    assert decision.asset_class_targets["EQ"] == pytest.approx(
        base["asset_class_targets"]["EQ"] - 0.2
    )
    assert decision.asset_class_targets["CASH"] == pytest.approx(
        base["asset_class_targets"]["CASH"] + 0.2
    )
