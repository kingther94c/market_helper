from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping
from urllib.parse import quote

import pandas as pd

from market_helper.common.progress import ProgressReporter
from market_helper.data_sources.yahoo_finance import YahooFinanceClient, YahooFinanceTransientError

from .volatility import compute_returns


DEFAULT_YAHOO_RETURNS_CACHE_DIR = (
    Path(__file__).resolve().parents[4] / "data" / "artifacts" / "portfolio_monitor" / "yahoo_returns"
)
DEFAULT_YAHOO_RETURN_METHOD = "log"
DEFAULT_YAHOO_PERIOD = "5y"
DEFAULT_YAHOO_INTERVAL = "1d"
DEFAULT_YAHOO_PRICE_FIELD = "adjclose"


@dataclass(frozen=True)
class YahooReturnCache:
    symbol: str
    currency: str
    source: str
    price_field: str
    return_method: str
    interval: str
    period: str
    generated_at: str
    series: pd.Series

    def to_payload(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "currency": self.currency,
            "source": self.source,
            "price_field": self.price_field,
            "return_method": self.return_method,
            "interval": self.interval,
            "period": self.period,
            "generated_at": self.generated_at,
            "series": {
                _normalize_date_key(index): float(value)
                for index, value in self.series.dropna().items()
            },
        }


def yahoo_symbol_cache_path(
    symbol: str,
    *,
    cache_dir: str | Path = DEFAULT_YAHOO_RETURNS_CACHE_DIR,
) -> Path:
    normalized_symbol = str(symbol).strip()
    if not normalized_symbol:
        raise ValueError("symbol is required")
    return Path(cache_dir) / f"{quote(normalized_symbol, safe='')}.json"


def price_history_to_return_series(
    history: Mapping[str, Any],
    *,
    return_method: str = DEFAULT_YAHOO_RETURN_METHOD,
    price_field: str = DEFAULT_YAHOO_PRICE_FIELD,
) -> pd.Series:
    prices = history.get("prices") if isinstance(history, Mapping) else None
    if not isinstance(prices, list):
        return pd.Series(dtype=float)
    rows: list[tuple[pd.Timestamp, float]] = []
    for row in prices:
        if not isinstance(row, Mapping):
            continue
        raw_timestamp = row.get("timestamp")
        raw_price = row.get(price_field)
        if raw_timestamp in (None, "") or raw_price in (None, ""):
            continue
        timestamp = pd.to_datetime(int(raw_timestamp), unit="s", utc=True).tz_localize(None).normalize()
        rows.append((timestamp, float(raw_price)))
    if not rows:
        return pd.Series(dtype=float)
    price_series = pd.Series(
        data=[price for _, price in rows],
        index=pd.DatetimeIndex([timestamp for timestamp, _ in rows]),
        dtype=float,
    ).sort_index()
    deduped = price_series[~price_series.index.duplicated(keep="last")]
    return compute_returns(deduped, method=return_method, dropna=True)


def load_symbol_return_cache(path: str | Path) -> YahooReturnCache | None:
    cache_path = Path(path)
    if not cache_path.exists():
        return None
    loaded = json.loads(cache_path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError("Yahoo return cache must be a JSON object")
    series_payload = loaded.get("series")
    if not isinstance(series_payload, dict):
        series = pd.Series(dtype=float)
    else:
        pairs = sorted(
            (
                pd.to_datetime(str(date_key)).normalize(),
                float(value),
            )
            for date_key, value in series_payload.items()
        )
        series = pd.Series(
            data=[value for _, value in pairs],
            index=pd.DatetimeIndex([timestamp for timestamp, _ in pairs]),
            dtype=float,
        )
    return YahooReturnCache(
        symbol=str(loaded.get("symbol") or ""),
        currency=str(loaded.get("currency") or ""),
        source=str(loaded.get("source") or "yahoo_finance"),
        price_field=str(loaded.get("price_field") or DEFAULT_YAHOO_PRICE_FIELD),
        return_method=str(loaded.get("return_method") or DEFAULT_YAHOO_RETURN_METHOD),
        interval=str(loaded.get("interval") or DEFAULT_YAHOO_INTERVAL),
        period=str(loaded.get("period") or DEFAULT_YAHOO_PERIOD),
        generated_at=str(loaded.get("generated_at") or ""),
        series=series,
    )


def write_symbol_return_cache(
    cache: YahooReturnCache,
    *,
    path: str | Path | None = None,
    cache_dir: str | Path = DEFAULT_YAHOO_RETURNS_CACHE_DIR,
) -> Path:
    destination = Path(path) if path is not None else yahoo_symbol_cache_path(cache.symbol, cache_dir=cache_dir)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(cache.to_payload(), indent=2, sort_keys=True), encoding="utf-8")
    return destination


