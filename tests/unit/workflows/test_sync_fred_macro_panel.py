from __future__ import annotations

import market_helper.workflows.sync_fred_macro_panel as sync_fred_macro_panel


def test_resolve_fred_api_key_reads_market_helper_config_path(tmp_path, monkeypatch) -> None:
    default_env = tmp_path / "local.env"
    override_env = tmp_path / "synced.env"
    default_env.write_text('FRED_API_KEY="default-key"\n', encoding="utf-8")
    override_env.write_text('FRED_API_KEY="synced-key"\n', encoding="utf-8")

    monkeypatch.delenv("FRED_API_KEY", raising=False)
    monkeypatch.setenv("MARKET_HELPER_CONFIG_PATH", str(override_env))
    monkeypatch.setattr(sync_fred_macro_panel, "_DEFAULT_LOCAL_ENV_PATH", default_env)

    assert sync_fred_macro_panel._resolve_fred_api_key(None) == "synced-key"


def test_resolve_fred_api_key_falls_back_to_default_local_env(tmp_path, monkeypatch) -> None:
    default_env = tmp_path / "local.env"
    default_env.write_text('FRED_API_KEY="default-key"\n', encoding="utf-8")

    monkeypatch.delenv("FRED_API_KEY", raising=False)
    monkeypatch.setenv("MARKET_HELPER_CONFIG_PATH", str(tmp_path / "missing.env"))
    monkeypatch.setattr(sync_fred_macro_panel, "_DEFAULT_LOCAL_ENV_PATH", default_env)

    assert sync_fred_macro_panel._resolve_fred_api_key(None) == "default-key"
