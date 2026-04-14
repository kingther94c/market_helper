from __future__ import annotations

from dataclasses import dataclass, field

from market_helper.application.portfolio_monitor.contracts import UiProgressEvent, UiProgressSink


@dataclass
class InMemoryUiProgressSink:
    events: list[UiProgressEvent] = field(default_factory=list)

    def record(self, event: UiProgressEvent) -> None:
        self.events.append(event)

    def clear(self) -> None:
        self.events.clear()


class UiProgressReporterAdapter:
    def __init__(self, sink: UiProgressSink | None = None, *, prefix: str = "") -> None:
        self.sink = sink
        self.prefix = prefix

    def stage(self, label: str, *, current: int | None = None, total: int | None = None) -> None:
        self._record(UiProgressEvent(kind="stage", label=self._label(label), current=current, total=total))

    def update(self, label: str, *, completed: int, total: int, detail: str | None = None) -> None:
        self._record(
            UiProgressEvent(
                kind="update",
                label=self._label(label),
                completed=completed,
                total=total,
                detail=detail,
            )
        )

    def spinner(self, label: str, *, detail: str | None = None) -> None:
        self._record(UiProgressEvent(kind="spinner", label=self._label(label), detail=detail))

    def child(self, label: str) -> "UiProgressReporterAdapter":
        child_prefix = self.prefix
        if label.strip():
            child_prefix = f"{child_prefix}{label.strip()} > "
        return UiProgressReporterAdapter(self.sink, prefix=child_prefix)

    def done(self, label: str, *, detail: str | None = None) -> None:
        self._record(UiProgressEvent(kind="done", label=self._label(label), detail=detail))

    def _record(self, event: UiProgressEvent) -> None:
        if self.sink is not None:
            self.sink.record(event)

    def _label(self, label: str) -> str:
        return f"{self.prefix}{label.strip()}".strip()