def ensure_symbol_return_cache(
    symbol: str,
    *,
    yahoo_client: YahooFinanceClient,
    cache_dir: str | Path = DEFAULT_YAHOO_RETURNS_CACHE_DIR,
    period: str = DEFAULT_YAHOO_PERIOD,
    interval: str = DEFAULT_YAHOO_INTERVAL,
    return_method: str = DEFAULT_YAHOO_RETURN_METHOD,
    price_field: str = DEFAULT_YAHOO_PRICE_FIELD,
    force_refresh: bool = False,
    now: pd.Timestamp | None = None,
) -> YahooReturnCache:
    cache_path = yahoo_symbol_cache_path(symbol, cache_dir=cache_dir)
    cached = load_symbol_return_cache(cache_path)
    if (
        not force_refresh
        and cached is not None
        and not _is_cache_stale(
            cached,
            period=period,
            interval=interval,
            return_method=return_method,
            price_field=price_field,
            now=now,
        )
    ):
        return cached

    try:
        history = yahoo_client.fetch_price_history(symbol, period=period, interval=interval)
    except YahooFinanceTransientError:
        if cached is not None and not cached.series.empty:
            return cached
        raise
    series = price_history_to_return_series(history, return_method=return_method, price_field=price_field)
    cache = YahooReturnCache(
        symbol=str(history.get("symbol") or symbol),
        currency=str(history.get("currency") or ""),
        source="yahoo_finance",
        price_field=price_field,
        return_method=return_method,
        interval=interval,
        period=period,
        generated_at=pd.Timestamp.utcnow().isoformat(),
        series=series,
    )
    write_symbol_return_cache(cache, path=cache_path)
    return cache


def build_internal_id_return_series_from_yahoo(
    rows: Iterable[Any],
    *,
    yahoo_client: YahooFinanceClient,
    cache_dir: str | Path = DEFAULT_YAHOO_RETURNS_CACHE_DIR,
    period: str = DEFAULT_YAHOO_PERIOD,
    interval: str = DEFAULT_YAHOO_INTERVAL,
    return_method: str = DEFAULT_YAHOO_RETURN_METHOD,
    price_field: str = DEFAULT_YAHOO_PRICE_FIELD,
    ignore_transient_failures: bool = True,
    progress: ProgressReporter | None = None,
) -> dict[str, pd.Series]:
    ensured_by_symbol: dict[str, YahooReturnCache] = {}
    built: dict[str, pd.Series] = {}
    materialized_rows = list(rows)
    tracked_symbols = sorted(
        {
            str(getattr(row, "yahoo_symbol", "") or "").strip()
            for row in materialized_rows
            if str(getattr(row, "mapping_status", "") or "") == "mapped"
            and str(getattr(row, "asset_class", "") or "") != "CASH"
            and str(getattr(row, "yahoo_symbol", "") or "").strip()
        }
    )
    if progress is not None and tracked_symbols:
        progress.stage("Yahoo returns", current=0, total=len(tracked_symbols))
    completed_symbols = 0
    processed_symbols: set[str] = set()

    for row in materialized_rows:
        mapping_status = str(getattr(row, "mapping_status", "") or "")
        asset_class = str(getattr(row, "asset_class", "") or "")
        internal_id = str(getattr(row, "internal_id", "") or "")
        yahoo_symbol = str(getattr(row, "yahoo_symbol", "") or "").strip()
        if mapping_status != "mapped" or asset_class == "CASH":
            continue
        if not yahoo_symbol:
            raise ValueError(f"Missing yahoo_symbol for mapped security {internal_id}")
        if yahoo_symbol not in ensured_by_symbol:
            cache_path = yahoo_symbol_cache_path(yahoo_symbol, cache_dir=cache_dir)
            cached = load_symbol_return_cache(cache_path)
            try:
                ensured_by_symbol[yahoo_symbol] = ensure_symbol_return_cache(
                    yahoo_symbol,
                    yahoo_client=yahoo_client,
                    cache_dir=cache_dir,
                    period=period,
                    interval=interval,
                    return_method=return_method,
                    price_field=price_field,
                )
            except YahooFinanceTransientError:
                if progress is not None and yahoo_symbol not in processed_symbols:
                    completed_symbols += 1
                    processed_symbols.add(yahoo_symbol)
                    progress.update(
                        "Yahoo returns",
                        completed=completed_symbols,
                        total=len(tracked_symbols),
                        detail=f"{yahoo_symbol} skipped",
                    )
                if ignore_transient_failures:
                    continue
                raise
            if progress is not None and yahoo_symbol not in processed_symbols:
                detail = f"{yahoo_symbol} fetched"
                if cached is not None and ensured_by_symbol[yahoo_symbol] is cached:
                    detail = f"{yahoo_symbol} cached"
                completed_symbols += 1
                processed_symbols.add(yahoo_symbol)
                progress.update(
                    "Yahoo returns",
                    completed=completed_symbols,
                    total=len(tracked_symbols),
                    detail=detail,
                )
        built[internal_id] = ensured_by_symbol[yahoo_symbol].series.copy()
    return built


