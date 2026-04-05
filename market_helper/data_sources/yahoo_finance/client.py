from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Callable
from urllib.parse import quote
from urllib.request import urlopen


YahooDownloader = Callable[[str], dict[str, Any]]


@dataclass(frozen=True)
class YahooFinanceClient:
    """Read-only Yahoo Finance client for historical price retrieval."""

    session: Any | None = None
    downloader: YahooDownloader | None = None

    def fetch_price_history(
        self,
        symbol: str,
        *,
        period: str = "5y",
        interval: str = "1d",
    ) -> dict[str, Any]:
        normalized_symbol = str(symbol).strip()
        if not normalized_symbol:
            raise ValueError("Yahoo symbol is required")

        url = (
            "https://query1.finance.yahoo.com/v8/finance/chart/"
            f"{quote(normalized_symbol)}?range={period}&interval={interval}&includeAdjustedClose=true"
        )
        payload = self.downloader(url) if self.downloader is not None else _download_json(url)
        chart = payload.get("chart") if isinstance(payload, dict) else None
        result = chart.get("result") if isinstance(chart, dict) else None
        if not isinstance(result, list) or not result:
            raise ValueError(f"Yahoo Finance returned no chart result for {normalized_symbol}")

        materialized = result[0]
        meta = materialized.get("meta") if isinstance(materialized, dict) else {}
        timestamps = materialized.get("timestamp") if isinstance(materialized, dict) else None
        indicators = materialized.get("indicators") if isinstance(materialized, dict) else None
        quotes = indicators.get("quote") if isinstance(indicators, dict) else None
        adjclose_rows = indicators.get("adjclose") if isinstance(indicators, dict) else None
        closes = quotes[0].get("close") if isinstance(quotes, list) and quotes else []
        adjcloses = (
            adjclose_rows[0].get("adjclose")
            if isinstance(adjclose_rows, list) and adjclose_rows
            else []
        )
        if not isinstance(timestamps, list):
            raise ValueError(f"Yahoo Finance returned no timestamps for {normalized_symbol}")

        prices: list[dict[str, Any]] = []
        for idx, timestamp in enumerate(timestamps):
            close = closes[idx] if idx < len(closes) else None
            adjclose = adjcloses[idx] if idx < len(adjcloses) else close
            if close in (None, "") and adjclose in (None, ""):
                continue
            close_value = float(close if close not in (None, "") else adjclose)
            adjclose_value = float(adjclose if adjclose not in (None, "") else close_value)
            prices.append(
                {
                    "timestamp": int(timestamp),
                    "close": close_value,
                    "adjclose": adjclose_value,
                }
            )

        if not prices:
            raise ValueError(f"Yahoo Finance returned no usable prices for {normalized_symbol}")

        return {
            "symbol": normalized_symbol,
            "currency": str(meta.get("currency") or ""),
            "prices": prices,
        }


def _download_json(url: str) -> dict[str, Any]:
    with urlopen(url) as response:
        payload = response.read().decode("utf-8")
    loaded = json.loads(payload)
    if not isinstance(loaded, dict):
        raise ValueError("Yahoo Finance response was not a JSON object")
    return loaded
