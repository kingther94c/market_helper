from __future__ import annotations

import json
import os
import re
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from market_helper.data_sources.alpha_vantage import (
    AlphaVantageClient,
    AlphaVantageEtfSectorWeight,
)


DEFAULT_US_SECTOR_LOOKTHROUGH_PATH = (
    Path(__file__).resolve().parents[4] / "configs" / "portfolio_monitor" / "us_sector_lookthrough.json"
)
DEFAULT_CANONICAL_LOCAL_ENV_PATH = (
    Path(__file__).resolve().parents[4] / "configs" / "portfolio_monitor" / "local.env"
)
DEFAULT_ALPHA_VANTAGE_API_KEY_ENV_VAR = "ALPHA_VANTAGE_API_KEY"
DEFAULT_LOOKTHROUGH_SCHEMA_VERSION = 1
DEFAULT_LOOKTHROUGH_INITIAL_UPDATED_AT = "2000-01-01"
DEFAULT_LOOKTHROUGH_MAX_AGE_DAYS = 30
DEFAULT_ALPHA_VANTAGE_DAILY_CALL_LIMIT = 25
LOOKTHROUGH_PROVIDER = "alpha_vantage"
LOOKTHROUGH_OK_STATUSES = {"pending", "ok", "error", "stale"}
API_KEY_QUERY_PARAM_PATTERN = re.compile(r"([?&]apikey=)[^&\s:]+", re.IGNORECASE)

ALPHA_VANTAGE_SECTOR_TO_INTERNAL_BUCKET = {
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
    "information technology": "Technology",
    "industrials": "Industrials",
    "materials": "Materials",
    "real estate": "Real Estate",
    "semiconductor": "Technology",
    "semiconductors": "Technology",
    "technology": "Technology",
    "utilities": "Utilities",
}


def sync_us_sector_lookthrough_from_alpha_vantage(
    *,
    symbols: Sequence[str],
    output_path: str | Path | None = None,
    api_key: str | None = None,
    client: AlphaVantageClient | None = None,
    force_refresh: bool = True,
    today: date | None = None,
    max_age_days: int = DEFAULT_LOOKTHROUGH_MAX_AGE_DAYS,
    daily_call_limit: int = DEFAULT_ALPHA_VANTAGE_DAILY_CALL_LIMIT,
) -> Path:
    normalized_symbols = _normalize_symbols(symbols)
    if not normalized_symbols:
        raise ValueError("At least one ETF symbol is required")

    destination = Path(output_path) if output_path is not None else DEFAULT_US_SECTOR_LOOKTHROUGH_PATH
    destination.parent.mkdir(parents=True, exist_ok=True)
    materialized_today = today or datetime.now(timezone.utc).date()
    store = _load_store(destination, daily_call_limit=daily_call_limit)
    _ensure_symbols_tracked(store, normalized_symbols)

    resolved_api_key = _resolve_alpha_vantage_api_key(api_key)
    if resolved_api_key or client is not None:
        resolved_client = client or AlphaVantageClient(api_key=resolved_api_key)
        _refresh_store(
            store,
            client=resolved_client,
            requested_symbols=normalized_symbols,
            force_refresh=force_refresh,
            today=materialized_today,
            max_age_days=max_age_days,
            daily_call_limit=daily_call_limit,
        )

    _write_store(destination, store)
    return destination


def refresh_us_sector_lookthrough_for_report(
    *,
    symbols: Sequence[str],
    output_path: str | Path | None = None,
    api_key: str | None = None,
    client: AlphaVantageClient | None = None,
    today: date | None = None,
    max_age_days: int = DEFAULT_LOOKTHROUGH_MAX_AGE_DAYS,
    daily_call_limit: int = DEFAULT_ALPHA_VANTAGE_DAILY_CALL_LIMIT,
) -> Path:
    return sync_us_sector_lookthrough_from_alpha_vantage(
        symbols=symbols,
        output_path=output_path,
        api_key=api_key,
        client=client,
        force_refresh=False,
        today=today,
        max_age_days=max_age_days,
        daily_call_limit=daily_call_limit,
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


def _resolve_alpha_vantage_api_key(api_key: str | None) -> str:
    direct = str(api_key or "").strip()
    if direct:
        return direct
    from_process_env = str(os.environ.get(DEFAULT_ALPHA_VANTAGE_API_KEY_ENV_VAR, "")).strip()
    if from_process_env:
        return from_process_env
    return _read_local_env_value(DEFAULT_ALPHA_VANTAGE_API_KEY_ENV_VAR)


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
    client: AlphaVantageClient,
    requested_symbols: Sequence[str],
    force_refresh: bool,
    today: date,
    max_age_days: int,
    daily_call_limit: int,
) -> None:
    usage = _normalize_api_usage(store, today=today)
    remaining_budget = max(0, int(daily_call_limit) - int(usage["count"]))
    if remaining_budget <= 0:
        return

    stale_symbols = _stale_symbols(
        store,
        force_refresh=force_refresh,
        requested_symbols=requested_symbols,
        today=today,
        max_age_days=max_age_days,
    )
    for symbol in stale_symbols:
        if remaining_budget <= 0:
            break
        entry = _store_symbols(store)[symbol]
        entry["last_attempted_at"] = today.isoformat()
        try:
            normalized_rows = _normalize_alpha_vantage_rows(
                client.fetch_etf_sector_weightings(symbol),
                symbol=symbol,
            )
        except Exception as exc:
            entry["status"] = "stale" if _entry_has_sectors(entry) else "error"
            entry["error_message"] = _sanitize_error_message(exc)
        else:
            entry["status"] = "ok"
            entry["error_message"] = ""
            entry["updated_at"] = today.isoformat()
            entry["sectors"] = normalized_rows
        remaining_budget -= 1
        usage["count"] = int(usage["count"]) + 1


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
        if _normalize_optional_iso_date(payload.get("last_attempted_at")) == today.isoformat():
            continue
        if not _entry_has_sectors(payload):
            stale.append((_parse_iso_date(payload.get("updated_at")), symbol))
            continue
        updated_at = _parse_iso_date(payload.get("updated_at"))
        if (today - updated_at).days > max_age_days:
            stale.append((updated_at, symbol))
    stale.sort(key=lambda item: (item[0], item[1]))
    return [symbol for _, symbol in stale]


