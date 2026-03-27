from __future__ import annotations

from pathlib import Path

from market_helper.regimes.service import detect_regimes


def generate_regime_snapshots(
    *,
    returns_path: str | Path,
    proxy_path: str | Path,
    output_path: str | Path,
    config_path: str | Path | None = None,
    latest_only: bool = False,
    indicator_output_path: str | Path | None = None,
):
    """Workflow wrapper for CLI regime detection command."""
    return detect_regimes(
        returns_path=returns_path,
        proxy_path=proxy_path,
        output_path=output_path,
        config_path=config_path,
        latest_only=latest_only,
        indicator_output_path=indicator_output_path,
    )
