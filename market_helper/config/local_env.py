from __future__ import annotations

import glob
import os
import platform
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


def _probe_gdrive_root() -> str:
    """Best-effort default for ``MARKET_HELPER_GDRIVE_ROOT`` when env + registry
    are both empty.

    Tries well-known Google Drive mount paths for the current OS and returns
    the first one whose ``local.env`` actually exists. Returns ``""`` if no
    candidate matches.

    This makes typical Mac + Windows installs **zero-config** — no
    per-machine env var or registry entry needed in the canonical layout.
    Override with an explicit env var to point at a non-standard location.

    Known candidates:
        Windows: ``G:/My Drive/005 Portfolio``
        macOS:   ``~/Library/CloudStorage/GoogleDrive-<account>/My Drive/005 Portfolio``
                 + any ``~/Library/CloudStorage/GoogleDrive-*/My Drive/005 Portfolio``
                 + legacy ``~/Google Drive/My Drive/005 Portfolio``
    """
    sys_name = platform.system()
    if sys_name == "Windows":
        candidates: list[Path] = [Path("G:/My Drive/005 Portfolio")]
    elif sys_name == "Darwin":
        home = Path.home()
        candidates = [
            home / "Library/CloudStorage/GoogleDrive-<account>/My Drive/005 Portfolio",
            *(
                Path(match)
                for match in glob.glob(
                    str(home / "Library/CloudStorage/GoogleDrive-*/My Drive/005 Portfolio")
                )
            ),
            home / "Google Drive/My Drive/005 Portfolio",
        ]
    else:
        return ""
    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate)
        if key in seen:
            continue
        seen.add(key)
        if (candidate / LOCAL_ENV_FILENAME).is_file():
            return key
    return ""


def read_gdrive_root(*, environ: Mapping[str, str] | None = None) -> str:
    """Canonical resolver for ``MARKET_HELPER_GDRIVE_ROOT``.

    Tries, in order:

    1. Process env (or the explicit ``environ`` arg for hermetic tests).
    2. Windows User registry hive (``HKCU\\Environment``) — Win-only, no-op
       elsewhere; lets long-lived parents recover after ``setx`` ran.
    3. OS-aware default-probe (:func:`_probe_gdrive_root`) — picks the first
       well-known Google Drive mount path whose ``local.env`` exists.

    Steps 2 and 3 are skipped when the caller passes an explicit ``environ=``
    (hermetic tests should never touch the host registry or filesystem
    probes for the live user's GDrive mount).

    Returns ``""`` when no source yields a value.
    """
    env = environ if environ is not None else os.environ
    value = str(env.get(MARKET_HELPER_GDRIVE_ROOT_ENV_VAR, "")).strip()
    if value:
        return value
    if environ is not None:
        return ""
    value = read_windows_user_env(MARKET_HELPER_GDRIVE_ROOT_ENV_VAR)
    if value:
        return value
    return _probe_gdrive_root()


def resolve_local_config_path(
    default_path: str | Path | None = None,
    *,
    environ: Mapping[str, str] | None = None,
) -> Path:
    """Resolve the path to ``local.env``.

    Priority order:

    1. ``<MARKET_HELPER_GDRIVE_ROOT>/local.env``, where ROOT is resolved by
       :func:`read_gdrive_root` (process env → Windows registry → OS-aware
       probe of well-known Google Drive mount paths).
    2. ``default_path`` argument, or the repo-checked-in
       ``configs/portfolio_monitor/local.env`` as a final fallback.
    """
    gdrive_root = read_gdrive_root(environ=environ)
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
