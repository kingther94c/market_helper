from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Literal

try:
    import yaml
except Exception:  # pragma: no cover - optional dependency at runtime
    yaml = None


Mode = Literal["read_only"]


@dataclass(frozen=True)
class ProviderSettings:
    web_api_base_url: str = ""
    account_id: str = ""
    username: str = ""
    password_env_var: str = "IBKR_CP_PASSWORD"
    oauth_consumer_key_env_var: str = ""


@dataclass(frozen=True)
class AppSettings:
    mode: Mode
    provider: ProviderSettings


def load_settings(path: str | Path) -> AppSettings:
    payload = _load_payload(path)
    mode = payload.get("mode", "read_only")
    if mode != "read_only":
        raise ValueError("Only read_only mode is supported in V1")

    provider_payload = payload.get("provider", {})
    provider = ProviderSettings(
        web_api_base_url=str(provider_payload.get("web_api_base_url", "")),
        account_id=str(provider_payload.get("account_id", "")),
        username=str(provider_payload.get("username", "")),
        password_env_var=str(provider_payload.get("password_env_var", "IBKR_CP_PASSWORD")),
        oauth_consumer_key_env_var=str(
            provider_payload.get("oauth_consumer_key_env_var", "")
        ),
    )
    return AppSettings(mode=mode, provider=provider)


def _load_payload(path: str | Path) -> dict[str, Any]:
    file_path = Path(path)
    text = file_path.read_text(encoding="utf-8")

    if file_path.suffix in {".json"}:
        return dict(json.loads(text))
    if file_path.suffix in {".yaml", ".yml"}:
        if yaml is None:
            raise RuntimeError("PyYAML is required for YAML settings files")
        loaded = yaml.safe_load(text) or {}
        return dict(loaded)

    raise ValueError(f"Unsupported settings file extension: {file_path.suffix}")