def _normalize_alpha_vantage_rows(
    rows: Iterable[AlphaVantageEtfSectorWeight],
    *,
    symbol: str,
) -> list[dict[str, object]]:
    bucket_weights: dict[str, float] = {}
    for row in rows:
        bucket = _normalize_sector_name(row.sector)
        bucket_weights[bucket] = bucket_weights.get(bucket, 0.0) + float(row.weight)

    if not bucket_weights:
        raise ValueError(f"Alpha Vantage returned no usable sector rows for {symbol}")

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
    normalized = ALPHA_VANTAGE_SECTOR_TO_INTERNAL_BUCKET.get(cleaned.lower())
    if normalized is not None:
        return normalized
    return cleaned


def _rounded_weight(weight: float) -> float:
    return round(float(weight), 6)


def _coerce_weight(raw_value: object) -> float:
    if raw_value in (None, ""):
        return 0.0
    return float(raw_value)


def _load_store(
    path: Path,
    *,
    daily_call_limit: int = DEFAULT_ALPHA_VANTAGE_DAILY_CALL_LIMIT,
) -> dict[str, Any]:
    if path.exists():
        loaded = json.loads(path.read_text(encoding="utf-8")) or {}
        if not isinstance(loaded, dict):
            raise ValueError("ETF sector lookthrough JSON must be an object")
        return _normalize_store(loaded, daily_call_limit=daily_call_limit)
    return _default_store(daily_call_limit=daily_call_limit)


def _default_store(*, daily_call_limit: int) -> dict[str, Any]:
    return {
        "schema_version": DEFAULT_LOOKTHROUGH_SCHEMA_VERSION,
        "provider": LOOKTHROUGH_PROVIDER,
        "daily_call_limit": int(daily_call_limit),
        "api_usage": {
            "date": "",
            "count": 0,
        },
        "symbols": {},
    }


def _normalize_store(payload: Mapping[str, Any], *, daily_call_limit: int) -> dict[str, Any]:
    store = _default_store(daily_call_limit=daily_call_limit)
    raw_provider = str(payload.get("provider") or "").strip().lower()
    migrated_from_other_provider = raw_provider not in ("", LOOKTHROUGH_PROVIDER)
    store["schema_version"] = int(payload.get("schema_version", DEFAULT_LOOKTHROUGH_SCHEMA_VERSION))
    store["provider"] = LOOKTHROUGH_PROVIDER
    store["daily_call_limit"] = int(
        daily_call_limit
        if migrated_from_other_provider
        else payload.get("daily_call_limit", daily_call_limit)
    )
    store["api_usage"] = (
        {"date": "", "count": 0}
        if migrated_from_other_provider
        else _normalize_api_usage_payload(payload.get("api_usage"))
    )

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
        updated_at = (
            DEFAULT_LOOKTHROUGH_INITIAL_UPDATED_AT
            if migrated_from_other_provider
            else _parse_iso_date(entry.get("updated_at")).isoformat()
        )
        last_attempted_at = (
            ""
            if migrated_from_other_provider
            else _normalize_optional_iso_date(entry.get("last_attempted_at"))
        )
        status = _normalize_entry_status(
            raw_status=entry.get("status"),
            has_sectors=bool(normalized_sectors),
        )
        error_message = _sanitize_error_message(entry.get("error_message"))
        if migrated_from_other_provider:
            status = "stale" if normalized_sectors else "pending"
            error_message = ""
        symbols[symbol] = {
            "updated_at": updated_at,
            "last_attempted_at": last_attempted_at,
            "status": status,
            "error_message": error_message,
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
            "last_attempted_at": "",
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


def _normalize_optional_iso_date(raw_value: object) -> str:
    cleaned = str(raw_value or "").strip()
    if not cleaned:
        return ""
    try:
        return date.fromisoformat(cleaned).isoformat()
    except ValueError:
        return ""


def _normalize_entry_status(*, raw_status: object, has_sectors: bool) -> str:
    normalized = str(raw_status or ("ok" if has_sectors else "pending")).strip().lower()
    if normalized == "error" and has_sectors:
        return "stale"
    if normalized not in LOOKTHROUGH_OK_STATUSES:
        return "ok" if has_sectors else "pending"
    return normalized


def _entry_has_sectors(payload: Mapping[str, Any]) -> bool:
    sectors = payload.get("sectors", [])
    return isinstance(sectors, list) and len(sectors) > 0


def _sanitize_error_message(raw_value: object) -> str:
    message = str(raw_value or "").strip()
    if not message:
        return ""
    return API_KEY_QUERY_PARAM_PATTERN.sub(r"\1[redacted]", message)


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