def load_internal_id_return_series_override(path: str | Path) -> dict[str, pd.Series]:
    loaded = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError("Expected returns JSON object")
    materialized: dict[str, pd.Series] = {}
    for key, value in loaded.items():
        internal_id = str(key)
        if isinstance(value, list):
            materialized[internal_id] = _legacy_list_returns_to_series(value)
            continue
        if isinstance(value, dict):
            materialized[internal_id] = _dated_return_mapping_to_series(value)
            continue
        raise ValueError("Expected returns JSON values to be either lists or dated objects")
    return materialized


def _legacy_list_returns_to_series(values: list[Any]) -> pd.Series:
    parsed = [float(value) for value in values]
    start = -len(parsed)
    return pd.Series(parsed, index=pd.RangeIndex(start=start, stop=0), dtype=float)


def _dated_return_mapping_to_series(values: Mapping[str, Any]) -> pd.Series:
    pairs = sorted((pd.to_datetime(str(key)).normalize(), float(value)) for key, value in values.items())
    return pd.Series(
        data=[value for _, value in pairs],
        index=pd.DatetimeIndex([timestamp for timestamp, _ in pairs]),
        dtype=float,
    )


def _is_cache_stale(
    cache: YahooReturnCache,
    *,
    period: str,
    interval: str,
    return_method: str,
    price_field: str,
    now: pd.Timestamp | None,
) -> bool:
    if cache.series.empty:
        return True
    if cache.period != period or cache.interval != interval:
        return True
    if cache.return_method != return_method or cache.price_field != price_field:
        return True
    last_index = pd.Timestamp(cache.series.index.max()).normalize()
    return last_index < _latest_expected_daily_observation(now=now)


def _latest_expected_daily_observation(now: pd.Timestamp | None) -> pd.Timestamp:
    reference = pd.Timestamp.utcnow() if now is None else pd.Timestamp(now)
    reference = reference.tz_localize(None) if reference.tzinfo is not None else reference
    normalized = reference.normalize()
    return (normalized - pd.offsets.BDay(1)).normalize()


def _normalize_date_key(index: Any) -> str:
    timestamp = pd.Timestamp(index)
    return timestamp.normalize().date().isoformat()


__all__ = [
    "DEFAULT_YAHOO_INTERVAL",
    "DEFAULT_YAHOO_PERIOD",
    "DEFAULT_YAHOO_RETURN_METHOD",
    "DEFAULT_YAHOO_RETURNS_CACHE_DIR",
    "YahooReturnCache",
    "build_internal_id_return_series_from_yahoo",
    "ensure_symbol_return_cache",
    "load_internal_id_return_series_override",
    "load_symbol_return_cache",
    "price_history_to_return_series",
    "write_symbol_return_cache",
    "yahoo_symbol_cache_path",
]
