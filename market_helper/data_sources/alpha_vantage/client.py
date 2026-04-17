from __future__ import annotations

from dataclasses import dataclass, field
import time
from typing import Callable, Iterable, Mapping

from market_helper.data_sources.base import DEFAULT_TIMEOUT, build_url, download_json


DEFAULT_ALPHA_VANTAGE_QUERY_URL = "https://www.alphavantage.co/query"
ETF_PROFILE_FUNCTION = "ETF_PROFILE"
DEFAULT_ALPHA_VANTAGE_REQUEST_SPACING_SECONDS = 12.0
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
    request_spacing_seconds: float = DEFAULT_ALPHA_VANTAGE_REQUEST_SPACING_SECONDS
    clock: Clock = time.monotonic
    sleep: Sleep = time.sleep
    _next_request_not_before: float = field(
        default=0.0,
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
        spacing_seconds = max(0.0, float(self.request_spacing_seconds))
        if spacing_seconds <= 0:
            return
        now = float(self.clock())
        next_allowed = float(self._next_request_not_before)
        wait_seconds = next_allowed - now
        if wait_seconds > 0:
            self.sleep(wait_seconds)
            now = float(self.clock())
            next_allowed = float(self._next_request_not_before)
        object.__setattr__(
            self,
            "_next_request_not_before",
            max(now, next_allowed) + spacing_seconds,
        )


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
