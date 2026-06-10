"""Reusable **AI Plus** pane — a read-only, tool-enabled dialog any module embeds.

Generalizes the original Tactical AI brief into a component: a module supplies an
``initial_builder()`` returning ``(messages, registry)`` (messages already framed +
protocol-injected when the module wants tools); the pane runs the tool-chat,
renders the transcript, and offers a feedback box to **iteratively refine** — the
interactive-feedback mechanism the v2 plan asks for on every AI pane.

Read-only invariant: the AI may only call registered read-only tools and never
emits orders. Any gateway/auth failure degrades gracefully — the module's
rule-based pane is unaffected.
"""
from __future__ import annotations

import asyncio
from typing import Callable

from nicegui import ui

from market_helper.trade_advisor.ai.gateway import GatewayAuthMissing, GatewayError
from market_helper.trade_advisor.ai.tools import run_tool_chat

# An initial_builder returns (messages, registry|None). It runs off-thread, so it
# may do blocking work (assemble context, build a tool registry).
InitialBuilder = Callable[[], "tuple[list[dict], object]"]


def module_ai_initial(
    system_framing: str,
    user_ask: str,
    *,
    knowledge_names: "list[str] | None" = None,
    with_tools: bool = True,
):
    """Assemble ``(messages, registry)`` for a module's AI Plus pane.

    Grounds the AI on the core knowledge (the read-only invariant is always
    included) plus the module's own framing, and — when ``with_tools`` — bakes the
    read-only tool protocol into the system turn so the pane can run with
    ``inject_protocol=False`` (the persistent-conversation contract). The tools are
    the shared read-only set (regime / policy-expert / anchors / price-trend /
    tactical-edge), which are generically useful to every module.
    """
    from market_helper.trade_advisor.ai.skills import build_core_knowledge, knowledge_system_block

    names = knowledge_names if knowledge_names is not None else ["read_only_invariant", "data_mode_ladder", "cockpit_modules"]
    system = system_framing.strip()
    block = knowledge_system_block(build_core_knowledge(), names=names)
    if block:
        system += "\n\n" + block

    registry = None
    if with_tools:
        from market_helper.domain.tactical_ideas.ai_tools import build_tactical_tool_registry
        from market_helper.trade_advisor.ai.tools import tool_protocol_instructions

        registry = build_tactical_tool_registry()
        system += tool_protocol_instructions(registry)

    return [{"role": "system", "content": system}, {"role": "user", "content": user_ask}], registry


