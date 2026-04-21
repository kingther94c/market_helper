from __future__ import annotations

import pytest

from market_helper.regimes.axes import (
    QUADRANT_DEFLATIONARY_SLOWDOWN,
    QUADRANT_GOLDILOCKS,
    QUADRANT_REFLATION,
    QUADRANT_STAGFLATION,
)
from market_helper.regimes.methods.legacy_rulebook import (
    LegacyRulebookConfig,
    LegacyRulebookMethod,
    project_to_quadrant,
)
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


def test_project_to_quadrant_all_labels() -> None:
    assert project_to_quadrant(REGIME_GOLDILOCKS, rates_score=0.0) == (
        QUADRANT_GOLDILOCKS,
        False,
    )
    assert project_to_quadrant(REGIME_REFLATION_TIGHTENING, rates_score=0.5) == (
        QUADRANT_REFLATION,
        False,
    )
    assert project_to_quadrant(REGIME_STAGFLATION, rates_score=0.5) == (
        QUADRANT_STAGFLATION,
        False,
    )
    assert project_to_quadrant(REGIME_DEFLATIONARY_SLOWDOWN, rates_score=-0.1) == (
        QUADRANT_DEFLATIONARY_SLOWDOWN,
        False,
    )
    # Recovery splits on rates sign
    assert project_to_quadrant(REGIME_RECOVERY_PIVOT, rates_score=0.0) == (
        QUADRANT_GOLDILOCKS,
        False,
    )
    assert project_to_quadrant(REGIME_RECOVERY_PIVOT, rates_score=0.5) == (
        QUADRANT_REFLATION,
        False,
    )
    # Crises keep their character in the projection AND set the crisis flag.
    assert project_to_quadrant(REGIME_DEFLATIONARY_CRISIS, rates_score=-0.1) == (
        QUADRANT_DEFLATIONARY_SLOWDOWN,
        True,
    )
    assert project_to_quadrant(REGIME_INFLATIONARY_CRISIS, rates_score=0.5) == (
        QUADRANT_STAGFLATION,
        True,
    )


def _stable_bundle() -> RegimeInputBundle:
    # 30 days of flat inputs; should land in a single non-crisis regime.
    n = 30
    dates = [f"2024-01-{day:02d}" for day in range(1, n + 1)]
    return RegimeInputBundle(
        dates=dates,
        vix=[15.0] * n,
        move=[90.0] * n,
        hy_oas=[3.5] * n,
        y2=[4.5] * n,
        y10=[4.2] * n,
        eq_returns=[0.0005] * n,
        fi_returns=[0.0001] * n,
        source_info={"test": "inline"},
    )


def test_legacy_method_emits_projected_results() -> None:
    method = LegacyRulebookMethod(LegacyRulebookConfig())
    results = method.classify(_stable_bundle())
    assert len(results) == 30
    assert all(r.method_name == "legacy_rulebook" for r in results)
    # Every projected quadrant is one of the 2D labels.
    assert {r.quadrant.quadrant for r in results} <= {
        QUADRANT_GOLDILOCKS,
        QUADRANT_REFLATION,
        QUADRANT_STAGFLATION,
        QUADRANT_DEFLATIONARY_SLOWDOWN,
    }
    # native_label should be one of the 7 legacy regimes.
    assert results[-1].native_label in {
        REGIME_GOLDILOCKS,
        REGIME_REFLATION_TIGHTENING,
        REGIME_STAGFLATION,
        REGIME_DEFLATIONARY_SLOWDOWN,
        REGIME_RECOVERY_PIVOT,
        REGIME_DEFLATIONARY_CRISIS,
        REGIME_INFLATIONARY_CRISIS,
    }


def test_legacy_method_flags_crisis_when_stressed() -> None:
    # Spike VIX + widening HY_OAS to push the stress factor above the enter
    # threshold for the last 10 days.
    n = 30
    dates = [f"2024-02-{day:02d}" for day in range(1, n + 1)]
    vix = [15.0] * 20 + [55.0] * 10
    move = [90.0] * 20 + [180.0] * 10
    hy_oas = [3.5] * 20 + [8.5] * 10
    bundle = RegimeInputBundle(
        dates=dates,
        vix=vix,
        move=move,
        hy_oas=hy_oas,
        y2=[4.5] * n,
        y10=[4.2] * n,
        eq_returns=[-0.02] * 20 + [-0.04] * 10,
        fi_returns=[0.0] * n,
        source_info={"test": "inline"},
    )
    method = LegacyRulebookMethod(LegacyRulebookConfig())
    results = method.classify(bundle)
    # At least some late-period snapshot must carry the crisis flag.
    assert any(r.quadrant.crisis_flag for r in results[-10:])
