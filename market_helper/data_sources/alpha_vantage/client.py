from __future__ import annotations

from dataclasses import dataclass, field
import time
from typing import Callable, Iterable, Mapping

from market_helper.data_sources.base import DEFAULT_TIMEOUT, build_url, download_json


DEFAULT_ALPHA_VANTAGE_QUERY_URL = "https://www.alphavantage.co/query"
ETF_PROFILE_FUNCTION = "ETF_PROFILE"
# Free-tier limits observed in practice: ~1 request/second burst cap (AV
# rejects back-to-back requests with a "spread out your requests" payload)
# plus the daily quota. We pace requests at a small fixed gap and keep a
# conservative 5-per-minute sliding window — the old fixed 12s spacing made
# even a 2-symbol refresh stall a report build for ~12s.
DEFAULT_ALPHA_VANTAGE_MAX_REQUESTS_PER_WINDOW = 5
DEFAULT_ALPHA_VANTAGE_WINDOW_SECONDS = 60.0
DEFAULT_ALPHA_VANTAGE_MIN_REQUEST_INTERVAL_SECONDS = 1.2
AlphaVantageDownloader = Callable[[str], object]
Clock = Callable[[], float]
Sleep = Callable[[float], None]


class AlphaVantageClientError(RuntimeError):
    """Base exception for Alpha Vantage ETF profile lookups."""


@dataclass(frozen=True)
class AlphaVantageEtfSectorWeight:
    symbol: str
    sector: str
    weight: float


@dataclass(frozen=True)
class AlphaVantageClient:
    """Lightweight read-only client for ETF sector weight lookups."""

    api_key: str
    downloader: AlphaVantageDownloader | None = None
    base_url: str = DEFAULT_ALPHA_VANTAGE_QUERY_URL
    timeout: int = DEFAULT_TIMEOUT
    max_requests_per_window: int = DEFAULT_ALPHA_VANTAGE_MAX_REQUESTS_PER_WINDOW
    window_seconds: float = DEFAULT_ALPHA_VANTAGE_WINDOW_SECONDS
    min_request_interval_seconds: float = DEFAULT_ALPHA_VANTAGE_MIN_REQUEST_INTERVAL_SECONDS
    clock: Clock = time.monotonic
    sleep: Sleep = time.sleep
    _request_times: list[float] = field(
        default_factory=list,
        init=False,
        repr=False,
        compare=False,
    )

    def fetch_etf_sector_weightings(self, symbol: str) -> list[AlphaVantageEtfSectorWeight]:
        normalized_symbol = str(symbol).strip().upper()
        normalized_api_key = str(self.api_key).strip()
        if not normalized_symbol:
            raise ValueError("symbol is required")
        if not normalized_api_key:
            raise ValueError("api_key is required")

        payload = self._download(
            self.base_url,
            {
                "function": ETF_PROFILE_FUNCTION,
                "symbol": normalized_symbol,
                "apikey": normalized_api_key,
            },
        )
        rows = _parse_sector_rows(payload, symbol=normalized_symbol)
        if not rows:
            raise AlphaVantageClientError(
                f"Alpha Vantage returned no ETF sector rows for {normalized_symbol}"
            )
        return rows

    def _download(self, url: str, params: Mapping[str, object]) -> object:
        self._respect_request_spacing()
        if self.downloader is not None:
            return self.downloader(build_url(url, params))
        return download_json(url, params=params, timeout=self.timeout)

    def _respect_request_spacing(self) -> None:
        """Two-level limiter matching AV's observed free-tier behavior.

        A short fixed gap between consecutive requests (AV rejects true
        back-to-back calls with a "spread out your requests" payload) plus a
        sliding ``max_requests_per_window`` / ``window_seconds`` cap. Small
        batches pace at ~1s per request instead of the old 12s spacing."""
        limit = int(self.max_requests_per_window)
        window = max(0.0, float(self.window_seconds))
        min_gap = max(0.0, float(self.min_request_interval_seconds))
        now = float(self.clock())
        recent = [stamp for stamp in self._request_times if window > 0 and now - stamp < window]
        if min_gap > 0 and recent:
            gap_wait = recent[-1] + min_gap - now
            if gap_wait > 0:
                self.sleep(gap_wait)
                now = float(self.clock())
        if limit > 0 and window > 0 and len(recent) >= limit:
            wait_seconds = recent[0] + window - now
            if wait_seconds > 0:
                self.sleep(wait_seconds)
                now = float(self.clock())
            recent = [stamp for stamp in recent if now - stamp < window]
        recent.append(now)
        object.__setattr__(self, "_request_times", recent)


def _parse_sector_rows(
    payload: object,
    *,
    symbol: str,
) -> list[AlphaVantageEtfSectorWeight]:
    if not isinstance(payload, Mapping):
        raise AlphaVantageClientError(
            f"Unexpected Alpha Vantage ETF profile payload for {symbol}"
        )

    _raise_if_error_payload(payload, symbol=symbol)

    raw_rows = payload.get("sectors")
    if not isinstance(raw_rows, list):
        raise AlphaVantageClientError(
            f"Alpha Vantage ETF profile for {symbol} did not include sectors"
        )
    return _parse_row_list(raw_rows, symbol=symbol)


def _raise_if_error_payload(payload: Mapping[str, object], *, symbol: str) -> None:
    for key in ("Error Message", "Information", "Note", "error", "message"):
        raw_value = payload.get(key)
        if raw_value not in (None, ""):
            raise AlphaVantageClientError(
                f"Alpha Vantage ETF profile request failed for {symbol}: {raw_value}"
            )


def _parse_row_list(
    rows: Iterable[object],
    *,
    symbol: str,
) -> list[AlphaVantageEtfSectorWeight]:
    materialized: list[AlphaVantageEtfSectorWeight] = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        sector = str(row.get("sector") or "").strip()
        weight = _parse_weight_value(row.get("weight"))
        if not sector or weight <= 0:
            continue
        materialized.append(
            AlphaVantageEtfSectorWeight(symbol=symbol, sector=sector, weight=weight)
        )
    return materialized


def _parse_weight_value(raw_value: object) -> float:
    if raw_value in (None, ""):
        return 0.0
    if isinstance(raw_value, str):
        cleaned = raw_value.strip().replace("%", "").replace(",", "")
        if cleaned == "":
            return 0.0
        try:
            parsed = float(cleaned)
        except ValueError:
            return 0.0
    elif isinstance(raw_value, (int, float)):
        parsed = float(raw_value)
    else:
        return 0.0

    if parsed < 0:
        return 0.0
    if parsed > 1.0:
        return parsed / 100.0
    return parsed
