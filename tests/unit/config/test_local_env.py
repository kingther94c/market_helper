from __future__ import annotations

from market_helper.config.local_env import (
    LOCAL_ENV_FILENAME,
    MARKET_HELPER_CONFIG_PATH_ENV_VAR,
    MARKET_HELPER_GDRIVE_ROOT_ENV_VAR,
    read_env_file_value,
    read_local_config_value,
    resolve_local_config_path,
)


def test_resolve_local_config_path_prefers_existing_market_helper_config_path(tmp_path) -> None:
    default_path = tmp_path / "default.env"
    override_path = tmp_path / "Google Drive" / "market_helper.env"
    override_path.parent.mkdir()
    override_path.write_text('DEMO_KEY="override"\n', encoding="utf-8")

    resolved = resolve_local_config_path(
        default_path=default_path,
        environ={MARKET_HELPER_CONFIG_PATH_ENV_VAR: str(override_path)},
    )

    assert resolved == override_path


def test_resolve_local_config_path_falls_back_when_override_missing(tmp_path) -> None:
    default_path = tmp_path / "default.env"
    missing_override = tmp_path / "missing.env"

    resolved = resolve_local_config_path(
        default_path=default_path,
        environ={MARKET_HELPER_CONFIG_PATH_ENV_VAR: str(missing_override)},
    )

    assert resolved == default_path


def test_resolve_local_config_path_derives_from_gdrive_root(tmp_path) -> None:
    """When CONFIG_PATH is unset but GDRIVE_ROOT is, derive <ROOT>/local.env."""
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


def test_resolve_local_config_path_prefers_explicit_path_over_gdrive_root(tmp_path) -> None:
    """CONFIG_PATH still wins when both are set, so legacy setups don't change."""
    default_path = tmp_path / "default.env"
    explicit = tmp_path / "explicit.env"
    explicit.write_text("x=y\n", encoding="utf-8")
    gdrive_root = tmp_path / "005 Portfolio"
    gdrive_root.mkdir()
    (gdrive_root / LOCAL_ENV_FILENAME).write_text("x=y\n", encoding="utf-8")

    resolved = resolve_local_config_path(
        default_path=default_path,
        environ={
            MARKET_HELPER_CONFIG_PATH_ENV_VAR: str(explicit),
            MARKET_HELPER_GDRIVE_ROOT_ENV_VAR: str(gdrive_root),
        },
    )

    assert resolved == explicit


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


def test_read_local_config_value_uses_market_helper_config_path(tmp_path) -> None:
    default_path = tmp_path / "default.env"
    override_path = tmp_path / "synced.env"
    default_path.write_text('DEMO_KEY="default"\n', encoding="utf-8")
    override_path.write_text("export DEMO_KEY='override'\n", encoding="utf-8")

    value = read_local_config_value(
        "DEMO_KEY",
        default_path=default_path,
        environ={MARKET_HELPER_CONFIG_PATH_ENV_VAR: str(override_path)},
    )

    assert value == "override"


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
