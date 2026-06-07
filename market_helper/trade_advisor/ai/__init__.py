"""AI+ trade advisor — a parallel, opt-in layer over the rule-based umbrella.

The rule-based engine stays the default and the source of truth (zero AI). This
sub-package adds an *optional* synthesis layer: the same portfolio + regime
context and the rule-based ideas are sent to a local OpenClaw gateway
(OpenAI-compatible), which returns a synthesized advisory. Read-only — analysis
text only, never orders. Disabled with one missing env var
(``OPENCLAW_GATEWAY_TOKEN``); the rule-based surface is unaffected either way.
"""

from .advisor import AiAdvisory, build_prompt, request_ai_advisory
from .capabilities import AdvisorAiCapabilities, build_advisor_ai_capabilities
from .gateway import (
    DEFAULT_GATEWAY_URL,
    DEFAULT_MODEL,
    GatewayAuthMissing,
    GatewayConfig,
    GatewayError,
    post_chat_completion,
    resolve_gateway_token,
)
from .skills import (
    KnowledgeBook,
    KnowledgeEntry,
    PromptSkill,
    SkillRegistry,
    build_core_knowledge,
    knowledge_system_block,
)
from .tools import AiTool, AiToolRegistry, ToolChatResult, run_tool_chat, tool_protocol_instructions

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
    # Capability framework
    "AiTool",
    "AiToolRegistry",
    "ToolChatResult",
    "run_tool_chat",
    "tool_protocol_instructions",
    "PromptSkill",
    "KnowledgeEntry",
    "SkillRegistry",
    "KnowledgeBook",
    "build_core_knowledge",
    "knowledge_system_block",
    "AdvisorAiCapabilities",
    "build_advisor_ai_capabilities",
]
