from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable, Mapping

from market_helper.data_sources.base import DEFAULT_TIMEOUT, download_json


DEFAULT_FMP_ETF_SECTOR_WEIGHTINGS_URL = "https://financialmodelingprep.com/stable/etf/sector-weightings"
FmpDownloader = Callable[[str], object]


class FmpClientError(RuntimeError):
    """Base exception for Financial Modeling Prep client errors."""


@dataclass(frozen=True)
class FmpEtfSectorWeight:
    symbol: str
    sector: str
    weight: float


@dataclass(frozen=True)
class FmpClient:
    """Lightweight read-only client for ETF sector weight lookups."""

    api_key: str
    downloader: FmpDownloader | None = None
    base_url: str = DEFAULT_FMP_ETF_SECTOR_WEIGHTINGS_URL
    timeout: int = DEFAULT_TIMEOUT

    def fetch_etf_sector_weightings(self, symbol: str) -> list[FmpEtfSectorWeight]:
        normalized_symbol = str(symbol).strip().upper()
        normalized_api_key = str(self.api_key).strip()
        if not normalized_symbol:
            raise ValueError("symbol is required")
        if not normalized_api_key:
            raise ValueError("api_key is required")

        payload = self._download(
            self.base_url,
            {
                "symbol": normalized_symbol,
                "apikey": normalized_api_key,
            },
        )
        rows = _parse_sector_rows(payload, symbol=normalized_symbol)
        if not rows:
            raise FmpClientError(f"FMP returned no ETF sector rows for {normalized_symbol}")
        return rows

    def _download(self, url: str, params: Mapping[str, object]) -> object:
        if self.downloader is not None:
            return self.downloader(_build_request_url(url, params))
        return download_json(url, params=params, timeout=self.timeout)


def _build_request_url(url: str, params: Mapping[str, object]) -> str:
    query = "&".join(
        f"{key}={value}"
        for key, value in params.items()
        if value not in (None, "")
    )
    return f"{url}?{query}" if query else url


def _parse_sector_rows(payload: object, *, symbol: str) -> list[FmpEtfSectorWeight]:
    if isinstance(payload, list):
        rows = _parse_row_list(payload, symbol=symbol)
        if rows:
            return rows
    elif isinstance(payload, dict):
        _raise_if_error_payload(payload, symbol=symbol)
        rows = _parse_dict_payload(payload, symbol=symbol)
        if rows:
            return rows
    raise FmpClientError(f"Unexpected FMP ETF sector payload for {symbol}")


def _raise_if_error_payload(payload: Mapping[str, object], *, symbol: str) -> None:
    for key in ("Error Message", "error", "message"):
        raw_value = payload.get(key)
        if raw_value not in (None, ""):
            raise FmpClientError(f"FMP ETF sector request failed for {symbol}: {raw_value}")


def _parse_dict_payload(payload: Mapping[str, object], *, symbol: str) -> list[FmpEtfSectorWeight]:
    for key in ("sectorWeightings", "sector_weightings", "data", "results"):
        nested = payload.get(key)
        if isinstance(nested, list):
            return _parse_row_list(nested, symbol=symbol)

    maybe_direct_mapping = _parse_direct_sector_mapping(payload, symbol=symbol)
    if maybe_direct_mapping:
        return maybe_direct_mapping
    return []


def _parse_row_list(rows: Iterable[object], *, symbol: str) -> list[FmpEtfSectorWeight]:
    materialized: list[FmpEtfSectorWeight] = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        sector = _coerce_sector_name(row)
        weight = _coerce_weight(row)
        if not sector or weight <= 0:
            continue
        materialized.append(
            FmpEtfSectorWeight(symbol=symbol, sector=sector, weight=weight)
        )
    return materialized


def _parse_direct_sector_mapping(
    payload: Mapping[str, object],
    *,
    symbol: str,
) -> list[FmpEtfSectorWeight]:
    reserved = {"symbol", "ticker", "fund", "name", "date", "updated", "asOfDate"}
    materialized: list[FmpEtfSectorWeight] = []
    for key, value in payload.items():
        if key in reserved:
            continue
        weight = _parse_weight_value(value)
        if weight <= 0:
            continue
        materialized.append(
            FmpEtfSectorWeight(symbol=symbol, sector=str(key).strip(), weight=weight)
        )
    return materialized


def _coerce_sector_name(row: Mapping[str, object]) -> str:
    for key in ("sector", "sectorName", "name", "label", "category"):
        value = row.get(key)
        if value not in (None, ""):
            return str(value).strip()
    return ""


def _coerce_weight(row: Mapping[str, object]) -> float:
    for key in (
        "weight",
        "weightPercentage",
        "weightPercent",
        "percentage",
        "percent",
        "allocation",
        "value",
    ):
        weight = _parse_weight_value(row.get(key))
        if weight > 0:
            return weight
    return 0.0


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
