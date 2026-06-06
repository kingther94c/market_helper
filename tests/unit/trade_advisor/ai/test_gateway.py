"""AI+ gateway client: token resolution, auth guard, network boundary (hermetic)."""

from __future__ import annotations

import json

import pytest

from market_helper.trade_advisor.ai import gateway


# --------------------------------------------------------------------------- #
# GatewayConfig.from_env
# --------------------------------------------------------------------------- #


def test_config_defaults(monkeypatch):
    monkeypatch.delenv("OPENCLAW_GATEWAY_URL", raising=False)
    monkeypatch.delenv("OPENCLAW_TRADE_ADVISOR_MODEL", raising=False)
    cfg = gateway.GatewayConfig.from_env()
    assert cfg.base_url == gateway.DEFAULT_GATEWAY_URL
    assert cfg.model == gateway.DEFAULT_MODEL


def test_config_env_overrides(monkeypatch):
    monkeypatch.setenv("OPENCLAW_GATEWAY_URL", "http://127.0.0.1:9999/v1")
    monkeypatch.setenv("OPENCLAW_TRADE_ADVISOR_MODEL", "openclaw/trade-advisor-panel")
    cfg = gateway.GatewayConfig.from_env()
    assert cfg.base_url == "http://127.0.0.1:9999/v1"
    assert cfg.model == "openclaw/trade-advisor-panel"


# --------------------------------------------------------------------------- #
# resolve_gateway_token precedence
# --------------------------------------------------------------------------- #


def test_token_explicit_wins(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENCLAW_GATEWAY_TOKEN", "from-env")
    assert gateway.resolve_gateway_token("explicit") == "explicit"


def test_token_from_env(monkeypatch):
    monkeypatch.setenv("OPENCLAW_GATEWAY_TOKEN", "  env-token  ")
    assert gateway.resolve_gateway_token() == "env-token"


def test_token_from_local_env(monkeypatch, tmp_path):
    monkeypatch.delenv("OPENCLAW_GATEWAY_TOKEN", raising=False)
    p = tmp_path / "local.env"
    p.write_text('OPENCLAW_GATEWAY_TOKEN="file-token"\n', encoding="utf-8")
    assert gateway.resolve_gateway_token(local_env_path=p) == "file-token"


def test_token_absent_is_empty(monkeypatch, tmp_path):
    monkeypatch.delenv("OPENCLAW_GATEWAY_TOKEN", raising=False)
    # conftest already points OPENCLAW_CONFIG_PATH at a nonexistent file.
    assert gateway.resolve_gateway_token(local_env_path=tmp_path / "nope.env") == ""


def test_token_from_openclaw_config(monkeypatch, tmp_path):
    monkeypatch.delenv("OPENCLAW_GATEWAY_TOKEN", raising=False)
    cfg = tmp_path / "openclaw.json"
    cfg.write_text(json.dumps({"gateway": {"auth": {"token": "cfg-token"}}}), encoding="utf-8")
    monkeypatch.setenv("OPENCLAW_CONFIG_PATH", str(cfg))  # override the conftest neutralization
    assert gateway.resolve_gateway_token(local_env_path=tmp_path / "none.env") == "cfg-token"


def test_token_from_openclaw_config_env_block(monkeypatch, tmp_path):
    monkeypatch.delenv("OPENCLAW_GATEWAY_TOKEN", raising=False)
    cfg = tmp_path / "openclaw.json"
    cfg.write_text(json.dumps({"env": {"OPENCLAW_GATEWAY_TOKEN": "env-block-token"}}), encoding="utf-8")
    assert gateway.resolve_gateway_token(openclaw_config_path=cfg, local_env_path=tmp_path / "none.env") == "env-block-token"


def test_env_token_beats_openclaw_config(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENCLAW_GATEWAY_TOKEN", "env-wins")
    cfg = tmp_path / "openclaw.json"
    cfg.write_text(json.dumps({"gateway": {"auth": {"token": "cfg-token"}}}), encoding="utf-8")
    assert gateway.resolve_gateway_token(openclaw_config_path=cfg) == "env-wins"


# --------------------------------------------------------------------------- #
# post_chat_completion
# --------------------------------------------------------------------------- #


class _FakeResp:
    def __init__(self, payload):
        self._b = json.dumps(payload).encode()

    def read(self):
        return self._b

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_post_requires_token():
    with pytest.raises(gateway.GatewayAuthMissing):
        gateway.post_chat_completion(config=gateway.GatewayConfig(), token="", payload={})


def test_post_success_sends_bearer_and_no_token_in_url(monkeypatch):
    captured = {}

    def fake_urlopen(req, timeout=None):
        captured["url"] = req.full_url
        captured["auth"] = req.get_header("Authorization")
        captured["body"] = json.loads(req.data.decode())
        return _FakeResp({"choices": [{"message": {"content": "hi"}}], "usage": {"prompt_tokens": 5}})

    monkeypatch.setattr(gateway.urllib.request, "urlopen", fake_urlopen)
    out = gateway.post_chat_completion(
        config=gateway.GatewayConfig(base_url="http://127.0.0.1:18789/v1"),
        token="secret-token",
        payload={"model": "openclaw/trade-advisor", "messages": []},
    )
    assert out["choices"][0]["message"]["content"] == "hi"
    assert captured["url"] == "http://127.0.0.1:18789/v1/chat/completions"
    assert captured["auth"] == "Bearer secret-token"
    assert "secret-token" not in captured["url"]  # token never in the URL


def test_post_http_error_becomes_gateway_error(monkeypatch):
    import io
    import urllib.error

    def boom(req, timeout=None):
        raise urllib.error.HTTPError(req.full_url, 502, "Bad Gateway", {}, io.BytesIO(b"upstream boom"))

    monkeypatch.setattr(gateway.urllib.request, "urlopen", boom)
    with pytest.raises(gateway.GatewayError):
        gateway.post_chat_completion(config=gateway.GatewayConfig(), token="t", payload={})


def test_post_unreachable_becomes_gateway_error(monkeypatch):
    import urllib.error

    def boom(req, timeout=None):
        raise urllib.error.URLError("Connection refused")

    monkeypatch.setattr(gateway.urllib.request, "urlopen", boom)
    with pytest.raises(gateway.GatewayError):
        gateway.post_chat_completion(config=gateway.GatewayConfig(), token="t", payload={})
