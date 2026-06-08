"""The Advisor cockpit: shared bounded inputs → one run → per-module tabs.

Reframes ``/advisor`` from an option page into a multi-module advisory cockpit —
**Option Strategy**, **FX Hedge Tilt**, **Tactical Trade Ideas**, and **Roll & Carry
Calendar** are peer *tabs* (but not peers in trust — each suggestion carries a
decision tier) over a single bounded-input run, so Option Strategy is one module,
not the centre. The Tactical tab additionally exposes an opt-in,
read-only **AI brief** (research/synthesis, never orders). The cross-module Inbox
+ decision journal + static snapshot are unchanged.
"""

from __future__ import annotations

import asyncio

from nicegui import ui

from market_helper.application.trade_advisor import TradeAdvisorService, current_regime_seed
from market_helper.presentation.dashboard.pages.trade_advisor.cards import _render_module
from market_helper.presentation.dashboard.pages.trade_advisor.inputs import (
    CONFIDENCE_OPTIONS,
    LIQUID_UNIVERSE,
    REGIME_OPTIONS,
    AdvisorInputs,
    build_run_context,
    option_run_params,
)
from market_helper.trade_advisor.journal import DecisionJournal

# Cockpit module tab → the advisor keys whose suggestions render in it.
_MODULES: list[tuple[str, tuple[str, ...]]] = [
    ("Option Strategy", ("option",)),
    ("FX Hedge Tilt", ("fx_hedge",)),
    ("Tactical Trade Ideas", ("tactical", "ideas")),
    ("Roll & Carry Calendar", ("roll", "futures_roll")),
]


def _render_tactical_ai() -> None:
    """Opt-in, read-only AI tactical brief at the top of the Tactical tab."""
    from market_helper.domain.tactical_ideas import build_tactical_context, generate_tactical_ideas
    from market_helper.domain.tactical_ideas.ai_tools import build_tactical_tool_registry, tactical_tool_messages
    from market_helper.trade_advisor.ai.gateway import GatewayAuthMissing, GatewayError
    from market_helper.trade_advisor.ai.tools import run_tool_chat

    convo: dict = {"messages": None, "reg": None}  # running history + tool registry once a brief exists

    with ui.card().classes("w-full pm-card"):
        with ui.row().classes("items-center justify-between w-full"):
            ui.label("AI tactical brief · research/synthesis, never orders").classes("text-subtitle2")
            gen_btn = ui.button("Generate AI brief").props("dense")
        transcript = ui.column().classes("w-full gap-2")
        with transcript:
            ui.label(
                "Opt-in: the AI synthesizes the grounded anchors and may call read-only tools "
                "(regime / policy-expert / anchors / price-trend) for more. After a brief, type feedback to "
                "refine it — analysis only, never orders."
            ).classes("text-caption pm-muted")
        with ui.row().classes("w-full items-center gap-2 wrap"):
            fb_in = ui.input(placeholder="Feedback to refine (e.g. “focus on the 2 best; check gold trend; be concise”)").props("dense").classes("grow")
            send_btn = ui.button("Send feedback").props("dense")
        fb_in.disable()
        send_btn.disable()

        def _add_turn(role: str, text: str, meta: str = "") -> None:
            with transcript:
                with ui.card().classes("w-full").style("background:rgba(255,255,255,.03)"):
                    ui.label("You" if role == "user" else "AI brief").classes("text-caption pm-muted")
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
            """Run the tool-enabled chat, append the brief to the transcript + history. Graceful."""
            with transcript:
                pending = ui.label("Synthesizing… (the AI may call read-only tools)").classes("text-caption pm-muted")
            try:
                res = await asyncio.to_thread(
                    lambda: run_tool_chat(messages=messages, registry=convo["reg"], inject_protocol=False, max_rounds=3)
                )
            except GatewayAuthMissing:
                pending.delete()
                _explain("AI disabled — start the OpenClaw gateway / set OPENCLAW_GATEWAY_TOKEN. "
                         "The rule-based tactical anchors below are unaffected.")
                return
            except (GatewayError, Exception) as exc:  # noqa: BLE001 — UI must never crash
                pending.delete()
                _explain(f"AI brief unavailable: {type(exc).__name__}: {str(exc)[:160]}")
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
            fb_in.enable()
            send_btn.enable()

        async def generate() -> None:
            gen_btn.disable()
            transcript.clear()
            convo["messages"] = None
            convo["reg"] = None
            fb_in.disable()
            send_btn.disable()

            def _build():
                ctx = build_tactical_context()
                reg = build_tactical_tool_registry()
                return tactical_tool_messages(ctx, generate_tactical_ideas(ctx), reg), reg

            messages, reg = await asyncio.to_thread(_build)
            convo["reg"] = reg
            await _ask(messages)
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


