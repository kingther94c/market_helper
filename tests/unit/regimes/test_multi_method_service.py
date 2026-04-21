from __future__ import annotations

import json

from market_helper.regimes.axes import (
    QUADRANT_DEFLATIONARY_SLOWDOWN,
    QUADRANT_GOLDILOCKS,
    QUADRANT_REFLATION,
    QUADRANT_STAGFLATION,
)
from market_helper.regimes.models import MultiMethodRegimeSnapshot
from market_helper.regimes.multi_method_service import (
    MultiMethodConfig,
    run_multi_method,
    snapshots_from_json,
    snapshots_to_json,
)
from market_helper.regimes.sources import RegimeInputBundle


def _stable_bundle(n: int = 30) -> RegimeInputBundle:
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


def test_orchestrator_legacy_only_produces_snapshots() -> None:
    cfg = MultiMethodConfig(enable_macro_rules=False)
    out = run_multi_method(config=cfg, market_bundle=_stable_bundle())
    assert len(out) == 30
    for snap in out:
        assert set(snap.per_method.keys()) == {"legacy_rulebook"}
        assert snap.ensemble.quadrant in {
            QUADRANT_GOLDILOCKS,
            QUADRANT_REFLATION,
            QUADRANT_STAGFLATION,
            QUADRANT_DEFLATIONARY_SLOWDOWN,
        }
    manifest = out[0].source_info["manifest"]
    assert manifest["methods"]["legacy_rulebook"]["status"] == "ok"
    assert "macro_rules" not in manifest["methods"]


def test_orchestrator_skips_macro_rules_when_inputs_missing() -> None:
    cfg = MultiMethodConfig()  # both enabled by default
    out = run_multi_method(config=cfg, market_bundle=_stable_bundle(5))
    assert out
    manifest = out[0].source_info["manifest"]
    assert manifest["methods"]["macro_rules"]["status"] == "skipped"
    assert manifest["methods"]["legacy_rulebook"]["status"] == "ok"


def test_orchestrator_returns_empty_when_all_methods_disabled() -> None:
    cfg = MultiMethodConfig(
        enable_macro_rules=False, enable_legacy_rulebook=False
    )
    assert run_multi_method(config=cfg) == []


def test_orchestrator_returns_empty_when_no_inputs_supplied() -> None:
    assert run_multi_method() == []


def test_snapshot_roundtrip_json() -> None:
    out = run_multi_method(
        config=MultiMethodConfig(enable_macro_rules=False),
        market_bundle=_stable_bundle(5),
    )
    assert out
    payload = snapshots_to_json(out)
    dumped = json.dumps(payload)  # must be JSON-serializable
    restored = snapshots_from_json(json.loads(dumped))
    assert len(restored) == len(out)
    for original, recovered in zip(out, restored):
        assert isinstance(recovered, MultiMethodRegimeSnapshot)
        assert recovered.as_of == original.as_of
        assert recovered.ensemble.quadrant == original.ensemble.quadrant
        assert set(recovered.per_method.keys()) == set(original.per_method.keys())
        assert recovered.version == original.version
