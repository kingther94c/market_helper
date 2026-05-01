"""CLI-facing wrapper for market-regime price panel sync."""
from __future__ import annotations

from pathlib import Path

from market_helper.data_sources.yahoo_finance.market_panel import sync_market_panel
from market_helper.regimes.methods.market_regime import market_symbol_specs_from_config


def run_market_regime_sync(
    *,
    config_path: Path,
    cache_dir: Path,
    period: str = "max",
    interval: str = "1d",
    start_date: str | None = None,
    end_date: str | None = None,
) -> Path:
    specs = market_symbol_specs_from_config(config_path)
    if not specs:
        raise ValueError(f"{config_path}: no market symbols configured")
    return sync_market_panel(
        specs,
        cache_dir=cache_dir,
        period=period,
        interval=interval,
        start_date=start_date,
        end_date=end_date,
    )


__all__ = ["run_market_regime_sync"]
