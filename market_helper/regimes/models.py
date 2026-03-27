from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class IndicatorPoint:
    """Single timestamped indicator reading."""

    as_of: str
    name: str
    value: float
    source: str = "unknown"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class FactorSnapshot:
    """Computed normalized factor scores used by the regime rulebook."""

    as_of: str
    vol: float
    credit: float
    rates: float
    growth: float
    trend: float
    stress: float
    inputs: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RegimeSnapshot:
    """Resolved mutually-exclusive regime state at one timestamp."""

    as_of: str
    regime: str
    scores: dict[str, float]
    inputs: dict[str, float]
    flags: dict[str, bool]
    version: str = "regime-v1"
    diagnostics: dict[str, Any] | None = None
    source_info: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "RegimeSnapshot":
        return cls(
            as_of=str(payload["as_of"]),
            regime=str(payload["regime"]),
            scores={str(k): float(v) for k, v in dict(payload.get("scores", {})).items()},
            inputs={str(k): float(v) for k, v in dict(payload.get("inputs", {})).items()},
            flags={str(k): bool(v) for k, v in dict(payload.get("flags", {})).items()},
            version=str(payload.get("version", "regime-v1")),
            diagnostics=dict(payload["diagnostics"]) if isinstance(payload.get("diagnostics"), dict) else None,
            source_info=dict(payload["source_info"]) if isinstance(payload.get("source_info"), dict) else None,
        )
