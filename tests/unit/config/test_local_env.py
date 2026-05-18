from __future__ import annotations

from market_helper.config.local_env import (
    MARKET_HELPER_CONFIG_PATH_ENV_VAR,
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
