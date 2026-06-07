"""Tactical Trade Ideas — genuine short-term, non-option macro/market ideas.

The cockpit's most AI-leveraged module. A **rule-based signal layer** grounds a
set of tactical idea *anchors* on the offline regime snapshot + policy-expert
predictor/trending (de-dollarization / short-USD, risk-off / vol, short-VIX
carry, trend-persistence / add-exposure, curve steepeners, sector rotation,
commodity RV, JPY). An optional **AI synthesis layer** then researches and
expands those anchors into a tactical brief — pinned to the supplied context,
surfacing evidence + invalidation, and **never emitting an order**.

Honesty: these are *independent directional trades* (distinct from the Option
Strategy module's base-position overlays), advisory-only, capped at MONITOR.
"""

from .signals import (
    TacticalContext,
    TacticalIdea,
    build_tactical_context,
    generate_tactical_ideas,
)
from .synthesis import TacticalBrief, build_tactical_prompt, request_tactical_brief

__all__ = [
    "TacticalContext",
    "TacticalIdea",
    "build_tactical_context",
    "generate_tactical_ideas",
    "TacticalBrief",
    "build_tactical_prompt",
    "request_tactical_brief",
]
