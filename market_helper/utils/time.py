from __future__ import annotations

from datetime import UTC, datetime


def utc_now_iso() -> str:
    """Return an ISO-8601 UTC timestamp with timezone info."""
    return datetime.now(UTC).isoformat()


def ensure_utc_iso(value: datetime) -> str:
    """Normalize a datetime to UTC and return ISO-8601 string."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat()
