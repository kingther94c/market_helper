"""OpenClaw gateway client (OpenAI-compatible) for the AI+ trade advisor.

The single network boundary is :func:`post_chat_completion` (stdlib ``urllib``,
no SDK dependency), which tests monkeypatch. The bearer token is resolved from
the environment / local.env and is **never logged or placed in a URL** — it
rides only in the ``Authorization`` header.

Defaults match the OpenClaw gateway (``http://127.0.0.1:18789/v1``, model
``openclaw/trade-advisor``) and are overridable via env vars so a differently
configured gateway needs no code change.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

DEFAULT_GATEWAY_URL = "http://127.0.0.1:18789/v1"
DEFAULT_MODEL = "openclaw/trade-advisor"

_TOKEN_ENV_VAR = "OPENCLAW_GATEWAY_TOKEN"
_GATEWAY_URL_ENV_VAR = "OPENCLAW_GATEWAY_URL"
_MODEL_ENV_VAR = "OPENCLAW_TRADE_ADVISOR_MODEL"
_DEFAULT_LOCAL_ENV = Path("configs/portfolio_monitor/local.env")
_REQUEST_TIMEOUT_SECONDS = 120.0


class GatewayError(RuntimeError):
    """The OpenClaw gateway was unreachable or returned an error."""


class GatewayAuthMissing(GatewayError):
    """No ``OPENCLAW_GATEWAY_TOKEN`` is configured — AI+ stays disabled."""


@dataclass(frozen=True)
class GatewayConfig:
    """Where/how to reach the gateway (no secrets — the token is passed separately)."""

    base_url: str = DEFAULT_GATEWAY_URL
    model: str = DEFAULT_MODEL
    timeout: float = _REQUEST_TIMEOUT_SECONDS
    session_key: str | None = None

    @classmethod
    def from_env(cls, *, model: str | None = None, session_key: str | None = None) -> "GatewayConfig":
        return cls(
            base_url=(os.environ.get(_GATEWAY_URL_ENV_VAR) or DEFAULT_GATEWAY_URL).strip() or DEFAULT_GATEWAY_URL,
            model=(model or os.environ.get(_MODEL_ENV_VAR) or DEFAULT_MODEL).strip() or DEFAULT_MODEL,
            session_key=session_key,
        )


def resolve_gateway_token(explicit: str | None = None, *, local_env_path: Path | None = None) -> str:
    """Resolve the bearer token: explicit → process env → local.env. ``""`` if absent.

    The value is returned only to the caller — never logged. An empty string
    means AI+ should stay disabled (the rule-based surface is unaffected).
    """
    direct = (explicit or "").strip()
    if direct:
        return direct
    from_env = os.environ.get(_TOKEN_ENV_VAR, "").strip()
    if from_env:
        return from_env
    try:
        from market_helper.config.local_env import read_local_config_value

        value = read_local_config_value(_TOKEN_ENV_VAR, default_path=local_env_path or _DEFAULT_LOCAL_ENV)
        return (value or "").strip()
    except Exception:  # noqa: BLE001 — token discovery must never raise
        return ""


def post_chat_completion(*, config: GatewayConfig, token: str, payload: dict) -> dict:
    """POST an OpenAI-compatible chat-completions request. The network boundary.

    Raises :class:`GatewayAuthMissing` when no token is set, :class:`GatewayError`
    on any transport / protocol failure.
    """
    if not token:
        raise GatewayAuthMissing(
            "no OPENCLAW_GATEWAY_TOKEN configured — set it in the environment or local.env to enable AI+"
        )
    url = config.base_url.rstrip("/") + "/chat/completions"
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=body, method="POST")
    request.add_header("Content-Type", "application/json")
    request.add_header("Authorization", f"Bearer {token}")
    if config.session_key:
        request.add_header("x-openclaw-session-key", config.session_key)
    try:
        with urllib.request.urlopen(request, timeout=config.timeout) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:  # 4xx/5xx from the gateway
        detail = exc.read().decode("utf-8", "replace")[:300]
        raise GatewayError(f"gateway returned HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:  # connection refused / DNS / timeout
        raise GatewayError(f"could not reach the OpenClaw gateway at {url}: {exc.reason}") from exc
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise GatewayError("gateway returned a non-JSON response") from exc
