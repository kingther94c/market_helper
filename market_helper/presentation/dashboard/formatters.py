from __future__ import annotations

from pathlib import Path


def format_percent(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{float(value):.2%}"


def format_amount(value: float | None, *, decimals: int = 2) -> str:
    if value is None:
        return "n/a"
    return f"{float(value):,.{decimals}f}"


def format_ratio(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{float(value):.2f}"


def format_path(value: str | Path | None) -> str:
    if value is None:
        return "n/a"
    return str(value)


def format_text(value: str | None) -> str:
    normalized = (value or "").strip()
    return normalized or "n/a"

