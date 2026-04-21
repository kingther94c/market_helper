from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from market_helper.regimes.axes import QuadrantSnapshot
from market_helper.regimes.methods.base import MethodResult


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


@dataclass(frozen=True)
class MultiMethodRegimeSnapshot:
    """Per-date output of the multi-method regime orchestrator.

    ``per_method`` keeps each method's native view (including its richer label,
    e.g. the legacy 7-regime string) alongside the projected 2D quadrant;
    ``ensemble`` is the voted consensus. Downstream policy / reporting layers
    use ``ensemble`` as the primary signal and ``per_method`` to show
    disagreement.
    """

    as_of: str
    per_method: dict[str, MethodResult]
    ensemble: QuadrantSnapshot
    source_info: dict[str, Any] = field(default_factory=dict)
    version: str = "regime-multi-v1"

    def to_dict(self) -> dict[str, Any]:
        return {
            "as_of": self.as_of,
            "per_method": {
                name: result.to_dict() for name, result in self.per_method.items()
            },
            "ensemble": self.ensemble.to_dict(),
            "source_info": dict(self.source_info),
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "MultiMethodRegimeSnapshot":
        per_method_raw = dict(payload.get("per_method", {}))
        per_method = {
            str(name): MethodResult.from_dict(dict(entry))
            for name, entry in per_method_raw.items()
        }
        return cls(
            as_of=str(payload["as_of"]),
            per_method=per_method,
            ensemble=QuadrantSnapshot.from_dict(dict(payload["ensemble"])),
            source_info=dict(payload.get("source_info", {})),
            version=str(payload.get("version", "regime-multi-v1")),
        )
