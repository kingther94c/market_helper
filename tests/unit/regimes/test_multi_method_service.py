from __future__ import annotations

import json

import pandas as pd

from market_helper.data_sources.fred.macro_panel import SeriesSpec
from market_helper.regimes.axes import (
    QUADRANT_DEFLATIONARY_SLOWDOWN,
    QUADRANT_GOLDILOCKS,
    QUADRANT_REFLATION,
    QUADRANT_STAGFLATION,
)
from market_helper.regimes.methods.market_regime import (
    MarketRegimeConfig,
    MarketSignalSpec,
)
from market_helper.regimes.models import MultiMethodRegimeSnapshot
from market_helper.regimes.multi_method_service import (
    MultiMethodConfig,
    run_multi_method,
    snapshots_from_json,
    snapshots_to_json,
)


def _macro_panel(n: int = 30) -> pd.DataFrame:
    dates = pd.bdate_range("2024-01-01", periods=n)
    return pd.DataFrame({"date": dates, "G": [1.0] * n, "I": [-1.0] * n})


def _macro_specs() -> list[SeriesSpec]:
    return [
        SeriesSpec(series_id="G", axis="growth", transform="level", bucket="fast"),
        SeriesSpec(series_id="I", axis="inflation", transform="level", bucket="fast"),
    ]


def _market_panel(n: int = 30) -> pd.DataFrame:
    dates = pd.bdate_range("2024-01-01", periods=n)
    return pd.DataFrame(
        {
            "date": dates,
            "SPY": [100.0 + idx for idx in range(n)],
            "USO": [100.0 - idx for idx in range(n)],
            "VIX": [20.0] * n,
        }
    )


def _market_config() -> MarketRegimeConfig:
    return MarketRegimeConfig(
        signals=[
            MarketSignalSpec(
                name="spy_raw",
                axis="growth",
                symbol="SPY",
                transform="raw_sign",
                lookback_days=1,
            ),
            MarketSignalSpec(
                name="oil_raw",
                axis="inflation",
                symbol="USO",
                transform="raw_sign",
                lookback_days=1,
            ),
            MarketSignalSpec(
                name="vix_raw",
                axis="risk",
                symbol="VIX",
                transform="raw_sign",
                lookback_days=1,
            ),
        ],
        min_consecutive_days=1,
        risk_min_consecutive_days=1,
    )


def test_orchestrator_macro_only_produces_snapshots() -> None:
    cfg = MultiMethodConfig(enable_market_regime=False)
    out = run_multi_method(
        config=cfg,
        macro_panel=_macro_panel(),
        macro_specs=_macro_specs(),
    )
    assert len(out) == 30
    for snap in out:
        assert set(snap.per_method.keys()) == {"macro_regime"}
        assert snap.ensemble.quadrant in {
            QUADRANT_GOLDILOCKS,
            QUADRANT_REFLATION,
            QUADRANT_STAGFLATION,
            QUADRANT_DEFLATIONARY_SLOWDOWN,
        }
    manifest = out[0].source_info["manifest"]
    assert manifest["methods"]["macro_regime"]["status"] == "ok"
    assert "market_regime" not in manifest["methods"]


def test_orchestrator_skips_market_regime_when_inputs_missing() -> None:
    cfg = MultiMethodConfig()
    out = run_multi_method(
        config=cfg,
        macro_panel=_macro_panel(5),
        macro_specs=_macro_specs(),
    )
    assert out
    manifest = out[0].source_info["manifest"]
    assert manifest["methods"]["macro_regime"]["status"] == "ok"
    assert manifest["methods"]["market_regime"]["status"] == "skipped"


def test_orchestrator_returns_empty_when_all_methods_disabled() -> None:
    cfg = MultiMethodConfig(
        enable_macro_regime=False, enable_market_regime=False
    )
    assert run_multi_method(config=cfg) == []


def test_orchestrator_returns_empty_when_no_inputs_supplied() -> None:
    assert run_multi_method() == []


def test_snapshot_roundtrip_json() -> None:
    out = run_multi_method(
        config=MultiMethodConfig(market_regime=_market_config()),
        macro_panel=_macro_panel(5),
        macro_specs=_macro_specs(),
        market_panel=_market_panel(5),
    )
    assert out
    payload = snapshots_to_json(out)
    dumped = json.dumps(payload)
    restored = snapshots_from_json(json.loads(dumped))
    assert len(restored) == len(out)
    for original, recovered in zip(out, restored):
        assert isinstance(recovered, MultiMethodRegimeSnapshot)
        assert recovered.as_of == original.as_of
        assert recovered.ensemble.quadrant == original.ensemble.quadrant
        assert set(recovered.per_method.keys()) == set(original.per_method.keys())
        assert recovered.version == original.version
