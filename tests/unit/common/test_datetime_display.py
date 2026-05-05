from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from market_helper.common.datetime_display import compute_as_of_freshness_note

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
