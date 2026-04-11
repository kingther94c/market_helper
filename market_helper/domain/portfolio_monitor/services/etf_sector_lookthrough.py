from __future__ import annotations

import json
import os
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from market_helper.common.progress import ProgressReporter
from market_helper.data_sources.fmp import FmpClient, FmpEtfSectorWeight


DEFAULT_US_SECTOR_LOOKTHROUGH_PATH = (
    Path(__file__).resolve().parents[4] / "configs" / "portfolio_monitor" / "us_sector_lookthrough.json"
)
DEFAULT_CANONICAL_LOCAL_ENV_PATH = (
    Path(__file__).resolve().parents[4] / "configs" / "portfolio_monitor" / "local.env"
)
DEFAULT_FMP_API_KEY_ENV_VAR = "FMP_API_KEY"
DEFAULT_LOOKTHROUGH_SCHEMA_VERSION = 1
DEFAULT_LOOKTHROUGH_INITIAL_UPDATED_AT = "2000-01-01"
DEFAULT_LOOKTHROUGH_MAX_AGE_DAYS = 30
DEFAULT_FMP_DAILY_CALL_LIMIT = 250

FMP_SECTOR_TO_INTERNAL_BUCKET = {
    "basic materials": "Materials",
    "communication services": "Communication Services",
    "consumer cyclical": "Consumer Discretionary",
    "consumer cyclicals": "Consumer Discretionary",
    "consumer defensive": "Consumer Staples",
    "consumer discretionary": "Consumer Discretionary",
    "consumer staples": "Consumer Staples",
    "energy": "Energy",
    "financial services": "Financials",
    "financials": "Financials",
    "health care": "Health Care",
    "healthcare": "Health Care",
    "industrials": "Industrials",
    "materials": "Materials",
    "real estate": "Real Estate",
    "semiconductor": "Technology",
    "semiconductors": "Technology",
    "technology": "Technology",
    "utilities": "Utilities",
}


def sync_us_sector_lookthrough_from_fmp(
    *,
    symbols: Sequence[str],
    output_path: str | Path | None = None,
    api_key: str | None = None,
    client: FmpClient | None = None,
    force_refresh: bool = True,
    today: date | None = None,
    max_age_days: int = DEFAULT_LOOKTHROUGH_MAX_AGE_DAYS,
    daily_call_limit: int = DEFAULT_FMP_DAILY_CALL_LIMIT,
    progress: ProgressReporter | None = None,
) -> Path:
    normalized_symbols = _normalize_symbols(symbols)
    if not normalized_symbols:
        raise ValueError("At least one ETF symbol is required")

    destination = Path(output_path) if output_path is not None else DEFAULT_US_SECTOR_LOOKTHROUGH_PATH
    destination.parent.mkdir(parents=True, exist_ok=True)
    materialized_today = today or datetime.now(timezone.utc).date()
    store = _load_store(destination, daily_call_limit=daily_call_limit)
    _ensure_symbols_tracked(store, normalized_symbols)

    resolved_api_key = _resolve_fmp_api_key(api_key)
    if resolved_api_key or client is not None:
        resolved_client = client or FmpClient(api_key=resolved_api_key)
        _refresh_store(
            store,
            client=resolved_client,
            requested_symbols=normalized_symbols,
            force_refresh=force_refresh,
            today=materialized_today,
            max_age_days=max_age_days,
            daily_call_limit=daily_call_limit,
            progress=progress,
        )

    _write_store(destination, store)
    return destination


def refresh_us_sector_lookthrough_for_report(
    *,
    symbols: Sequence[str],
    output_path: str | Path | None = None,
    api_key: str | None = None,
    client: FmpClient | None = None,
    today: date | None = None,
    max_age_days: int = DEFAULT_LOOKTHROUGH_MAX_AGE_DAYS,
    daily_call_limit: int = DEFAULT_FMP_DAILY_CALL_LIMIT,
    progress: ProgressReporter | None = None,
) -> Path:
    return sync_us_sector_lookthrough_from_fmp(
        symbols=symbols,
        output_path=output_path,
        api_key=api_key,
        client=client,
        force_refresh=False,
        today=today,
        max_age_days=max_age_days,
        daily_call_limit=daily_call_limit,
        progress=progress,
    )


def load_us_sector_weight_table(path: str | Path) -> dict[str, list[tuple[str, float]]]:
    store = _load_store(Path(path))
    materialized: dict[str, list[tuple[str, float]]] = {}
    for symbol, payload in _store_symbols(store).items():
        sectors = payload.get("sectors", [])
        rows: list[tuple[str, float]] = []
        if isinstance(sectors, list):
            for row in sectors:
                if not isinstance(row, Mapping):
                    continue
                sector = str(row.get("sector") or "").strip()
                weight = _coerce_weight(row.get("weight"))
                if not sector or weight <= 0:
                    continue
                rows.append((sector, weight))
        if rows:
            materialized[symbol] = rows
    return materialized


