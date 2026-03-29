from __future__ import annotations

from pathlib import Path

from market_helper.domain.regime_detection.services.feature_builder import compute_factor_snapshots
from market_helper.domain.regime_detection.services.input_loader import load_regime_inputs
from market_helper.domain.regime_detection.services.detection_service import load_service_config


def build_regime_features(
    *,
    returns_path: str | Path,
    proxy_path: str | Path,
    config_path: str | Path | None = None,
):
    cfg = load_service_config(config_path)
    bundle = load_regime_inputs(proxy_path=proxy_path, returns_path=returns_path)
    return compute_factor_snapshots(
        dates=bundle.dates,
        vix=bundle.vix,
        move=bundle.move,
        hy_oas=bundle.hy_oas,
        y2=bundle.y2,
        y10=bundle.y10,
        eq_returns=bundle.eq_returns,
        fi_returns=bundle.fi_returns,
        stress_weight_vol=cfg.stress_weight_vol,
        stress_weight_credit=cfg.stress_weight_credit,
    )


__all__ = ["build_regime_features"]
