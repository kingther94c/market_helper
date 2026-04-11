from __future__ import annotations

from pathlib import Path

from market_helper.common.progress import ProgressReporter
from market_helper.domain.regime_detection.services.detection_service import detect_regimes


def run_regime_detection(
    *,
    returns_path: str | Path,
    proxy_path: str | Path,
    output_path: str | Path,
    config_path: str | Path | None = None,
    latest_only: bool = False,
    indicator_output_path: str | Path | None = None,
    progress: ProgressReporter | None = None,
):
    return detect_regimes(
        returns_path=returns_path,
        proxy_path=proxy_path,
        output_path=output_path,
        config_path=config_path,
        latest_only=latest_only,
        indicator_output_path=indicator_output_path,
        progress=progress,
    )


__all__ = ["run_regime_detection"]