def load_tracked_us_sector_symbols(path: str | Path) -> set[str]:
    store = _load_store(Path(path))
    return set(_store_symbols(store))


def _resolve_fmp_api_key(api_key: str | None) -> str:
    direct = str(api_key or "").strip()
    if direct:
        return direct
    from_process_env = str(os.environ.get(DEFAULT_FMP_API_KEY_ENV_VAR, "")).strip()
    if from_process_env:
        return from_process_env
    return _read_local_env_value(DEFAULT_FMP_API_KEY_ENV_VAR)


def _normalize_symbols(symbols: Sequence[str]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for raw_symbol in symbols:
        parts = [part.strip().upper() for part in str(raw_symbol).split(",")]
        for part in parts:
            if not part or part in seen:
                continue
            seen.add(part)
            normalized.append(part)
    return normalized


def _refresh_store(
    store: dict[str, Any],
    *,
    client: FmpClient,
    requested_symbols: Sequence[str],
    force_refresh: bool,
    today: date,
    max_age_days: int,
    daily_call_limit: int,
    progress: ProgressReporter | None,
) -> None:
    usage = _normalize_api_usage(store, today=today)
    remaining_budget = max(0, int(daily_call_limit) - int(usage["count"]))
    stale_symbols = _stale_symbols(
        store,
        force_refresh=force_refresh,
        requested_symbols=requested_symbols,
        today=today,
        max_age_days=max_age_days,
    )
    if progress is not None and stale_symbols:
        progress.stage("ETF sector sync", current=0, total=len(stale_symbols))
    if remaining_budget <= 0:
        if progress is not None and stale_symbols:
            progress.update(
                "ETF sector sync",
                completed=len(stale_symbols),
                total=len(stale_symbols),
                detail="budget exhausted",
            )
        return

    completed = 0
    for index, symbol in enumerate(stale_symbols, start=1):
        if remaining_budget <= 0:
            if progress is not None:
                progress.update(
                    "ETF sector sync",
                    completed=index,
                    total=len(stale_symbols),
                    detail=f"{symbol} budget-exhausted",
                )
            continue
        entry = _store_symbols(store)[symbol]
        try:
            normalized_rows = _normalize_fmp_rows(
                client.fetch_etf_sector_weightings(symbol),
                symbol=symbol,
            )
        except Exception as exc:
            entry["status"] = "error"
            entry["error_message"] = str(exc)
            entry["updated_at"] = today.isoformat()
        else:
            entry["status"] = "ok"
            entry["error_message"] = ""
            entry["updated_at"] = today.isoformat()
            entry["sectors"] = normalized_rows
        remaining_budget -= 1
        usage["count"] = int(usage["count"]) + 1
        if progress is not None:
            completed += 1
            progress.update(
                "ETF sector sync",
                completed=completed,
                total=len(stale_symbols),
                detail=f"{symbol} {entry['status']}",
            )


def _stale_symbols(
    store: Mapping[str, Any],
    *,
    force_refresh: bool,
    requested_symbols: Sequence[str],
    today: date,
    max_age_days: int,
) -> list[str]:
    symbols = _store_symbols(store)
    if force_refresh:
        return sorted(
            {
                symbol
                for symbol in requested_symbols
                if symbol in symbols
            }
        )

    stale: list[tuple[date, str]] = []
    for symbol, payload in symbols.items():
        updated_at = _parse_iso_date(payload.get("updated_at"))
        if (today - updated_at).days > max_age_days:
            stale.append((updated_at, symbol))
    stale.sort(key=lambda item: (item[0], item[1]))
    return [symbol for _, symbol in stale]


def _normalize_fmp_rows(
    rows: Iterable[FmpEtfSectorWeight],
    *,
    symbol: str,
) -> list[dict[str, object]]:
    bucket_weights: dict[str, float] = {}
    for row in rows:
        bucket = _normalize_sector_name(row.sector)
        bucket_weights[bucket] = bucket_weights.get(bucket, 0.0) + float(row.weight)

    if not bucket_weights:
        raise ValueError(f"FMP returned no usable sector rows for {symbol}")

    return [
        {
            "sector": sector,
            "weight": _rounded_weight(weight),
        }
        for sector, weight in sorted(
            bucket_weights.items(),
            key=lambda item: (-item[1], item[0]),
        )
    ]


def _normalize_sector_name(raw_sector: str) -> str:
    cleaned = str(raw_sector).strip()
    if not cleaned:
        raise ValueError("Sector name cannot be blank")
    normalized = FMP_SECTOR_TO_INTERNAL_BUCKET.get(cleaned.lower())
    if normalized is not None:
        return normalized
    return cleaned


def _rounded_weight(weight: float) -> float:
    return round(float(weight), 6)


def _coerce_weight(raw_value: object) -> float:
    if raw_value in (None, ""):
        return 0.0
    return float(raw_value)


def _load_store(path: Path, *, daily_call_limit: int = DEFAULT_FMP_DAILY_CALL_LIMIT) -> dict[str, Any]:
    if path.exists():
        loaded = json.loads(path.read_text(encoding="utf-8")) or {}
        if not isinstance(loaded, dict):
            raise ValueError("ETF sector lookthrough JSON must be an object")
        return _normalize_store(loaded, daily_call_limit=daily_call_limit)
    return _default_store(daily_call_limit=daily_call_limit)


def _default_store(*, daily_call_limit: int) -> dict[str, Any]:
    return {
        "schema_version": DEFAULT_LOOKTHROUGH_SCHEMA_VERSION,
        "provider": "fmp",
        "daily_call_limit": int(daily_call_limit),
        "api_usage": {
            "date": "",
            "count": 0,
        },
        "symbols": {},
    }


def _normalize_store(payload: Mapping[str, Any], *, daily_call_limit: int) -> dict[str, Any]:
    store = _default_store(daily_call_limit=daily_call_limit)
    store["schema_version"] = int(payload.get("schema_version", DEFAULT_LOOKTHROUGH_SCHEMA_VERSION))
    store["provider"] = str(payload.get("provider") or "fmp")
    store["daily_call_limit"] = int(payload.get("daily_call_limit", daily_call_limit))
    store["api_usage"] = _normalize_api_usage_payload(payload.get("api_usage"))

    raw_symbols = payload.get("symbols", {})
    if not isinstance(raw_symbols, Mapping):
        raise ValueError("ETF sector lookthrough symbols payload must be a mapping")
    symbols: dict[str, dict[str, Any]] = {}
    for raw_symbol, raw_entry in raw_symbols.items():
        symbol = str(raw_symbol).strip().upper()
        if not symbol:
            continue
        entry = dict(raw_entry) if isinstance(raw_entry, Mapping) else {}
        sectors = entry.get("sectors", [])
        normalized_sectors: list[dict[str, object]] = []
        if isinstance(sectors, list):
            for row in sectors:
                if not isinstance(row, Mapping):
                    continue
                sector = str(row.get("sector") or "").strip()
                weight = _coerce_weight(row.get("weight"))
                if not sector or weight <= 0:
                    continue
                normalized_sectors.append(
                    {
                        "sector": sector,
                        "weight": _rounded_weight(weight),
                    }
                )
        symbols[symbol] = {
            "updated_at": _parse_iso_date(entry.get("updated_at")).isoformat(),
            "status": str(entry.get("status") or ("ok" if normalized_sectors else "pending")).strip().lower(),
            "error_message": str(entry.get("error_message") or "").strip(),
            "sectors": normalized_sectors,
        }
    store["symbols"] = symbols
    return store


def _normalize_api_usage(store: dict[str, Any], *, today: date) -> dict[str, Any]:
    usage = _normalize_api_usage_payload(store.get("api_usage"))
    if usage["date"] != today.isoformat():
        usage = {
            "date": today.isoformat(),
            "count": 0,
        }
    store["api_usage"] = usage
    return usage


def _normalize_api_usage_payload(raw_usage: Any) -> dict[str, Any]:
    if not isinstance(raw_usage, Mapping):
        return {"date": "", "count": 0}
    usage_date = str(raw_usage.get("date") or "").strip()
    count = raw_usage.get("count", 0)
    try:
        normalized_count = max(0, int(count))
    except (TypeError, ValueError):
        normalized_count = 0
    return {
        "date": usage_date,
        "count": normalized_count,
    }


def _ensure_symbols_tracked(store: dict[str, Any], symbols: Sequence[str]) -> None:
    tracked = _store_symbols(store)
    for symbol in symbols:
        if symbol in tracked:
            continue
        tracked[symbol] = {
            "updated_at": DEFAULT_LOOKTHROUGH_INITIAL_UPDATED_AT,
            "status": "pending",
            "error_message": "",
            "sectors": [],
        }


def _store_symbols(store: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    raw_symbols = store.get("symbols", {})
    if not isinstance(raw_symbols, dict):
        raise ValueError("ETF sector lookthrough store symbols must be a dict")
    return raw_symbols


def _write_store(path: Path, store: Mapping[str, Any]) -> None:
    path.write_text(
        json.dumps(store, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _parse_iso_date(raw_value: object) -> date:
    cleaned = str(raw_value or "").strip()
    if not cleaned:
        return date.fromisoformat(DEFAULT_LOOKTHROUGH_INITIAL_UPDATED_AT)
    try:
        return date.fromisoformat(cleaned)
    except ValueError:
        return date.fromisoformat(DEFAULT_LOOKTHROUGH_INITIAL_UPDATED_AT)


def _read_local_env_value(key: str) -> str:
    normalized_key = str(key).strip()
    if not normalized_key:
        return ""
    return _read_env_file_value(DEFAULT_CANONICAL_LOCAL_ENV_PATH, normalized_key)


def _read_env_file_value(path: Path, key: str) -> str:
    if not path.exists():
        return ""

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue
        raw_key, raw_value = line.split("=", 1)
        if raw_key.strip() != key:
            continue
        value = raw_value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"\"", "'"}:
            value = value[1:-1]
        return value.strip()
    return ""
