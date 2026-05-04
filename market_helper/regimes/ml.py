"""ML layer interfaces for Regime Engine v2.

The selector is intentionally separate from the classification layer so model
choice can evolve without changing orchestration.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Protocol, runtime_checkable


@dataclass(frozen=True)
class SelectedRegimeModel:
    model_type: str
    artifact_path: Path
    feature_schema: tuple[str, ...] = ()
    diagnostics: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ModelSelectionResult:
    selected: SelectedRegimeModel | None = None
    unavailable_reason: str | None = None

    @property
    def available(self) -> bool:
        return self.selected is not None


@runtime_checkable
class RegimeModelSelector(Protocol):
    def select_model(
        self,
        *,
        layer_name: str,
        config: Mapping[str, Any],
        available_features: tuple[str, ...] = (),
    ) -> ModelSelectionResult: ...


class ConfiguredRegimeModelSelector:
    """Resolve a model from layer config without training or inference."""

    def select_model(
        self,
        *,
        layer_name: str,
        config: Mapping[str, Any],
        available_features: tuple[str, ...] = (),
    ) -> ModelSelectionResult:
        model_type = str(config.get("model_type") or "svm").lower()
        if model_type != "svm":
            return ModelSelectionResult(
                unavailable_reason=f"{layer_name}: unsupported model_type {model_type!r}"
            )
        artifact_raw = config.get("model_artifact")
        if not artifact_raw:
            return ModelSelectionResult(
                unavailable_reason=f"{layer_name}: model_artifact not configured"
            )
        artifact_path = Path(str(artifact_raw))
        if not artifact_path.exists():
            return ModelSelectionResult(
                unavailable_reason=f"{layer_name}: model artifact not found: {artifact_path}"
            )
        required = tuple(str(item) for item in config.get("feature_schema", ()) or ())
        missing = [name for name in required if name not in set(available_features)]
        if missing:
            return ModelSelectionResult(
                unavailable_reason=f"{layer_name}: missing features: {', '.join(missing)}"
            )
        try:
            import sklearn  # noqa: F401
        except Exception as exc:  # pragma: no cover - depends on optional environment
            return ModelSelectionResult(
                unavailable_reason=f"{layer_name}: sklearn unavailable: {exc}"
            )
        return ModelSelectionResult(
            selected=SelectedRegimeModel(
                model_type=model_type,
                artifact_path=artifact_path,
                feature_schema=required,
                diagnostics={"selector": "configured", "layer_name": layer_name},
            )
        )


__all__ = [
    "ConfiguredRegimeModelSelector",
    "ModelSelectionResult",
    "RegimeModelSelector",
    "SelectedRegimeModel",
]
