"""The opt-in AI+ tab: rule-based context + ideas → OpenClaw synthesis.

Parallel to (never replacing) the rule-based tab. Read-only — analysis text only.
Degrades to an explainer when the gateway token is unset/unreachable. Controls
stay bounded (model select + include-ideas switch; no free-text prompt).
"""
from __future__ import annotations

import asyncio

from nicegui import ui

from market_helper.application.trade_advisor import TradeAdvisorService, current_regime_seed
from market_helper.trade_advisor.ai import (
    GatewayAuthMissing,
    GatewayConfig,
    GatewayError,
    request_ai_advisory,
    resolve_gateway_token,
)
from market_helper.trade_advisor.contracts import Suggestion
from market_helper.presentation.dashboard.pages.trade_advisor.inputs import (
    CONFIDENCE_OPTIONS,
    LIQUID_UNIVERSE,
    REGIME_OPTIONS,
    AdvisorInputs,
    build_run_context,
)

# AI+ tab: bounded model choices (the OpenClaw gateway routes these ids to personas).
AI_MODELS = ["openclaw/trade-advisor", "openclaw/trade-advisor-panel"]


def _render_ai_unavailable(box, message: str) -> None:
    box.clear()
    with box:
        with ui.card().classes("w-full pm-card"):
            ui.label("AI+ unavailable").classes("text-subtitle1")
            ui.label(message).classes("text-caption pm-muted")


def _render_ai_advisory(box, advisory, *, book_note: str = "", n_ideas: int = 0) -> None:
    box.clear()
    with box:
        with ui.card().classes("w-full pm-card"):
            with ui.row().classes("items-center gap-2"):
                ui.badge("AI+", color="purple")
                ui.label("AI-generated synthesis · analysis only, not orders").classes("text-caption pm-muted")
            meta = f"model {advisory.model}"
            if advisory.prompt_tokens is not None:
                meta += f" · tokens {advisory.prompt_tokens}+{advisory.completion_tokens or 0}"
            meta += f" · {n_ideas} rule-based ideas in context{book_note}"
            ui.label(meta).classes("text-caption pm-muted")
            # Display-only rendering of the gateway's own output (no execution).
            ui.markdown(advisory.advice).classes("w-full")


def _render_ai_tab(service: TradeAdvisorService) -> None:
    """The opt-in AI+ surface: rule-based context + ideas → OpenClaw synthesis.

    Parallel to (never replacing) the rule-based tab. Read-only — analysis text
    only. Degrades to an explainer when the gateway token is unset/unreachable.
    """
    token_present = bool(resolve_gateway_token())
    with ui.row().classes("w-full gap-4 items-start no-wrap"):
        with ui.card().classes("p-4").style("min-width: 300px"):
            ui.label("AI+ inputs").classes("text-subtitle1")
            ui.label(
                "Synthesizes the rule-based ideas + your book + regime via the local "
                "OpenClaw gateway. Analysis only — never orders."
            ).classes("text-caption pm-muted")
            sym_sel = ui.select(LIQUID_UNIVERSE, value=["SPY", "QQQ"], multiple=True, label="Universe").props("use-chips").classes("w-full")
            held_sel = ui.select(LIQUID_UNIVERSE, value=["SPY"], multiple=True, label="Treat as held (100 sh)").props("use-chips").classes("w-full")
            aum_in = ui.number("AUM (USD)", value=250_000, min=0, step=10_000, format="%.0f").classes("w-full")
            seed = current_regime_seed()
            regime_sel = ui.select(REGIME_OPTIONS, value=seed.regime, label="Regime").classes("w-full")
            conf_sel = ui.select(CONFIDENCE_OPTIONS, value=seed.confidence, label="Confidence").classes("w-full")
            crisis_sw = ui.switch("Crisis overlay", value=seed.crisis)
            portfolio_sw = ui.switch("Use my portfolio (live positions)", value=True)
            model_sel = ui.select(AI_MODELS, value=AI_MODELS[0], label="AI model").classes("w-full")
            include_ideas_sw = ui.switch("Include rule-based ideas as context", value=True)
            gen_btn = ui.button("Generate AI advisory")
            status = ui.label(
                "" if token_present
                else "AI+ disabled — set OPENCLAW_GATEWAY_TOKEN and start the OpenClaw gateway."
            ).classes("text-caption pm-muted")

        out_box = ui.column().classes("grow gap-3")

    async def generate() -> None:
        gen_btn.disable()
        status.text = "Thinking…"
        out_box.clear()
        inp = AdvisorInputs(
            symbols=list(sym_sel.value or []),
            held=list(held_sel.value or []),
            aum=float(aum_in.value or 0),
            regime=regime_sel.value or "",
            confidence=conf_sel.value or "",
            crisis=bool(crisis_sw.value),
        )
        if not inp.symbols:
            status.text = "Pick at least one symbol."
            gen_btn.enable()
            return
        context, book_note = build_run_context(inp, use_portfolio=bool(portfolio_sw.value))
        suggestions: list[Suggestion] = []
        if include_ideas_sw.value:
            try:
                run_result = await asyncio.to_thread(service.run, context, advisors=None)
                suggestions = run_result.all_suggestions()
            except Exception:  # noqa: BLE001 — AI can still run on context alone
                suggestions = []
        config = GatewayConfig.from_env(model=str(model_sel.value or AI_MODELS[0]))
        try:
            advisory = await asyncio.to_thread(
                request_ai_advisory, context=context, suggestions=suggestions, config=config,
            )
        except GatewayAuthMissing:
            _render_ai_unavailable(
                out_box,
                "AI+ needs OPENCLAW_GATEWAY_TOKEN. Set it in the environment or local.env, "
                "then start the OpenClaw gateway.",
            )
            status.text = "AI+ disabled (no token)."
            gen_btn.enable()
            return
        except GatewayError as exc:
            _render_ai_unavailable(out_box, f"Could not reach the OpenClaw gateway: {exc}")
            status.text = "Gateway error."
            gen_btn.enable()
            return
        except Exception as exc:  # noqa: BLE001 — never crash the page
            _render_ai_unavailable(out_box, f"AI+ failed: {type(exc).__name__}: {exc}")
            status.text = "Failed."
            gen_btn.enable()
            return
        _render_ai_advisory(out_box, advisory, book_note=book_note, n_ideas=len(suggestions))
        status.text = f"Done · {advisory.model}{book_note}"
        gen_btn.enable()

    gen_btn.on_click(generate)
