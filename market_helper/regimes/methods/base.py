"""Shared protocol and result dataclass for regime-detection methods.

A method is any implementation that, given a bundle of inputs, produces one
``MethodResult`` per date. Results carry a projected 2D :class:`QuadrantSnapshot`
so disparate methods can be compared, combined, or voted together by the
ensemble layer without the ensemble needing to know their internals.

Methods are free to also expose a ``native_label`` (e.g. the legacy 7-regime
name) and arbitrary ``native_detail`` diagnostics.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, List, Protocol, runtime_checkable

from market_helper.regimes.axes import QuadrantSnapshot


@dataclass(frozen=True)
class MethodResult:
    as_of: str
    method_name: str
    quadrant: QuadrantSnapshot
    native_label: str | None = None
    native_detail: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "as_of": self.as_of,
            "method_name": self.method_name,
            "quadrant": self.quadrant.to_dict(),
            "native_label": self.native_label,
            "native_detail": dict(self.native_detail),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "MethodResult":
        return cls(
            as_of=str(payload["as_of"]),
            method_name=str(payload["method_name"]),
            quadrant=QuadrantSnapshot.from_dict(dict(payload["quadrant"])),
            native_label=(
                str(payload["native_label"])
                if payload.get("native_label") is not None
                else None
            ),
            native_detail=dict(payload.get("native_detail", {})),
        )


@runtime_checkable
class RegimeMethod(Protocol):
    """Any regime-classification method the orchestrator can run.

    Implementations don't share a base class — duck typing is enough — but
    should stay stateless across ``classify`` calls so the orchestrator is
    free to parallelize or retry.
    """

    name: str

    def classify(self, *args: Any, **kwargs: Any) -> List[MethodResult]: ...


__all__ = ["MethodResult", "RegimeMethod"]
