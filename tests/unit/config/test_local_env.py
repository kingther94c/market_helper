from __future__ import annotations

import os
import sys

import pytest

from market_helper.config import local_env
from market_helper.config.local_env import (
    LOCAL_ENV_FILENAME,
    MARKET_HELPER_GDRIVE_ROOT_ENV_VAR,
    read_env_file_value,
    read_local_config_value,
    read_windows_user_env,
    resolve_local_config_path,
)


def test_resolve_local_config_path_derives_from_gdrive_root(tmp_path) -> None:
    """When GDRIVE_ROOT is set, derive <ROOT>/local.env."""
    default_path = tmp_path / "default.env"
    gdrive_root = tmp_path / "005 Portfolio"
    gdrive_root.mkdir()
    derived_path = gdrive_root / LOCAL_ENV_FILENAME
    derived_path.write_text('DEMO_KEY="derived"\n', encoding="utf-8")

    resolved = resolve_local_config_path(
        default_path=default_path,
        environ={MARKET_HELPER_GDRIVE_ROOT_ENV_VAR: str(gdrive_root)},
    )

    assert resolved == derived_path


def test_resolve_local_config_path_falls_through_when_gdrive_root_has_no_env_file(tmp_path) -> None:
    """GDRIVE_ROOT set but no local.env inside → fall through to default."""
    default_path = tmp_path / "default.env"
    gdrive_root = tmp_path / "005 Portfolio"
    gdrive_root.mkdir()  # no local.env inside

    resolved = resolve_local_config_path(
        default_path=default_path,
        environ={MARKET_HELPER_GDRIVE_ROOT_ENV_VAR: str(gdrive_root)},
    )

    assert resolved == default_path


def test_resolve_local_config_path_falls_back_to_default_when_no_env(tmp_path) -> None:
    """Neither env var set → use default_path argument."""
    default_path = tmp_path / "default.env"

    resolved = resolve_local_config_path(default_path=default_path, environ={})

    assert resolved == default_path


def test_read_local_config_value_uses_gdrive_root(tmp_path) -> None:
    default_path = tmp_path / "default.env"
    gdrive_root = tmp_path / "005 Portfolio"
    gdrive_root.mkdir()
    synced = gdrive_root / LOCAL_ENV_FILENAME
    default_path.write_text('DEMO_KEY="default"\n', encoding="utf-8")
    synced.write_text("export DEMO_KEY='override'\n", encoding="utf-8")

    value = read_local_config_value(
        "DEMO_KEY",
        default_path=default_path,
        environ={MARKET_HELPER_GDRIVE_ROOT_ENV_VAR: str(gdrive_root)},
    )

    assert value == "override"


def test_resolve_local_config_path_uses_windows_user_env_when_process_env_empty(
    tmp_path, monkeypatch
) -> None:
    """When ROOT missing from os.environ, fall back to read_windows_user_env.

    Simulates the Claude/Codex agent-shell case where the user set
    MARKET_HELPER_GDRIVE_ROOT via `setx` after the parent process started,
    so it's in the registry but not in os.environ. Without this fallback,
    every tool call has to manually inject ROOT from the registry.
    """
    default_path = tmp_path / "default.env"
    gdrive_root = tmp_path / "005 Portfolio"
    gdrive_root.mkdir()
    derived_path = gdrive_root / LOCAL_ENV_FILENAME
    derived_path.write_text('DEMO_KEY="from-registry"\n', encoding="utf-8")

    # Ensure the env path is empty in os.environ
    monkeypatch.delenv(MARKET_HELPER_GDRIVE_ROOT_ENV_VAR, raising=False)
    # Monkey-patch the registry-read helper to return our tmp path
    monkeypatch.setattr(
        local_env,
        "read_windows_user_env",
        lambda key: str(gdrive_root) if key == MARKET_HELPER_GDRIVE_ROOT_ENV_VAR else "",
    )

    # No explicit environ → production code path → registry fallback engages
    resolved = resolve_local_config_path(default_path=default_path)

    assert resolved == derived_path


def test_resolve_local_config_path_skips_registry_when_explicit_environ_passed(
    tmp_path, monkeypatch
) -> None:
    """Explicit environ={} → test-hermetic — must not consult the host registry."""
    default_path = tmp_path / "default.env"

    # If the registry helper were called it would corrupt the test by reading
    # the real host. We assert it's never called by raising on access.
    def explode(key: str) -> str:
        raise AssertionError(f"read_windows_user_env({key!r}) called despite explicit environ")

    monkeypatch.setattr(local_env, "read_windows_user_env", explode)

    resolved = resolve_local_config_path(default_path=default_path, environ={})

    assert resolved == default_path


@pytest.mark.skipif(os.name != "nt", reason="winreg only exists on Windows")
def test_read_windows_user_env_returns_empty_string_for_missing_key() -> None:
    """Smoke test against the real registry — unknown key returns ''."""
    assert read_windows_user_env("MARKET_HELPER_DEFINITELY_NOT_A_REAL_KEY_zZ9") == ""


def test_read_windows_user_env_returns_empty_string_on_non_windows(monkeypatch) -> None:
    """Helper short-circuits to '' on POSIX without importing winreg."""
    monkeypatch.setattr(local_env.os, "name", "posix")
    assert read_windows_user_env("ANY_KEY") == ""


def test_read_env_file_value_supports_export_and_quotes(tmp_path) -> None:
    env_path = tmp_path / "local.env"
    env_path.write_text(
        "\n".join(
            [
                "# comment",
                "export FRED_API_KEY='fred-key'",
                'ALPHA_VANTAGE_API_KEY="alpha-key"',
            ]
        ),
        encoding="utf-8",
    )

    assert read_env_file_value(env_path, "FRED_API_KEY") == "fred-key"
    assert read_env_file_value(env_path, "ALPHA_VANTAGE_API_KEY") == "alpha-key"
