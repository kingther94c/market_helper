from __future__ import annotations

from datetime import datetime


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
