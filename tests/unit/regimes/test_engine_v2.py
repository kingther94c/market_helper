from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import yaml

from market_helper.data_sources.fred.macro_panel import SeriesSpec
from market_helper.regimes.engine_v2 import (
    LayerConfig,
    RegimeEngineConfig,
    load_regime_engine_config,
    run_regime_engine_v2,
)
from market_helper.regimes.methods.market_regime import MarketRegimeConfig, MarketSignalSpec
from market_helper.regimes.ml import ConfiguredRegimeModelSelector
from market_helper.cli.main import main


def _macro_panel(values: tuple[float, float] = (1.0, -1.0), n: int = 12) -> pd.DataFrame:
    dates = pd.bdate_range("2026-01-01", periods=n)
    return pd.DataFrame({"date": dates, "G": [values[0]] * n, "I": [values[1]] * n})


def _macro_specs() -> list[SeriesSpec]:
    return [
        SeriesSpec(series_id="G", axis="growth", transform="level", bucket="fast"),
        SeriesSpec(series_id="I", axis="inflation", transform="level", bucket="fast"),
    ]


def _market_panel(
    *,
    growth_up: bool = True,
    inflation_up: bool = True,
    risk_high: bool = False,
    n: int = 90,
) -> pd.DataFrame:
    dates = pd.bdate_range("2026-01-01", periods=n)
    spy = [100.0 + idx if growth_up else 100.0 * (0.5 ** idx) for idx in range(n)]
    oil = [100.0 + idx if inflation_up else 100.0 * (0.5 ** idx) for idx in range(n)]
    vix = [15.0] * n
    if risk_high:
        vix[-20:] = [40.0] * 20
    return pd.DataFrame({"date": dates, "SPY": spy, "USO": oil, "VIX": vix})


def _market_config() -> MarketRegimeConfig:
    return MarketRegimeConfig(
        signals=[
            MarketSignalSpec(
                name="spy",
                axis="growth",
                symbol="SPY",
                transform="raw_sign",
                lookback_days=1,
            ),
            MarketSignalSpec(
                name="oil",
                axis="inflation",
                symbol="USO",
                transform="raw_sign",
                lookback_days=1,
            ),
            MarketSignalSpec(
                name="vix",
                axis="risk",
                symbol="VIX",
                transform="level_zscore",
                zscore_window_days=30,
            ),
        ],
        min_consecutive_days=1,
        risk_min_consecutive_days=1,
        risk_enter_threshold=0.5,
    )


def test_risk_overlay_does_not_change_growth_or_inflation_scores() -> None:
    common = {
        "config": RegimeEngineConfig(
            layers={
                "macro_nowcast": LayerConfig(enabled=True, weight_growth=1.0, weight_inflation=1.0),
                "market_implied": LayerConfig(enabled=False),
                "macro_truth_ml": LayerConfig(enabled=False, model_type="svm"),
                "return_truth_ml": LayerConfig(enabled=False, model_type="svm"),
            }
        ),
        "macro_panel": _macro_panel((1.0, 1.0), n=90),
        "macro_specs": _macro_specs(),
        "market_config": _market_config(),
    }
    no_stress = run_regime_engine_v2(market_panel=_market_panel(risk_high=False), **common)[-1]
    stress = run_regime_engine_v2(market_panel=_market_panel(risk_high=True), **common)[-1]

    assert no_stress.final_growth_score == stress.final_growth_score
    assert no_stress.final_inflation_score == stress.final_inflation_score
    assert stress.risk_overlay_on is True
    assert "Stress Overlay" in stress.final_regime


def test_disabled_ml_layers_and_missing_contributors_do_not_break_output() -> None:
    out = run_regime_engine_v2(
        config=RegimeEngineConfig(),
        macro_panel=_macro_panel(),
        macro_specs=_macro_specs(),
        market_panel=_market_panel(inflation_up=False),
        market_config=_market_config(),
    )
    latest = out[-1].to_dict()
    assert latest["version"] == "regime-engine-v2"
    layer_status = {layer["layer_name"]: layer for layer in latest["layer_outputs"]}
    assert layer_status["macro_truth_ml"]["growth_state"] == "Disabled"
    assert layer_status["return_truth_ml"]["inflation_state"] == "Disabled"
    assert latest["ml_macro_growth_score"] is None


def test_enabled_ml_without_model_artifact_is_not_available() -> None:
    cfg = RegimeEngineConfig(
        layers={
            "macro_nowcast": LayerConfig(enabled=True, weight_growth=1.0, weight_inflation=1.0),
            "market_implied": LayerConfig(enabled=False),
            "macro_truth_ml": LayerConfig(enabled=True, model_type="svm", weight_growth=0.0, weight_inflation=0.0),
            "return_truth_ml": LayerConfig(enabled=False, model_type="svm"),
        }
    )
    latest = run_regime_engine_v2(
        config=cfg,
        macro_panel=_macro_panel(),
        macro_specs=_macro_specs(),
    )[-1]
    ml = {layer.layer_name: layer for layer in latest.layer_outputs}["macro_truth_ml"]
    assert ml.enabled is True
    assert ml.available is False
    assert "model_artifact not configured" in ml.diagnostics["reason"]


def test_model_selector_picks_existing_svm_artifact(tmp_path: Path) -> None:
    artifact = tmp_path / "svm.pkl"
    artifact.write_bytes(b"not-loaded-by-selector")

    result = ConfiguredRegimeModelSelector().select_model(
        layer_name="macro_truth_ml",
        config={"model_type": "svm", "model_artifact": str(artifact), "feature_schema": ["SPY"]},
        available_features=("SPY",),
    )

    assert result.available is True
    assert result.selected is not None
    assert result.selected.model_type == "svm"


