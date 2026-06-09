"""Tactical Trade Ideas module — external brief as baseline + AI accumulation.

Two steps (devplan §5.3):

1. **Baseline** — the external **Tactical Edge** daily brief (parsed from the
   user's folder) plus the rule-based tactical anchors, displayed directly as the
   starting set of ideas.
2. **Accumulate (AI-led)** — the AI Plus dialog researches the anchors in several
   directions, calls read-only tools for fresh data, judges confidence, and
   proposes ideas; refine interactively. Read-only, never orders.

Tactical is idea-shaped, so it keeps the decision journal (Promote/Watch/Dismiss
+ the 30/60/90 ex-ante review loop) — that is what makes a promoted idea
verifiable later.
"""
from __future__ import annotations

import asyncio
import datetime as _dt

from nicegui import ui

from market_helper.trade_advisor.contracts import AdvisorContext, Suggestion

from ..ai_pane import render_ai_pane
from ..cards import _render_module


def build_tactical_suggestions(*, include_edge: bool = True, edge_root=None) -> list[Suggestion]:
    """Baseline tactical ideas: external Tactical Edge cards + rule-based anchors.

    Offline + graceful (the adapter swallows a missing brief / regime snapshot).
    """
    from market_helper.trade_advisor.adapters.tactical import TacticalIdeasPlugin

    context = AdvisorContext(as_of=_dt.date.today().isoformat())
    res = TacticalIdeasPlugin().produce(context, include_edge=include_edge, edge_root=edge_root)
    return list(res.suggestions)


def _tactical_ai_builder():
    """Initial messages for the tool-enabled tactical brief (the harness-selected prompt)."""
    from market_helper.domain.tactical_ideas import build_tactical_context, generate_tactical_ideas
    from market_helper.domain.tactical_ideas.ai_tools import build_tactical_tool_registry, tactical_tool_messages

    ctx = build_tactical_context()
    reg = build_tactical_tool_registry()
    return tactical_tool_messages(ctx, generate_tactical_ideas(ctx), reg), reg


def render_tactical_module(journal, refresh_inbox) -> None:
    """Render the Tactical module: baseline ideas (displayed on load) + AI accumulation."""
    ui.label("Tactical Trade Ideas").classes("text-subtitle1")
    ui.label(
        "Baseline from the external Tactical Edge brief + rule anchors; then accumulate your own with the AI. "
        "Independent directional trades — research-tier, never orders."
    ).classes("text-caption pm-muted")

    # 1) Baseline — populated just after load so the page stays responsive.
    with ui.card().classes("w-full pm-card"):
        ui.label("Baseline ideas · Tactical Edge brief + rule anchors").classes("text-subtitle2")
        baseline_box = ui.column().classes("w-full gap-3")
        with baseline_box:
            ui.label("Loading baseline ideas…").classes("text-caption pm-muted")

        async def _populate() -> None:
            try:
                suggestions = await asyncio.to_thread(lambda: build_tactical_suggestions(include_edge=True))
            except Exception as exc:  # noqa: BLE001 — surface, never crash the page
                baseline_box.clear()
                with baseline_box:
                    ui.label(f"Could not load baseline ideas: {type(exc).__name__}: {str(exc)[:160]}").classes(
                        "text-caption pm-muted"
                    )
                return
            _render_module(
                baseline_box, suggestions, journal, refresh_inbox,
                empty_note="No tactical baseline ideas fired for the current regime / brief.",
            )

        ui.timer(0.1, _populate, once=True)

    # 2) Accumulate — the AI Plus dialog.
    render_ai_pane(
        _tactical_ai_builder,
        intro="Opt-in: the AI synthesizes the anchors and may call read-only tools (regime / policy-expert / "
              "anchors / price-trend / tactical-edge) to research new ideas + judge confidence. After a brief, "
              "type feedback to refine — analysis only, never orders.",
        generate_label="Generate AI brief",
    )
