from __future__ import annotations

"""High-level regime report entry points."""

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from market_helper.data_sources.fred.macro_panel import DEFAULT_PANEL_FILENAME
from market_helper.workflows.generate_multi_method_regime import (
    ALL_METHODS,
    run_multi_method_detection,
)
from market_helper.workflows.generate_regime_html import generate_regime_html_report
from market_helper.workflows.sync_fred_macro_panel import run_fred_macro_sync
from market_helper.workflows.sync_regime_inputs import (
    DEFAULT_HY_OAS_HISTORY_PATH,
    DEFAULT_REGIME_PROXY_PATH,
    DEFAULT_REGIME_RETURNS_PATH,
    sync_regime_inputs,
)


DEFAULT_REGIME_ARTIFACT_PATH = Path("data/artifacts/regime_detection/regime_multi_snapshots.json")
DEFAULT_REGIME_HTML_PATH = Path("data/artifacts/regime_detection/regime_report.html")
DEFAULT_FRED_CACHE_DIR = Path("data/interim/fred")
DEFAULT_FRED_SERIES_CONFIG = Path("configs/regime_detection/fred_series.yml")
DEFAULT_FRED_SERIES_EXAMPLE_CONFIG = Path("configs/regime_detection/fred_series.example.yml")


@dataclass(frozen=True)
class RegimeReportRunResult:
    regime_path: Path
    html_path: Path
    returns_path: Path
    proxy_path: Path
    macro_panel_path: Path
    refreshed_inputs: bool = False
    refreshed_macro_panel: bool = False


def run_regime_report_from_existing_data(
    *,
    methods: Sequence[str] = ALL_METHODS,
    macro_panel_path: str | Path | None = None,
    fred_series_config: str | Path | None = None,
    returns_path: str | Path = DEFAULT_REGIME_RETURNS_PATH,
    proxy_path: str | Path = DEFAULT_REGIME_PROXY_PATH,
    output_regime_path: str | Path = DEFAULT_REGIME_ARTIFACT_PATH,
    output_html_path: str | Path = DEFAULT_REGIME_HTML_PATH,
    policy_path: str | Path | None = None,
    latest_only: bool = False,
) -> RegimeReportRunResult:
    """Run regime detection + HTML from already-synced local inputs."""
    resolved_config = _resolve_fred_series_config(fred_series_config)
    resolved_macro_panel = Path(macro_panel_path) if macro_panel_path else DEFAULT_FRED_CACHE_DIR / DEFAULT_PANEL_FILENAME
    output_regime = Path(output_regime_path)
    output_html = Path(output_html_path)
    returns = Path(returns_path)
    proxy = Path(proxy_path)

    run_multi_method_detection(
        methods=methods,
        macro_panel_path=resolved_macro_panel,
        fred_series_config=resolved_config,
        returns_path=returns,
        proxy_path=proxy,
        output_path=output_regime,
        latest_only=latest_only,
    )
    generate_regime_html_report(
        regime_path=output_regime,
        output_path=output_html,
        policy_path=policy_path,
    )
    return RegimeReportRunResult(
        regime_path=output_regime,
        html_path=output_html,
        returns_path=returns,
        proxy_path=proxy,
        macro_panel_path=resolved_macro_panel,
    )


