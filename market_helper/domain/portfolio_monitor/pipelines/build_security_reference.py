from __future__ import annotations

from pathlib import Path

from market_helper.common.models import (
    DEFAULT_SECURITY_REFERENCE_PATH,
    SecurityReferenceTable,
    build_security_reference_table,
    export_security_reference_csv,
)


def build_security_reference(
    path: str | Path | None = None,
) -> SecurityReferenceTable:
    destination = Path(path) if path is not None else DEFAULT_SECURITY_REFERENCE_PATH
    table = build_security_reference_table(reference_path=destination)
    export_security_reference_csv(table.to_rows(), destination)
    return table


__all__ = ["build_security_reference"]
