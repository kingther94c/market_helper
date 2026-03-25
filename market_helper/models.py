from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass(frozen=True)
class Observation:
    date: str
    value: float


@dataclass(frozen=True)
class EconomicSeries:
    series_id: str
    title: str
    units: str
    frequency: str
    observations: List[Observation]
    metadata: Dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class NewsItem:
    source: str
    title: str
    url: str
    published_at: Optional[str]
    summary: str = ""
