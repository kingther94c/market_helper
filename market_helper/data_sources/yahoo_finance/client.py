from __future__ import annotations

from dataclasses import dataclass
import json
import time
from typing import Any, Callable, Dict, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import urlopen

import pandas as pd
import yfinance as yf


YahooDownloader = Callable[[str], Dict[str, Any]]
SleepFn = Callable[[float], None]


class YahooFinanceError(RuntimeError):
    """Base exception for Yahoo Finance data access failures."""


class YahooFinanceTransientError(YahooFinanceError):
    """Transient Yahoo Finance failure such as rate limiting or network errors."""


@dataclass(frozen=True)
class YahooFinanceClient:
    """Read-only Yahoo Finance client for historical price retrieval."""

    session: Any | None = None
    downloader: YahooDownloader | None = None
    max_attempts: int = 3
    backoff_base_seconds: float = 1.0
    backoff_max_seconds: float = 8.0
    sleep: SleepFn = time.sleep

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

        if self.downloader is None:
            return _fetch_yfinance_history_with_retry(
                normalized_symbol,
                period=period,
                interval=interval,
                session=self.session,
                max_attempts=self.max_attempts,
                backoff_base_seconds=self.backoff_base_seconds,
                backoff_max_seconds=self.backoff_max_seconds,
                sleep=self.sleep,
            )

        url = (
            "https://query1.finance.yahoo.com/v8/finance/chart/"
            f"{quote(normalized_symbol)}?range={period}&interval={interval}&includeAdjustedClose=true"
        )
        payload = _download_with_retry(
            url,
            downloader=self.downloader,
            max_attempts=self.max_attempts,
            backoff_base_seconds=self.backoff_base_seconds,
            backoff_max_seconds=self.backoff_max_seconds,
            sleep=self.sleep,
        )
        return _materialize_chart_payload(payload, normalized_symbol)


def _materialize_chart_payload(payload: Mapping[str, Any], normalized_symbol: str) -> dict[str, Any]:
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


def _fetch_yfinance_history_with_retry(
    symbol: str,
    *,
    period: str,
    interval: str,
    session: Any | None,
    max_attempts: int,
    backoff_base_seconds: float,
    backoff_max_seconds: float,
    sleep: SleepFn,
) -> dict[str, Any]:
    if max_attempts <= 0:
        raise ValueError("max_attempts must be positive")
    if backoff_base_seconds < 0 or backoff_max_seconds < 0:
        raise ValueError("backoff values must be non-negative")

    for attempt in range(1, max_attempts + 1):
        try:
            return _fetch_yfinance_history(
                symbol,
                period=period,
                interval=interval,
                session=session,
            )
        except Exception as exc:
            if isinstance(exc, ValueError):
                raise
            if attempt >= max_attempts:
                raise YahooFinanceTransientError(
                    f"Yahoo Finance request failed after {attempt} attempts"
                ) from exc
            delay = _retry_delay_seconds(
                exc,
                attempt=attempt,
                backoff_base_seconds=backoff_base_seconds,
                backoff_max_seconds=backoff_max_seconds,
            )
            if delay > 0:
                sleep(delay)

    raise YahooFinanceTransientError("Yahoo Finance request failed without an explicit error")


def _fetch_yfinance_history(
    symbol: str,
    *,
    period: str,
    interval: str,
    session: Any | None,
) -> dict[str, Any]:
    ticker = yf.Ticker(symbol, session=session)
    history = ticker.history(
        period=period,
        interval=interval,
        auto_adjust=False,
        actions=False,
    )
    if history is None or history.empty:
        raise ValueError(f"yfinance returned no usable prices for {symbol}")

    prices: list[dict[str, Any]] = []
    for timestamp, row in history.iterrows():
        close = _coerce_history_float(row.get("Close"))
        adjclose = _coerce_history_float(row.get("Adj Close"))
        if close is None and adjclose is None:
            continue
        close_value = close if close is not None else adjclose
        adjclose_value = adjclose if adjclose is not None else close_value
        prices.append(
            {
                "timestamp": _timestamp_to_epoch_seconds(timestamp),
                "close": float(close_value),
                "adjclose": float(adjclose_value),
            }
        )

    if not prices:
        raise ValueError(f"yfinance returned no usable prices for {symbol}")

    return {
        "symbol": symbol,
        "currency": _extract_yfinance_currency(ticker),
        "prices": prices,
    }