def test_disagreement_and_confidence_penalty_are_exposed() -> None:
    cfg = RegimeEngineConfig(
        layers={
            "macro_nowcast": LayerConfig(enabled=True, weight_growth=0.5, weight_inflation=0.5),
            "market_implied": LayerConfig(enabled=True, weight_growth=0.5, weight_inflation=0.5),
            "macro_truth_ml": LayerConfig(enabled=False, model_type="svm"),
            "return_truth_ml": LayerConfig(enabled=False, model_type="svm"),
        }
    )
    latest = run_regime_engine_v2(
        config=cfg,
        macro_panel=_macro_panel((1.0, -1.0), n=90),
        macro_specs=_macro_specs(),
        market_panel=_market_panel(growth_up=False, inflation_up=True),
        market_config=_market_config(),
    )[-1]

    assert latest.disagreement_flag is True
    assert "macro_nowcast" in latest.disagreement_summary
    assert latest.confidence in {"Low", "Medium", "High"}
    assert latest.confidence != "High"


def test_neutral_layer_difference_is_not_strong_disagreement() -> None:
    cfg = RegimeEngineConfig(
        layers={
            "macro_nowcast": LayerConfig(enabled=True, weight_growth=0.5, weight_inflation=0.5),
            "market_implied": LayerConfig(enabled=True, weight_growth=0.5, weight_inflation=0.5),
            "macro_truth_ml": LayerConfig(enabled=False, model_type="svm"),
            "return_truth_ml": LayerConfig(enabled=False, model_type="svm"),
        }
    )
    latest = run_regime_engine_v2(
        config=cfg,
        macro_panel=_macro_panel((0.4, 0.0), n=90),
        macro_specs=_macro_specs(),
        market_panel=_market_panel(growth_up=True, inflation_up=True),
        market_config=_market_config(),
    )[-1]

    assert latest.disagreement_flag is False


def test_weights_and_zero_weight_layers_control_final_scores() -> None:
    cfg = RegimeEngineConfig(
        layers={
            "macro_nowcast": LayerConfig(enabled=True, weight_growth=1.0, weight_inflation=1.0),
            "market_implied": LayerConfig(enabled=True, weight_growth=0.0, weight_inflation=0.0),
            "macro_truth_ml": LayerConfig(enabled=False, model_type="svm"),
            "return_truth_ml": LayerConfig(enabled=False, model_type="svm"),
        }
    )
    latest = run_regime_engine_v2(
        config=cfg,
        macro_panel=_macro_panel((1.0, -1.0), n=90),
        macro_specs=_macro_specs(),
        market_panel=_market_panel(growth_up=False, inflation_up=True),
        market_config=_market_config(),
    )[-1]
    assert latest.final_growth_score == latest.macro_growth_score
    assert latest.final_inflation_score == latest.macro_inflation_score


def test_config_loader_accepts_v2_yaml(tmp_path: Path) -> None:
    path = tmp_path / "regime_engine.yml"
    path.write_text(
        yaml.safe_dump(
            {
                "regime_engine": {
                    "version": 2,
                    "layers": {"market_implied": {"enabled": True, "weight_growth": 0.25}},
                }
            }
        ),
        encoding="utf-8",
    )
    cfg = load_regime_engine_config(path)
    assert cfg.version == 2
    assert cfg.layers["market_implied"].weight_growth == 0.25
    assert cfg.layers["macro_truth_ml"].weight_growth == 0.0


def test_cli_regime_detect_v2_writes_schema(tmp_path: Path) -> None:
    macro_panel = tmp_path / "macro_panel.feather"
    fred_config = tmp_path / "fred_series.yml"
    market_panel = tmp_path / "market_panel.feather"
    market_config = tmp_path / "market_regime.yml"
    output = tmp_path / "regime_v2.json"

    _macro_panel(n=30).to_feather(macro_panel)
    fred_config.write_text(
        yaml.safe_dump(
            {
                "series": [
                    {"series_id": "G", "axis": "growth", "transform": "level", "bucket": "fast"},
                    {"series_id": "I", "axis": "inflation", "transform": "level", "bucket": "fast"},
                ]
            }
        ),
        encoding="utf-8",
    )
    _market_panel(n=30).to_feather(market_panel)
    market_config.write_text(
        yaml.safe_dump(
            {
                "growth": {"signals": [{"name": "spy", "symbol": "SPY", "transform": "raw_sign", "lookback_days": 1}]},
                "inflation": {"signals": [{"name": "oil", "symbol": "USO", "transform": "raw_sign", "lookback_days": 1}]},
                "risk_overlay": {"signals": [{"name": "vix", "symbol": "VIX", "transform": "raw_sign", "lookback_days": 1}]},
            }
        ),
        encoding="utf-8",
    )

    exit_code = main(
        [
            "regime-detect",
            "--macro-panel",
            str(macro_panel),
            "--fred-series-config",
            str(fred_config),
            "--market-panel",
            str(market_panel),
            "--market-regime-config",
            str(market_config),
            "--output",
            str(output),
            "--latest-only",
        ]
    )

    assert exit_code == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload[0]["version"] == "regime-engine-v2"
    assert payload[0]["final_regime"]
    assert payload[0]["layer_outputs"]
