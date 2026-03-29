from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class YahooFinanceClient:
    """Read-only Yahoo Finance client scaffold for future regime ingestion."""

    session: Any | None = None

    def fetch_price_history(self, symbol: str, *, period: str = "1y") -> dict[str, Any]:
        raise NotImplementedError(
            "YahooFinanceClient is a scaffold in this refactor. Wire concrete retrieval in a follow-up PR."
        )