def render_cockpit(journal: DecisionJournal, refresh_inbox, service: TradeAdvisorService) -> None:
    """Inputs + single run distributed across the four module tabs."""
    with ui.row().classes("w-full gap-4 items-start no-wrap"):
        with ui.card().classes("p-4").style("min-width: 300px"):
            ui.label("Inputs").classes("text-subtitle1")
            sym_sel = ui.select(LIQUID_UNIVERSE, value=["SPY", "QQQ"], multiple=True, label="Universe").props("use-chips").classes("w-full")
            held_sel = ui.select(LIQUID_UNIVERSE, value=["SPY"], multiple=True, label="Treat as held (100 sh)").props("use-chips").classes("w-full")
            aum_in = ui.number("AUM (USD)", value=250_000, min=0, step=10_000, format="%.0f").classes("w-full")
            seed = current_regime_seed()  # default the regime controls to the live snapshot (overridable)
            regime_sel = ui.select(REGIME_OPTIONS, value=seed.regime, label="Regime").classes("w-full")
            conf_sel = ui.select(CONFIDENCE_OPTIONS, value=seed.confidence, label="Confidence").classes("w-full")
            crisis_sw = ui.switch("Crisis overlay", value=seed.crisis)
            if seed.is_seeded:
                ui.label(
                    f"Regime auto-seeded: {seed.regime}"
                    f"{' · ' + seed.confidence if seed.confidence else ''}"
                    f"{' · stress overlay' if seed.crisis else ''} (override above)"
                ).classes("text-caption pm-muted")
            rv_sw = ui.switch("Fetch realized vol (slower)", value=False)
            earnings_sw = ui.switch("Check earnings (slower)", value=False)
            portfolio_sw = ui.switch("Use my portfolio (live positions)", value=True)
            run_btn = ui.button("Run advisor")
            status = ui.label("").classes("text-caption pm-muted")

        with ui.column().classes("grow gap-2"):
            with ui.tabs().classes("w-full") as tabs:
                tab_objs = [(name, ui.tab(name)) for name, _ in _MODULES]
            boxes: dict[str, object] = {}
            with ui.tab_panels(tabs, value=tab_objs[0][1]).classes("w-full"):
                for (name, _keys), (_, tab) in zip(_MODULES, tab_objs):
                    with ui.tab_panel(tab):
                        if name.startswith("Tactical"):
                            _render_tactical_ai()
                        boxes[name] = ui.column().classes("w-full gap-3")
                        with boxes[name]:
                            ui.label("Run the advisor to populate this module.").classes("text-caption pm-muted")

    async def run() -> None:
        run_btn.disable()
        status.text = "Running…"
        inp = AdvisorInputs(
            symbols=list(sym_sel.value or []),
            held=list(held_sel.value or []),
            aum=float(aum_in.value or 0),
            regime=regime_sel.value or "",
            confidence=conf_sel.value or "",
            crisis=bool(crisis_sw.value),
            fetch_realized=bool(rv_sw.value),
            check_earnings=bool(earnings_sw.value),
        )
        if not inp.symbols:
            status.text = "Pick at least one symbol."
            run_btn.enable()
            return
        context, book_note = build_run_context(inp, use_portfolio=bool(portfolio_sw.value))
        try:
            run_result = await asyncio.to_thread(
                service.run, context, advisors=None, params_by_advisor=option_run_params(inp)
            )
        except Exception as exc:  # noqa: BLE001 — surface, don't crash the page
            status.text = f"Failed: {type(exc).__name__}: {exc}"
            run_btn.enable()
            return
        all_s = run_result.all_suggestions()
        for name, keys in _MODULES:
            _render_module(
                boxes[name], [s for s in all_s if s.advisor in keys], journal, refresh_inbox,
                empty_note=f"No {name} ideas for these inputs.",
            )
        modes = ", ".join(sorted({r.data_mode for r in run_result.results.values() if r.data_mode})) or "n/a"
        status.text = f"Done · {len(all_s)} ideas · data: {modes}{book_note}"
        run_btn.enable()

    run_btn.on_click(run)
