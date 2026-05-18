from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping


MARKET_HELPER_CONFIG_PATH_ENV_VAR = "MARKET_HELPER_CONFIG_PATH"
DEFAULT_LOCAL_CONFIG_PATH = (
    Path(__file__).resolve().parents[2] / "configs" / "portfolio_monitor" / "local.env"
)


def resolve_local_config_path(
    default_path: str | Path | None = None,
    *,
    environ: Mapping[str, str] | None = None,
) -> Path:
    env = environ if environ is not None else os.environ
    configured_path = str(env.get(MARKET_HELPER_CONFIG_PATH_ENV_VAR, "")).strip()
    if configured_path:
        override_path = Path(configured_path).expanduser()
        if override_path.is_file():
            return override_path
    return Path(default_path or DEFAULT_LOCAL_CONFIG_PATH)


def read_local_config_value(
    key: str,
    *,
    default_path: str | Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> str:
    normalized_key = str(key).strip()
    if not normalized_key:
        return ""
    return read_env_file_value(
        resolve_local_config_path(default_path=default_path, environ=environ),
        normalized_key,
    )


def read_env_file_value(path: str | Path, key: str) -> str:
    normalized_key = str(key).strip()
    if not normalized_key:
        return ""
    env_path = Path(path)
    if not env_path.is_file():
        return ""
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue
        raw_key, raw_value = line.split("=", 1)
        if raw_key.strip() != normalized_key:
            continue
        value = raw_value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        return value.strip()
    return ""
