from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping


# Mirror of the constant in
# market_helper/domain/portfolio_monitor/pipelines/generate_portfolio_report.py
# — duplicated as a literal to avoid pulling domain code into the config layer.
MARKET_HELPER_GDRIVE_ROOT_ENV_VAR = "MARKET_HELPER_GDRIVE_ROOT"
LOCAL_ENV_FILENAME = "local.env"
DEFAULT_LOCAL_CONFIG_PATH = (
    Path(__file__).resolve().parents[2] / "configs" / "portfolio_monitor" / LOCAL_ENV_FILENAME
)


def read_windows_user_env(key: str) -> str:
    """Read a User-level Windows env var directly from the registry.

    Returns ``""`` on non-Windows hosts or when the key is absent / unreadable.

    Used as a fallback when a User env var was set via ``setx`` *after* the
    current process's parent started — in that case the value is in the
    registry but not in ``os.environ`` (Windows only propagates env vars
    on process spawn, not retroactively). Without this fallback, long-lived
    parent processes (agent shells, services, daemons) silently see empty
    values even though the user thinks the env var is set.
    """
    if os.name != "nt":
        return ""
    try:
        import winreg  # type: ignore[import-not-found]
    except ImportError:
        return ""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as hive:
            value, _ = winreg.QueryValueEx(hive, str(key).strip())
    except (FileNotFoundError, OSError):
        return ""
    return str(value).strip()


def resolve_local_config_path(
    default_path: str | Path | None = None,
    *,
    environ: Mapping[str, str] | None = None,
) -> Path:
    """Resolve the path to ``local.env``.

    Priority order:

    1. ``<MARKET_HELPER_GDRIVE_ROOT>/local.env``, if ROOT is set and the
       derived file exists. A single per-machine env var drives both
       report-mirror placement and local.env discovery. On Windows, if
       ROOT is absent from ``os.environ`` we also try the User registry
       hive directly (see :func:`read_windows_user_env`) so processes
       launched before ``setx`` ran still find the value.
    2. ``default_path`` argument, or the repo-checked-in
       ``configs/portfolio_monitor/local.env`` as a final fallback.
    """
    env = environ if environ is not None else os.environ

    gdrive_root = str(env.get(MARKET_HELPER_GDRIVE_ROOT_ENV_VAR, "")).strip()
    # Skip the Windows registry fallback when the caller passed an explicit
    # `environ` (typically a test fixture) — tests should be hermetic from
    # the real host registry. Production callers pass no `environ`, so they
    # still benefit from the fallback.
    if not gdrive_root and environ is None:
        gdrive_root = read_windows_user_env(MARKET_HELPER_GDRIVE_ROOT_ENV_VAR)
    if gdrive_root:
        derived_path = Path(gdrive_root).expanduser() / LOCAL_ENV_FILENAME
        if derived_path.is_file():
            return derived_path

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
