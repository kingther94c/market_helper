from __future__ import annotations

import io

from market_helper.common.progress import (
    NullProgressReporter,
    RecordingProgressReporter,
    TerminalProgressReporter,
    resolve_progress_reporter,
)


class FakeTty(io.StringIO):
    def isatty(self) -> bool:
        return True


def test_resolve_progress_reporter_returns_null_for_non_tty_stream() -> None:
    reporter = resolve_progress_reporter(stream=io.StringIO())

    assert isinstance(reporter, NullProgressReporter)


def test_terminal_progress_reporter_writes_ascii_lines() -> None:
    stream = FakeTty()
    reporter = TerminalProgressReporter(stream=stream, is_tty=True)

    reporter.stage("Risk HTML", current=1, total=4)
    reporter.update("Yahoo returns", completed=2, total=5, detail="SPY fetched")
    reporter.spinner("Flex polling", detail="2024 attempt 1/3")
    reporter.done("Risk HTML", detail="wrote report.html")

    output = stream.getvalue()
    assert "Risk HTML [1/4]" in output
    assert "Yahoo returns [########............] 2/5 SPY fetched" in output
    assert "Flex polling - 2024 attempt 1/3" in output
    assert "Risk HTML done wrote report.html" in output


def test_recording_progress_reporter_preserves_child_prefix() -> None:
    reporter = RecordingProgressReporter()
    child = reporter.child("Returns")

    reporter.stage("Risk HTML", current=1, total=3)
    child.update("Yahoo returns", completed=1, total=2, detail="SPY cached")

    assert reporter.events == [
        {"kind": "stage", "label": "Risk HTML", "current": 1, "total": 3},
        {
            "kind": "update",
            "label": "Returns > Yahoo returns",
            "completed": 1,
            "total": 2,
            "detail": "SPY cached",
        },
    ]
