"""AI+ trade advisor — a parallel, opt-in layer over the rule-based umbrella.

The rule-based engine stays the default and the source of truth (zero AI). This
sub-package adds an *optional* synthesis layer: the same portfolio + regime
context and the rule-based ideas are sent to a local OpenClaw gateway
(OpenAI-compatible), which returns a synthesized advisory. Read-only — analysis
text only, never orders. Disabled with one missing env var
(``OPENCLAW_GATEWAY_TOKEN``); the rule-based surface is unaffected either way.
"""

from .advisor import AiAdvisory, build_prompt, request_ai_advisory
from .gateway import (
    DEFAULT_GATEWAY_URL,
    DEFAULT_MODEL,
    GatewayAuthMissing,
    GatewayConfig,
    GatewayError,
    post_chat_completion,
    resolve_gateway_token,
)

__all__ = [
    "AiAdvisory",
    "build_prompt",
    "request_ai_advisory",
    "GatewayConfig",
    "GatewayError",
    "GatewayAuthMissing",
    "post_chat_completion",
    "resolve_gateway_token",
    "DEFAULT_GATEWAY_URL",
    "DEFAULT_MODEL",
]
