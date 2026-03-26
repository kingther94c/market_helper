from __future__ import annotations

import json

import pytest

from market_helper.config import load_settings


def test_load_settings_from_json(tmp_path) -> None:
    file_path = tmp_path / "settings.json"
    file_path.write_text(
        json.dumps(
            {
                "mode": "read_only",
                "provider": {
                    "web_api_base_url": "https://localhost:5000/v1/api",
                    "account_id": "U12345",
                    "username": "ibkr_user",
                    "password_env_var": "IBKR_CP_PASSWORD",
                    "oauth_consumer_key_env_var": "IBKR_OAUTH_CONSUMER_KEY",
                },
            }
        ),
        encoding="utf-8",
    )

    settings = load_settings(file_path)

    assert settings.mode == "read_only"
    assert settings.provider.account_id == "U12345"
    assert settings.provider.username == "ibkr_user"
    assert settings.provider.password_env_var == "IBKR_CP_PASSWORD"
    assert settings.provider.oauth_consumer_key_env_var == "IBKR_OAUTH_CONSUMER_KEY"


def test_load_settings_rejects_non_read_only_mode(tmp_path) -> None:
    file_path = tmp_path / "settings.json"
    file_path.write_text(json.dumps({"mode": "paper_trading"}), encoding="utf-8")

    with pytest.raises(ValueError):
        load_settings(file_path)
