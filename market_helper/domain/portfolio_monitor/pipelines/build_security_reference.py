from __future__ import annotations

from pathlib import Path

from market_helper.common.models import DEFAULT_SECURITY_REFERENCE_PATH, SecurityReferenceTable


def build_security_reference(
    path: str | Path | None = None,
) -> SecurityReferenceTable:
    source = Path(path) if path is not None else DEFAULT_SECURITY_REFERENCE_PATH
    return SecurityReferenceTable.from_csv(source)


__all__ = ["build_security_reference"]
