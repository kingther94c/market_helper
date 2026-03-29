from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class PortfolioPositionView:
    internal_id: str
    quantity: float
    market_value: float | None = None
    weight: float | None = None
    asset_class: str = ""
    category: str = ""


@dataclass(frozen=True)
class PortfolioSnapshot:
    account_id: str
    as_of_date: str
    positions: list[PortfolioPositionView] = field(default_factory=list)
    market_values: dict[str, float] = field(default_factory=dict)
    pnl: dict[str, float] = field(default_factory=dict)
    exposures: dict[str, float] = field(default_factory=dict)
    allocation_views: dict[str, float] = field(default_factory=dict)
    risk_metrics: dict[str, Any] = field(default_factory=dict)