def _coerce_history_float(value: Any) -> float | None:
    if value in (None, "") or pd.isna(value):
        return None
    return float(value)


def _timestamp_to_epoch_seconds(value: Any) -> int:
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        timestamp = timestamp.tz_localize("UTC")
    else:
        timestamp = timestamp.tz_convert("UTC")
    return int(timestamp.timestamp())


def _extract_yfinance_currency(ticker: Any) -> str:
    history_metadata = getattr(ticker, "history_metadata", None)
    if isinstance(history_metadata, Mapping):
        currency = history_metadata.get("currency")
        if currency not in (None, ""):
            return str(currency)

    fast_info = getattr(ticker, "fast_info", None)
    if isinstance(fast_info, Mapping):
        currency = fast_info.get("currency")
        if currency not in (None, ""):
            return str(currency)
    return ""


def _download_json(url: str) -> dict[str, Any]:
    with urlopen(url, timeout=30) as response:
        payload = response.read().decode("utf-8")
    loaded = json.loads(payload)
    if not isinstance(loaded, dict):
        raise ValueError("Yahoo Finance response was not a JSON object")
    return loaded


def _download_with_retry(
    url: str,
    *,
    downloader: YahooDownloader | None,
    max_attempts: int,
    backoff_base_seconds: float,
    backoff_max_seconds: float,
    sleep: SleepFn,
) -> dict[str, Any]:
    if max_attempts <= 0:
        raise ValueError("max_attempts must be positive")
    if backoff_base_seconds < 0 or backoff_max_seconds < 0:
        raise ValueError("backoff values must be non-negative")

    fetch = downloader if downloader is not None else _download_json
    for attempt in range(1, max_attempts + 1):
        try:
            payload = fetch(url)
            if not isinstance(payload, dict):
                raise ValueError("Yahoo Finance response was not a JSON object")
            return payload
        except Exception as exc:
            retryable = _is_retryable_yahoo_error(exc)
            if not retryable:
                raise
            if attempt >= max_attempts:
                raise YahooFinanceTransientError(
                    f"Yahoo Finance request failed after {attempt} attempts"
                ) from exc
            delay = _retry_delay_seconds(
                exc,
                attempt=attempt,
                backoff_base_seconds=backoff_base_seconds,
                backoff_max_seconds=backoff_max_seconds,
            )
            if delay > 0:
                sleep(delay)

    raise YahooFinanceTransientError("Yahoo Finance request failed without an explicit error")


def _is_retryable_yahoo_error(exc: Exception) -> bool:
    if isinstance(exc, HTTPError):
        return exc.code == 429 or exc.code == 408 or 500 <= exc.code < 600
    if isinstance(exc, URLError):
        return True
    return isinstance(exc, TimeoutError)


def _retry_delay_seconds(
    exc: Exception,
    *,
    attempt: int,
    backoff_base_seconds: float,
    backoff_max_seconds: float,
) -> float:
    if isinstance(exc, HTTPError):
        retry_after = exc.headers.get("Retry-After") if exc.headers is not None else None
        if retry_after not in (None, ""):
            try:
                retry_after_seconds = float(retry_after)
            except (TypeError, ValueError):
                retry_after_seconds = None
            else:
                if retry_after_seconds is not None and retry_after_seconds >= 0:
                    return min(backoff_max_seconds, retry_after_seconds)
    backoff = backoff_base_seconds * (2 ** (attempt - 1))
    return min(backoff_max_seconds, backoff)
