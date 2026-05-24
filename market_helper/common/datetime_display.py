from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo


def format_local_datetime(value: str | None) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        return "n/a"
    parsed = _parse_datetime(normalized)
    if parsed is None:
        return normalized
    local_dt = parsed.astimezone()
    tz_name = local_dt.tzname() or "Local"
    return f"{local_dt.strftime('%Y-%m-%d %H:%M:%S')} ({tz_name}, {_format_utc_offset(local_dt)})"


def _parse_datetime(value: str) -> datetime | None:
    normalized = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.astimezone()
    return parsed


_ET_TZ = ZoneInfo("America/New_York")
_SGT_TZ = ZoneInfo("Asia/Singapore")


def expected_t1_date(now: datetime | None = None):
    """Return the latest trading day we expect data to cover.

    T-1 in SGT-anchored terms — the previous weekday relative to today's
    SGT date. Shared by `compute_as_of_freshness_note` (report-level) and
    `is_as_of_stale` (per-artifact, used by the regime provider) so the two
    can't drift.
    """
    now_dt = now or datetime.now(timezone.utc)
    if now_dt.tzinfo is None:
        now_dt = now_dt.astimezone()
    now_sgt = now_dt.astimezone(_SGT_TZ)
    return _previous_or_same_weekday(now_sgt.date() - timedelta(days=1))


def is_as_of_stale(
    as_of: str | None,
    *,
    now: datetime | None = None,
) -> bool:
    """True when ``as_of`` is older than the expected T-1 trading day.

    Boolean predicate shared between the regime provider (drives the stale
    state + the refresh-if-stale trigger) and `compute_as_of_freshness_note`
    (drives the report's small-text freshness hint). Unparseable inputs are
    treated as **stale** so producers must supply a real timestamp.
    """
    parsed = _parse_datetime(str(as_of or "").strip())
    if parsed is None:
        return True
    return parsed.date() < expected_t1_date(now=now)


def compute_as_of_freshness_note(
    as_of: str | None,
    *,
    now: datetime | None = None,
) -> str | None:
    """Return a small-text note explaining why a report's as_of lags T-1.

    Returns None when the report is fresh (as_of >= expected T-1 in ET) or
    when as_of cannot be parsed.
    """
    parsed = _parse_datetime(str(as_of or "").strip())
    if parsed is None:
        return None
    as_of_date = parsed.date()
    now_dt = now or datetime.now(timezone.utc)
    if now_dt.tzinfo is None:
        now_dt = now_dt.astimezone()
    now_et = now_dt.astimezone(_ET_TZ)
    expected_t1 = expected_t1_date(now=now_dt)
    if as_of_date >= expected_t1:
        return None
    flex_baseline = _previous_or_same_weekday(now_et.date() - timedelta(days=1))
    if flex_baseline < expected_t1:
        flip_sgt = datetime.combine(
            expected_t1 + timedelta(days=1), time.min, tzinfo=_ET_TZ
        ).astimezone(_SGT_TZ)
        threshold = flip_sgt.strftime("%H:%M")
        return (
            f"Run before {threshold} SGT — IBKR Flex baseline is T-2 until ET "
            f"crosses midnight. Re-run after {threshold} SGT for T-1."
        )
    return (
        f"Latest trading day ({expected_t1.isoformat()}) not yet published by "
        f"IBKR Flex; serving T-2."
    )


def _previous_or_same_weekday(value):
    resolved = value
    while resolved.weekday() >= 5:
        resolved -= timedelta(days=1)
    return resolved


def _format_utc_offset(value: datetime) -> str:
    offset = value.utcoffset()
    if offset is None:
        return "UTC"
    total_seconds = int(offset.total_seconds())
    sign = "+" if total_seconds >= 0 else "-"
    total_seconds = abs(total_seconds)
    hours, remainder = divmod(total_seconds, 3600)
    minutes = remainder // 60
    return f"UTC{sign}{hours:02d}:{minutes:02d}"
