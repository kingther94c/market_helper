from __future__ import annotations

from market_helper.common.datetime_display import format_local_datetime
from market_helper.presentation.dashboard.formatters import format_local_text


def test_format_local_datetime_displays_local_time_with_timezone() -> None:
    rendered = format_local_datetime("2026-04-22T00:00:00+00:00")

    assert rendered != "2026-04-22T00:00:00+00:00"
    assert "UTC" in rendered
    assert "(" in rendered
    assert ")" in rendered


def test_format_local_text_returns_na_for_empty_value() -> None:
    assert format_local_text(None) == "n/a"
