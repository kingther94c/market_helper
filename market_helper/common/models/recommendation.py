from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class RecommendationOutput:
    current_portfolio_state: dict[str, Any] = field(default_factory=dict)
    detected_regime: dict[str, Any] = field(default_factory=dict)
    scenario_assumptions: dict[str, Any] = field(default_factory=dict)
    vulnerabilities: list[str] = field(default_factory=list)
    suggested_overweights: list[str] = field(default_factory=list)
    suggested_underweights: list[str] = field(default_factory=list)
    watch_items: list[str] = field(default_factory=list)
    rationale: str = ""
