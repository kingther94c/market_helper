"""Thin CLI-facing wrapper around the FRED macro panel sync.

Handles API-key resolution (arg -> env -> configs/portfolio_monitor/local.env)
and delegates to ``market_helper.data_sources.fred.macro_panel.sync_macro_panel``.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from market_helper.data_sources.fred.macro_panel import sync_macro_panel

_FRED_API_KEY_ENV_VAR = "FRED_API_KEY"
_DEFAULT_LOCAL_ENV_PATH = Path("configs/portfolio_monitor/local.env")


def _read_env_file_value(path: Path, key: str) -> str:
    if not path.exists():
        return ""
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue
        raw_key, raw_value = line.split("=", 1)
        if raw_key.strip() != key:
            continue
        value = raw_value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        return value.strip()
    return ""


def _resolve_fred_api_key(api_key: Optional[str]) -> str:
    direct = (api_key or "").strip()
    if direct:
        return direct
    from_env = os.environ.get(_FRED_API_KEY_ENV_VAR, "").strip()
    if from_env:
        return from_env
    return _read_env_file_value(_DEFAULT_LOCAL_ENV_PATH, _FRED_API_KEY_ENV_VAR)


def run_fred_macro_sync(
    *,
    config_path: Path,
    cache_dir: Path,
    observation_start: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    force: bool = False,
    api_key: Optional[str] = None,
) -> Path:
    resolved_key = _resolve_fred_api_key(api_key)
    if not resolved_key:
        raise RuntimeError(
            "FRED_API_KEY is not set. Pass --api-key, export FRED_API_KEY, "
            "or add it to configs/portfolio_monitor/local.env."
        )
    return sync_macro_panel(
        config_path=config_path,
        api_key=resolved_key,
        cache_dir=Path(cache_dir),
        observation_start=observation_start,
        start_date=start_date,
        end_date=end_date,
        force=force,
    )


__all__ = ["run_fred_macro_sync"]
