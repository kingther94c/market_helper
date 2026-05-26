from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from market_helper.common.datetime_display import (
    compute_as_of_freshness_note,
    format_local_datetime,
)

_SGT = ZoneInfo("Asia/Singapore")


def test_fresh_returns_none():
    # 2026-05-05 14:00 SGT -> ET 2026-05-05 02:00 -> expected T-1 = 2026-05-04
    now = datetime(2026, 5, 5, 14, 0, tzinfo=_SGT)
    assert compute_as_of_freshness_note("2026-05-04", now=now) is None


def test_pending_t1_after_et_flip_edt():
    # 2026-05-05 14:00 SGT (EDT) -> ET 02:00 5/5 -> expected T-1 = 5/4
    now = datetime(2026, 5, 5, 14, 0, tzinfo=_SGT)
    note = compute_as_of_freshness_note("2026-05-01", now=now)
    assert note is not None
    assert "2026-05-04" in note
    assert "not yet published" in note


def test_before_et_flip_edt_threshold_is_noon_sgt():
    # 2026-05-05 09:00 SGT (EDT) -> ET still 5/4 -> expected T-1 = 5/1 (Fri)
    # but as_of=4/30 < 5/1 -> note triggers; threshold is ET-midnight today in SGT = 12:00
    now = datetime(2026, 5, 5, 9, 0, tzinfo=_SGT)
    note = compute_as_of_freshness_note("2026-04-30", now=now)
    assert note is not None
    assert "12:00 SGT" in note
    assert "T-2" in note


def test_before_et_flip_est_threshold_is_one_pm_sgt():
    # 2026-01-06 11:00 SGT (EST) -> ET 22:00 1/5 -> expected T-1 = 1/5
    # ET-midnight today (1/6) in SGT = 13:00 SGT
    now = datetime(2026, 1, 6, 11, 0, tzinfo=_SGT)
    note = compute_as_of_freshness_note("2026-01-02", now=now)
    assert note is not None
    assert "13:00 SGT" in note


def test_unparseable_returns_none():
    now = datetime(2026, 5, 5, 14, 0, tzinfo=_SGT)
    assert compute_as_of_freshness_note("not-a-date", now=now) is None
    assert compute_as_of_freshness_note(None, now=now) is None
    assert compute_as_of_freshness_note("", now=now) is None


def test_format_local_datetime_strips_os_tz_name() -> None:
    """The OS-supplied tz name (‟Malay Peninsula Standard Time", ‟Pacific
    Daylight Time", etc.) varies by OS locale + DST and adds visual noise;
    the report renders only the UTC offset. Pin this so a future cleanup
    doesn't bring the long names back."""
    rendered = format_local_datetime("2026-05-24T04:50:04+00:00")

    # The offset suffix is always present and bracketed.
    assert "(UTC" in rendered
    assert rendered.endswith(")")
    # The OS-supplied tz name must NOT leak. None of the platform-typical
    # tokens may appear inside the parens.
    paren_block = rendered[rendered.index("(") : rendered.index(")") + 1]
    for forbidden in (
        "Standard Time",
        "Daylight Time",
        "Malay Peninsula",
        "Pacific",
        "Eastern",
        "UTC,",  # the old ‟({tz_name}, UTC+...)" form would emit ‟Local, UTC+..."
    ):
        assert forbidden not in paren_block, f"unexpected {forbidden!r} in {paren_block!r}"


def test_format_local_datetime_handles_n_a_and_invalid() -> None:
    assert format_local_datetime(None) == "n/a"
    assert format_local_datetime("") == "n/a"
    # Unparseable strings pass through verbatim — keeps the original signal
    # rather than silently swallowing it.
    assert format_local_datetime("not-a-date") == "not-a-date"
