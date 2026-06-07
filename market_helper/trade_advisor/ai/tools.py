"""AI tool framework — register local READ-ONLY functions the advisor AI may call.

The advisor AI (OpenClaw gateway, OpenAI-compatible) can be handed a set of
**tools** (function schemas). When the model decides it needs data it emits
``tool_calls``; :func:`run_tool_chat` executes them against the registry, feeds
the JSON results back as ``role=tool`` messages, and loops until the model
answers — so the AI grounds its brief on real, freshly-pulled local data instead
of whatever we happened to pre-stuff into the prompt.

Invariants:
- **Read-only only.** Every registered tool must be ``read_only=True`` — the
  registry refuses anything else. Tools fetch/compute and return data; they never
  place, size, persist, or mutate. (The whole advisor is read-only w.r.t. the
  broker — ADR 0001.)
- **Bounded.** ``run_tool_chat`` caps tool rounds so a model can't loop forever,
  and every dispatch is wrapped so a tool error becomes a JSON error the model
  can read, never a crash.
- **Transparent.** The returned :class:`ToolChatResult` carries a trace of every
  tool call (name, args, result preview) so the UI can show what the AI looked at.

This is the generic machinery; domains (e.g. ``domain/tactical_ideas``) supply
the actual tools + register them into an :class:`AiToolRegistry`.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Callable

from market_helper.trade_advisor.ai.gateway import (
    GatewayConfig,
    post_chat_completion,
    resolve_gateway_token,
)


@dataclass(frozen=True)
class AiTool:
    """One read-only local function exposed to the AI as an OpenAI function tool."""

    name: str
    description: str
    parameters: dict[str, Any]  # JSON Schema (an "object" schema) for the args
    fn: Callable[..., Any]
    read_only: bool = True

    def to_openai(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {"name": self.name, "description": self.description, "parameters": self.parameters},
        }


_NO_PARAMS: dict[str, Any] = {"type": "object", "properties": {}, "additionalProperties": False}


class AiToolRegistry:
    """A set of read-only tools the AI may call. Add a tool = register one AiTool."""

    def __init__(self) -> None:
        self._tools: dict[str, AiTool] = {}

    def register(self, tool: AiTool) -> None:
        if not tool.name:
            raise ValueError("AI tool must have a non-empty name")
        if not tool.read_only:
            raise ValueError(f"AI tools must be read-only (offending: {tool.name!r})")
        if tool.name in self._tools:
            raise ValueError(f"AI tool {tool.name!r} already registered")
        self._tools[tool.name] = tool

    def tool(self, name: str, description: str, parameters: dict[str, Any] | None = None):
        """Decorator: register the wrapped function as a read-only tool."""
        def _decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
            self.register(AiTool(name=name, description=description, parameters=parameters or _NO_PARAMS, fn=fn))
            return fn
        return _decorator

    def get(self, name: str) -> AiTool | None:
        return self._tools.get(name)

    def all(self) -> list[AiTool]:
        return list(self._tools.values())

    def keys(self) -> list[str]:
        return list(self._tools)

    def __len__(self) -> int:
        return len(self._tools)

    def __contains__(self, name: str) -> bool:
        return name in self._tools

    def to_openai_tools(self) -> list[dict[str, Any]]:
        return [t.to_openai() for t in self._tools.values()]

    def dispatch(self, name: str, arguments: dict[str, Any] | None) -> str:
        """Execute a tool by name and return its result as a JSON string (errors → JSON)."""
        tool = self._tools.get(name)
        if tool is None:
            return json.dumps({"error": f"unknown tool {name!r}", "available": list(self._tools)})
        try:
            result = tool.fn(**(arguments or {}))
        except TypeError as exc:  # bad/missing args from the model
            return json.dumps({"error": f"bad arguments for {name!r}: {exc}"})
        except Exception as exc:  # noqa: BLE001 — a tool failure must never crash the chat
            return json.dumps({"error": f"{type(exc).__name__}: {str(exc)[:200]}"})
        try:
            return json.dumps(result, default=str)
        except (TypeError, ValueError):
            return json.dumps({"result": str(result)})


@dataclass(frozen=True)
class ToolChatResult:
    """Final assistant text + a transparent trace of the tool calls it made."""

    text: str
    rounds: int = 0
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    model: str = ""
    prompt_tokens: int | None = None
    completion_tokens: int | None = None


def _message(resp: dict) -> dict:
    choices = resp.get("choices") or []
    return (choices[0].get("message") or {}) if choices else {}


# --------------------------------------------------------------------------- #
# Tool-use mechanism: a gateway-agnostic STRUCTURED-TEXT protocol.
#
# Probe finding (2026-06-07): the OpenClaw gateway IGNORES the client-supplied
# OpenAI ``tools`` param (it has its own internal tool registry and does not honor
# ours), so native ``tool_calls`` never come back. Instead we instruct the model
# to request a tool by emitting a fenced ```tool_call {json}``` block; we parse it,
# dispatch the read-only function, and feed the result back as a ```tool_result```
# user turn. This works with ANY plain chat-completions endpoint and is the seam a
# future native-function-calling gateway could replace (``to_openai_tools`` is kept
# for that day).
# --------------------------------------------------------------------------- #

_TOOL_CALL_RE = re.compile(r"```(?:tool_call|json)?\s*(\{.*?\})\s*```", re.DOTALL)


def _tool_manifest(registry: AiToolRegistry) -> str:
    lines = []
    for t in registry.all():
        args = ", ".join((t.parameters.get("properties") or {}).keys())
        lines.append(f"- {t.name}({args}): {t.description}")
    return "\n".join(lines)


def tool_protocol_instructions(registry: AiToolRegistry) -> str:
    """The system-prompt block that teaches the model how to call our tools."""
    return (
        "\n\n## Tools you can call (read-only data fetchers)\n"
        "When you need real data, call ONE tool by replying with ONLY this fenced block and nothing else:\n"
        "```tool_call\n{\"name\": \"<tool_name>\", \"arguments\": { }}\n```\n"
        "You will then receive a ```tool_result``` message; you may call another tool or, once you have "
        "enough, give your FINAL answer with NO tool_call block. Never fabricate data a tool can provide. "
        "Available tools:\n" + _tool_manifest(registry)
    )


def _inject_protocol(messages: list[dict], registry: AiToolRegistry) -> list[dict]:
    msgs = [dict(m) for m in messages]
    block = tool_protocol_instructions(registry)
    for m in msgs:
        if m.get("role") == "system":
            m["content"] = f"{m.get('content', '')}{block}"
            return msgs
    return [{"role": "system", "content": block.strip()}, *msgs]


def _parse_tool_call(text: str, registry: AiToolRegistry) -> tuple[str, dict, str] | None:
    """Find a fenced JSON object naming a registered tool. Returns (name, args, raw_block)."""
    for m in _TOOL_CALL_RE.finditer(text or ""):
        try:
            obj = json.loads(m.group(1))
        except (TypeError, ValueError):
            continue
        if isinstance(obj, dict) and obj.get("name") in registry:
            args = obj.get("arguments")
            return obj["name"], (args if isinstance(args, dict) else {}), m.group(0)
    return None


def _strip_tool_blocks(text: str) -> str:
    return _TOOL_CALL_RE.sub("", text or "").strip()


def run_tool_chat(
    *,
    messages: list[dict],
    registry: AiToolRegistry | None = None,
    config: GatewayConfig | None = None,
    token: str | None = None,
    post: Callable[..., dict] = post_chat_completion,
    max_rounds: int = 4,
    temperature: float = 0.3,
    inject_protocol: bool = True,
) -> ToolChatResult:
    """Drive a tool-use loop via the structured-text protocol (gateway-agnostic).

    Teaches the model the protocol (see :func:`tool_protocol_instructions`), then each
    round parses the reply for a ```tool_call``` block; if present the named read-only
    tool is dispatched and its JSON result fed back as a ```tool_result``` turn, up to
    ``max_rounds``. Returns the final answer (tool blocks stripped) + a transparent
    trace. With no registry (or no tools) it is a plain one-shot chat. ``post`` is
    injectable so tests never touch the network.

    ``inject_protocol=False`` skips adding the protocol block — pass it when the caller
    already baked the protocol into the system message (e.g. a persistent multi-turn
    conversation, so the block isn't appended every turn).
    """
    cfg = config or GatewayConfig.from_env()
    tok = token if token is not None else resolve_gateway_token()

    if not registry or len(registry) == 0:
        resp = post(config=cfg, token=tok, payload={"model": cfg.model, "messages": list(messages), "temperature": temperature})
        msg = _message(resp)
        usage = resp.get("usage") or {}
        return ToolChatResult(
            text=(msg.get("content") or "").strip(), rounds=1, model=str(resp.get("model", cfg.model)),
            prompt_tokens=usage.get("prompt_tokens"), completion_tokens=usage.get("completion_tokens"),
        )

    msgs = _inject_protocol(messages, registry) if inject_protocol else [dict(m) for m in messages]
    trace: list[dict[str, Any]] = []

    for rnd in range(1, max_rounds + 1):
        resp = post(config=cfg, token=tok, payload={"model": cfg.model, "messages": msgs, "temperature": temperature})
        msg = _message(resp)
        content = msg.get("content") or ""
        parsed = _parse_tool_call(content, registry)
        if parsed is None:
            usage = resp.get("usage") or {}
            return ToolChatResult(
                text=_strip_tool_blocks(content), rounds=rnd, tool_calls=trace,
                model=str(resp.get("model", cfg.model)),
                prompt_tokens=usage.get("prompt_tokens"), completion_tokens=usage.get("completion_tokens"),
            )
        name, args, _raw = parsed
        result = registry.dispatch(name, args)
        trace.append({"round": rnd, "name": name, "arguments": args, "result_preview": result[:300]})
        msgs.append({"role": "assistant", "content": content})
        msgs.append({"role": "user", "content": f"```tool_result name={name}\n{result}\n```\nContinue, or give your final answer."})

    # Max rounds hit — one final pass instructing a written answer (no more tool calls).
    resp = post(
        config=cfg, token=tok,
        payload={"model": cfg.model, "messages": [*msgs, {"role": "user", "content": "Give your final answer now from the tool results above; do not call any more tools."}], "temperature": temperature},
    )
    msg = _message(resp)
    usage = resp.get("usage") or {}
    return ToolChatResult(
        text=_strip_tool_blocks(msg.get("content") or ""), rounds=max_rounds, tool_calls=trace,
        model=str(resp.get("model", cfg.model)),
        prompt_tokens=usage.get("prompt_tokens"), completion_tokens=usage.get("completion_tokens"),
    )