def render_ai_pane(
    initial_builder: InitialBuilder,
    *,
    intro: str,
    generate_label: str = "Generate",
    feedback_placeholder: str = "Feedback to refine (e.g. “focus on the 2 best; be concise”)",
    max_rounds: int = 3,
    capture_parser: "Callable[[str], list] | None" = None,
    on_capture: "Callable[[list], None] | None" = None,
    capture_label: str = "Capture ideas → cards",
) -> None:
    """Render an opt-in AI dialog: Generate → brief → feedback → refine.

    ``initial_builder`` is the only module-specific seam: it returns the initial
    chat ``messages`` and a read-only tool ``registry`` (or ``None``). Everything
    else — transcript, tool-trace disclosure, feedback loop, graceful degradation —
    is shared. The pane never injects the tool protocol itself (the builder owns the
    system framing), mirroring the persistent-conversation contract of
    :func:`run_tool_chat` (``inject_protocol=False``).

    **Capture seam (v2.1):** when ``capture_parser`` + ``on_capture`` are given,
    every AI turn is parsed for structured idea blocks; a found batch surfaces a
    one-click capture button that hands the parsed items to the module (which
    renders them as journal-able cards). This is what stops good AI output from
    evaporating with the dialog.
    """
    convo: dict = {"messages": None, "reg": None}  # running history + tool registry once a brief exists

    with ui.card().classes("w-full pm-card"):
        with ui.row().classes("items-center justify-between w-full"):
            ui.label("AI Plus · research / synthesis, never orders").classes("text-subtitle2")
            gen_btn = ui.button(generate_label).props("dense")
        transcript = ui.column().classes("w-full gap-2")
        with transcript:
            ui.label(intro).classes("text-caption pm-muted")
        with ui.row().classes("w-full items-center gap-2 wrap"):
            fb_in = ui.input(placeholder=feedback_placeholder).props("dense").classes("grow")
            send_btn = ui.button("Send feedback").props("dense")
        fb_in.disable()
        send_btn.disable()

        def _add_turn(role: str, text: str, meta: str = "") -> None:
            with transcript:
                with ui.card().classes("w-full").style("background:rgba(255,255,255,.03)"):
                    ui.label("You" if role == "user" else "AI").classes("text-caption pm-muted")
                    if role == "user":
                        ui.label(text).classes("text-body2")
                    else:
                        ui.markdown(text or "_(empty response)_")
                        if meta:
                            ui.label(meta).classes("text-caption pm-muted")

        def _explain(msg: str) -> None:
            with transcript:
                ui.label(msg).classes("text-caption pm-muted")

        async def _ask(messages: list) -> None:
            """Run the tool-enabled chat, append the answer to the transcript + history. Graceful."""
            with transcript:
                pending = ui.label("Synthesizing… (the AI may call read-only tools)").classes("text-caption pm-muted")
            try:
                res = await asyncio.to_thread(
                    lambda: run_tool_chat(messages=messages, registry=convo["reg"], inject_protocol=False, max_rounds=max_rounds)
                )
            except GatewayAuthMissing:
                pending.delete()
                _explain("AI disabled — start the OpenClaw gateway / set OPENCLAW_GATEWAY_TOKEN. "
                         "The rule-based pane is unaffected.")
                return
            except (GatewayError, Exception) as exc:  # noqa: BLE001 — UI must never crash
                pending.delete()
                _explain(f"AI unavailable: {type(exc).__name__}: {str(exc)[:160]}")
                return
            pending.delete()
            convo["messages"] = [*messages, {"role": "assistant", "content": res.text}]
            tools_used = ", ".join(dict.fromkeys(t["name"] for t in res.tool_calls))
            bits = []
            if tools_used:
                bits.append(f"tools called: {tools_used}")
            if res.model:
                bits.append(f"model {res.model} · {res.prompt_tokens}/{res.completion_tokens} tok")
            bits.append("analysis only, not orders")
            _add_turn("assistant", res.text, " · ".join(bits))
            _offer_capture(res.text)
            fb_in.enable()
            send_btn.enable()

        def _offer_capture(text: str) -> None:
            """Surface a one-click capture button when the turn carries idea blocks."""
            if capture_parser is None or on_capture is None:
                return
            try:
                items = capture_parser(text or "")
            except Exception:  # noqa: BLE001 — a parser bug must not break the dialog
                return
            if not items:
                return
            with transcript:
                with ui.row().classes("items-center gap-2"):
                    n = len(items)
                    btn = ui.button(f"{capture_label} ({n})").props("dense outline")

                    def _do_capture() -> None:
                        try:
                            on_capture(items)
                        except Exception as exc:  # noqa: BLE001 — surface, don't crash
                            _explain(f"Capture failed: {type(exc).__name__}: {str(exc)[:120]}")
                            return
                        btn.disable()
                        btn.text = f"Captured {n} idea{'s' if n > 1 else ''} ✓"

                    btn.on_click(_do_capture)

        async def generate() -> None:
            gen_btn.disable()
            transcript.clear()
            convo["messages"] = None
            convo["reg"] = None
            fb_in.disable()
            send_btn.disable()
            try:
                messages, reg = await asyncio.to_thread(initial_builder)
                convo["reg"] = reg
                await _ask(messages)
            except Exception as exc:  # noqa: BLE001 — the Generate button must never wedge disabled
                _explain(f"Could not build the brief: {type(exc).__name__}: {str(exc)[:160]}")
            finally:
                gen_btn.enable()

        async def send_feedback() -> None:
            fb = (fb_in.value or "").strip()
            if not fb or not convo["messages"]:
                return
            send_btn.disable()
            fb_in.value = ""
            _add_turn("user", fb)
            await _ask([*convo["messages"], {"role": "user", "content": fb}])
            send_btn.enable()

        gen_btn.on_click(generate)
        send_btn.on_click(send_feedback)