def refresh_data_and_run_regime_report(
    *,
    methods: Sequence[str] = ALL_METHODS,
    max_age_days: int = 7,
    force_refresh: bool = False,
    macro_panel_path: str | Path | None = None,
    fred_cache_dir: str | Path = DEFAULT_FRED_CACHE_DIR,
    fred_series_config: str | Path | None = None,
    returns_path: str | Path = DEFAULT_REGIME_RETURNS_PATH,
    proxy_path: str | Path = DEFAULT_REGIME_PROXY_PATH,
    output_regime_path: str | Path = DEFAULT_REGIME_ARTIFACT_PATH,
    output_html_path: str | Path = DEFAULT_REGIME_HTML_PATH,
    policy_path: str | Path | None = None,
    fred_observation_start: str | None = None,
    hy_oas_history_path: str | Path | None = DEFAULT_HY_OAS_HISTORY_PATH,
    macro_start_date: str | None = None,
    macro_end_date: str | None = None,
    fred_api_key: str | None = None,
    eq_symbol: str = "SPY",
    fi_symbol: str = "AGG",
    vix_symbol: str = "^VIX",
    move_symbol: str = "^MOVE",
    yahoo_period: str = "max",
    yahoo_interval: str = "1d",
    latest_only: bool = False,
) -> RegimeReportRunResult:
    """Refresh stale online inputs, then run regime detection + HTML."""
    enabled = _normalize_methods(methods)
    resolved_config = _resolve_fred_series_config(fred_series_config)
    if macro_panel_path is not None:
        resolved_macro_panel = Path(macro_panel_path)
        if resolved_macro_panel.name != DEFAULT_PANEL_FILENAME:
            raise ValueError(
                f"refresh mode requires --macro-panel to be named {DEFAULT_PANEL_FILENAME!r}"
            )
        cache_dir = resolved_macro_panel.parent
    else:
        cache_dir = Path(fred_cache_dir)
        resolved_macro_panel = cache_dir / DEFAULT_PANEL_FILENAME
    returns = Path(returns_path)
    proxy = Path(proxy_path)

    refreshed_inputs = False
    if "legacy_rulebook" in enabled and (
        force_refresh or not _all_fresh([returns, proxy], max_age_days=max_age_days)
    ):
        sync_regime_inputs(
            returns_output_path=returns,
            proxy_output_path=proxy,
            eq_symbol=eq_symbol,
            fi_symbol=fi_symbol,
            vix_symbol=vix_symbol,
            move_symbol=move_symbol,
            yahoo_period=yahoo_period,
            yahoo_interval=yahoo_interval,
            fred_observation_start=fred_observation_start,
            fred_api_key=fred_api_key,
            hy_oas_history_path=hy_oas_history_path,
        )
        refreshed_inputs = True

    refreshed_macro_panel = False
    if "macro_rules" in enabled and (
        force_refresh or not _all_fresh([resolved_macro_panel], max_age_days=max_age_days)
    ):
        run_fred_macro_sync(
            config_path=resolved_config,
            cache_dir=cache_dir,
            observation_start=fred_observation_start,
            start_date=macro_start_date,
            end_date=macro_end_date,
            force=force_refresh,
            api_key=fred_api_key,
        )
        refreshed_macro_panel = True

    result = run_regime_report_from_existing_data(
        methods=tuple(enabled),
        macro_panel_path=resolved_macro_panel,
        fred_series_config=resolved_config,
        returns_path=returns,
        proxy_path=proxy,
        output_regime_path=output_regime_path,
        output_html_path=output_html_path,
        policy_path=policy_path,
        latest_only=latest_only,
    )
    return RegimeReportRunResult(
        regime_path=result.regime_path,
        html_path=result.html_path,
        returns_path=returns,
        proxy_path=proxy,
        macro_panel_path=resolved_macro_panel,
        refreshed_inputs=refreshed_inputs,
        refreshed_macro_panel=refreshed_macro_panel,
    )


def _resolve_fred_series_config(path: str | Path | None) -> Path:
    if path is not None:
        return Path(path)
    if DEFAULT_FRED_SERIES_CONFIG.exists():
        return DEFAULT_FRED_SERIES_CONFIG
    return DEFAULT_FRED_SERIES_EXAMPLE_CONFIG


def _normalize_methods(methods: Sequence[str]) -> tuple[str, ...]:
    enabled = {str(method).strip().lower() for method in methods if str(method).strip()}
    if not enabled or "all" in enabled:
        enabled = set(ALL_METHODS)
    return tuple(sorted(enabled))


def _all_fresh(paths: Sequence[Path], *, max_age_days: int) -> bool:
    if max_age_days < 0:
        return False
    if not paths or any(not path.exists() for path in paths):
        return False
    newest_allowed_age_seconds = float(max_age_days) * 24.0 * 60.0 * 60.0
    now = time.time()
    return all(now - path.stat().st_mtime <= newest_allowed_age_seconds for path in paths)


__all__ = [
    "DEFAULT_FRED_CACHE_DIR",
    "DEFAULT_FRED_SERIES_CONFIG",
    "DEFAULT_REGIME_ARTIFACT_PATH",
    "DEFAULT_REGIME_HTML_PATH",
    "RegimeReportRunResult",
    "refresh_data_and_run_regime_report",
    "run_regime_report_from_existing_data",
]
