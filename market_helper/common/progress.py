from __future__ import annotations

from dataclasses import dataclass
import io
import sys
from typing import Protocol, TextIO


class ProgressReporter(Protocol):
    def stage(self, label: str, *, current: int | None = None, total: int | None = None) -> None: ...

    def update(self, label: str, *, completed: int, total: int, detail: str | None = None) -> None: ...

    def spinner(self, label: str, *, detail: str | None = None) -> None: ...

    def child(self, label: str) -> "ProgressReporter": ...

    def done(self, label: str, *, detail: str | None = None) -> None: ...


class NullProgressReporter:
    def stage(self, label: str, *, current: int | None = None, total: int | None = None) -> None:
        return None

    def update(self, label: str, *, completed: int, total: int, detail: str | None = None) -> None:
        return None

    def spinner(self, label: str, *, detail: str | None = None) -> None:
        return None

    def child(self, label: str) -> "NullProgressReporter":
        return self

    def done(self, label: str, *, detail: str | None = None) -> None:
        return None


@dataclass
class TerminalProgressReporter:
    stream: TextIO
    prefix: str = ""
    is_tty: bool = True
    width: int = 20

    _SPINNER_FRAMES = ("-", "\\", "|", "/")

    def __post_init__(self) -> None:
        self._spinner_index = 0
        self._active_line = False

    def stage(self, label: str, *, current: int | None = None, total: int | None = None) -> None:
        if current is not None and total is not None:
            self._write_line(f"{self._label(label)} [{current}/{total}]")
            return
        self._write_line(self._label(label))

    def update(self, label: str, *, completed: int, total: int, detail: str | None = None) -> None:
        clamped_total = max(total, 0)
        clamped_completed = min(max(completed, 0), clamped_total) if clamped_total > 0 else 0
        if clamped_total <= 0:
            self._write_line(self._join_parts(self._label(label), detail))
            return
        filled = int((clamped_completed / clamped_total) * self.width)
        bar = f"[{'#' * filled}{'.' * (self.width - filled)}]"
        counter = f"{clamped_completed}/{clamped_total}"
        self._write_line(self._join_parts(self._label(label), bar, counter, detail))

    def spinner(self, label: str, *, detail: str | None = None) -> None:
        frame = self._SPINNER_FRAMES[self._spinner_index % len(self._SPINNER_FRAMES)]
        self._spinner_index += 1
        self._write_line(self._join_parts(self._label(label), frame, detail))

    def child(self, label: str) -> "TerminalProgressReporter":
        child_prefix = self.prefix
        if label.strip():
            child_prefix = f"{child_prefix}{label.strip()} > "
        return TerminalProgressReporter(
            stream=self.stream,
            prefix=child_prefix,
            is_tty=self.is_tty,
            width=self.width,
        )

    def done(self, label: str, *, detail: str | None = None) -> None:
        self._write_line(self._join_parts(self._label(label), "done", detail), finalize=True)

    def _label(self, label: str) -> str:
        return f"{self.prefix}{label.strip()}".strip()

    def _write_line(self, message: str, *, finalize: bool = False) -> None:
        if not self.is_tty:
            self.stream.write(f"{message}\n")
            self.stream.flush()
            self._active_line = False
            return
        prefix = "\r" if self._active_line else ""
        self.stream.write(f"{prefix}{message}")
        self.stream.write("\n")
        if finalize:
            self._active_line = False
        else:
            self._active_line = False
        self.stream.flush()

    @staticmethod
    def _join_parts(*parts: str | None) -> str:
        return " ".join(part for part in parts if part)


class RecordingProgressReporter:
    def __init__(self, *, prefix: str = "") -> None:
        self.prefix = prefix
        self.events: list[dict[str, object]] = []

    def stage(self, label: str, *, current: int | None = None, total: int | None = None) -> None:
        self.events.append(
            {
                "kind": "stage",
                "label": self._label(label),
                "current": current,
                "total": total,
            }
        )

    def update(self, label: str, *, completed: int, total: int, detail: str | None = None) -> None:
        self.events.append(
            {
                "kind": "update",
                "label": self._label(label),
                "completed": completed,
                "total": total,
                "detail": detail,
            }
        )

    def spinner(self, label: str, *, detail: str | None = None) -> None:
        self.events.append(
            {
                "kind": "spinner",
                "label": self._label(label),
                "detail": detail,
            }
        )

    def child(self, label: str) -> "RecordingProgressReporter":
        child_prefix = self.prefix
        if label.strip():
            child_prefix = f"{child_prefix}{label.strip()} > "
        child = RecordingProgressReporter(prefix=child_prefix)
        child.events = self.events
        return child

    def done(self, label: str, *, detail: str | None = None) -> None:
        self.events.append(
            {
                "kind": "done",
                "label": self._label(label),
                "detail": detail,
            }
        )

    def _label(self, label: str) -> str:
        return f"{self.prefix}{label.strip()}".strip()


def resolve_progress_reporter(
    progress: ProgressReporter | None = None,
    *,
    stream: TextIO | None = None,
) -> ProgressReporter:
    if progress is not None:
        return progress
    target_stream = stream or sys.stderr
    is_tty = _safe_isatty(target_stream)
    if not is_tty:
        return NullProgressReporter()
    return TerminalProgressReporter(stream=target_stream, is_tty=True)


def _safe_isatty(stream: TextIO) -> bool:
    try:
        return bool(stream.isatty())
    except (AttributeError, io.UnsupportedOperation):
        return False


__all__ = [
    "NullProgressReporter",
    "ProgressReporter",
    "RecordingProgressReporter",
    "TerminalProgressReporter",
    "resolve_progress_reporter",
]
