from __future__ import annotations

"""Sync online inputs used by the legacy regime rulebook."""

import json
import shutil
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Mapping

import pandas as pd

from market_helper.data_library.loader import (
    DownloadError,
    download_fred_series,
    download_fred_series_csv,
)
from market_helper.data_sources.yahoo_finance import YahooFinanceClient
from market_helper.workflows.sync_fred_macro_panel import _resolve_fred_api_key


DEFAULT_REGIME_RETURNS_PATH = Path("data/processed/regime_returns.json")
DEFAULT_REGIME_PROXY_PATH = Path("data/processed/regime_proxies.json")
DEFAULT_FRED_OBSERVATION_START = "2000-01-01"
DEFAULT_HY_OAS_HISTORY_PATH = Path("data/external/regime_detection/hy_oas_history.csv")


@dataclass(frozen=True)
class RegimeInputSyncResult:
    returns_path: Path
    proxy_path: Path


def sync_regime_inputs(
    *,
    returns_output_path: str | Path = DEFAULT_REGIME_RETURNS_PATH,
    proxy_output_path: str | Path = DEFAULT_REGIME_PROXY_PATH,
    eq_symbol: str = "SPY",
    fi_symbol: str = "AGG",
    vix_symbol: str = "^VIX",
    move_symbol: str = "^MOVE",
    yahoo_period: str = "max",
    yahoo_interval: str = "1d",
    fred_observation_start: str | None = DEFAULT_FRED_OBSERVATION_START,
    fred_api_key: str | None = None,
    hy_oas_history_path: str | Path | None = DEFAULT_HY_OAS_HISTORY_PATH,
    yahoo_client: YahooFinanceClient | None = None,
) -> RegimeInputSyncResult:
    """Fetch and write processed JSON inputs for ``legacy_rulebook``.

    Returns:
      - returns JSON with ``EQ`` and ``FI`` daily returns from Yahoo prices.
      - proxy JSON with ``VIX``, ``MOVE``, ``HY_OAS``, ``UST2Y``, ``UST10Y``.
    """
    yahoo = yahoo_client or YahooFinanceClient()
    resolved_fred_key = _resolve_fred_api_key(fred_api_key)
    if not resolved_fred_key:
        raise RuntimeError(
            "FRED_API_KEY is not set. Pass --fred-api-key, export FRED_API_KEY, "
            "or add it to configs/portfolio_monitor/local.env."
        )

    returns_payload = {
        "EQ": _yahoo_returns(
            yahoo,
            eq_symbol,
            period=yahoo_period,
            interval=yahoo_interval,
        ),
        "FI": _yahoo_returns(
            yahoo,
            fi_symbol,
            period=yahoo_period,
            interval=yahoo_interval,
        ),
    }
    hy_oas = _fred_series_dict(
        "BAMLH0A0HYM2",
        api_key=resolved_fred_key,
        observation_start=fred_observation_start,
    )
    if hy_oas_history_path is not None:
        hy_oas_seed_path = Path(hy_oas_history_path)
        hy_oas = _merge_series_dicts(
            _load_date_value_csv(hy_oas_seed_path),
            hy_oas,
        )
        _write_date_value_csv_with_backup(hy_oas_seed_path, hy_oas)

    proxy_payload = {
        "VIX": _yahoo_levels(
            yahoo,
            vix_symbol,
            period=yahoo_period,
            interval=yahoo_interval,
        ),
        "MOVE": _yahoo_levels(
            yahoo,
            move_symbol,
            period=yahoo_period,
            interval=yahoo_interval,
        ),
        "HY_OAS": hy_oas,
        "UST2Y": _fred_series_dict(
            "DGS2",
            api_key=resolved_fred_key,
            observation_start=fred_observation_start,
        ),
        "UST10Y": _fred_series_dict(
            "DGS10",
            api_key=resolved_fred_key,
            observation_start=fred_observation_start,
        ),
    }

    returns_path = Path(returns_output_path)
    proxy_path = Path(proxy_output_path)
    returns_path.parent.mkdir(parents=True, exist_ok=True)
    proxy_path.parent.mkdir(parents=True, exist_ok=True)
    returns_path.write_text(json.dumps(returns_payload, indent=2), encoding="utf-8")
    proxy_path.write_text(json.dumps(proxy_payload, indent=2), encoding="utf-8")
    return RegimeInputSyncResult(returns_path=returns_path, proxy_path=proxy_path)


def _yahoo_returns(
    yahoo_client: YahooFinanceClient,
    symbol: str,
    *,
    period: str,
    interval: str,
) -> dict[str, float]:
    levels = _yahoo_level_series(
        yahoo_client,
        symbol,
        period=period,
        interval=interval,
    )
    returns = levels.pct_change().dropna()
    return _series_to_json_dict(returns)


def _yahoo_levels(
    yahoo_client: YahooFinanceClient,
    symbol: str,
    *,
    period: str,
    interval: str,
) -> dict[str, float]:
    return _series_to_json_dict(
        _yahoo_level_series(
            yahoo_client,
            symbol,
            period=period,
            interval=interval,
        )
    )


def _yahoo_level_series(
    yahoo_client: YahooFinanceClient,
    symbol: str,
    *,
    period: str,
    interval: str,
) -> pd.Series:
    history = yahoo_client.fetch_price_history(
        symbol,
        period=period,
        interval=interval,
    )
    prices = history.get("prices") if isinstance(history, Mapping) else None
    if not isinstance(prices, list) or not prices:
        raise ValueError(f"Yahoo returned no prices for {symbol}")
    rows = []
    for row in prices:
        if not isinstance(row, Mapping):
            continue
        timestamp = row.get("timestamp")
        value = row.get("adjclose", row.get("close"))
        if timestamp is None or value in (None, ""):
            continue
        as_of = pd.to_datetime(int(timestamp), unit="s", utc=True).date().isoformat()
        rows.append((as_of, float(value)))
    if not rows:
        raise ValueError(f"Yahoo returned no usable prices for {symbol}")
    series = pd.Series(
        {as_of: value for as_of, value in rows},
        dtype=float,
    ).sort_index()
    return series[~series.index.duplicated(keep="last")]


def _fred_series_dict(
    series_id: str,
    *,
    api_key: str,
    observation_start: str | None,
) -> dict[str, float]:
    try:
        series = download_fred_series_csv(
            series_id,
            observation_start=observation_start,
        )
        return {
            obs.date: float(obs.value)
            for obs in series.observations
        }
    except (DownloadError, ValueError):
        pass

    attempts = 3
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            series = download_fred_series(
                series_id=series_id,
                api_key=api_key,
                observation_start=observation_start,
            )
            return {
                obs.date: float(obs.value)
                for obs in series.observations
            }
        except (DownloadError, TimeoutError, OSError) as exc:
            last_error = exc
            if attempt >= attempts:
                break
            time.sleep(float(attempt))
    raise RuntimeError(
        f"FRED download failed for {series_id} after CSV fallback and "
        f"{attempts} API attempts. Last API error: {last_error}"
    )


def _series_to_json_dict(series: pd.Series) -> dict[str, float]:
    out: dict[str, float] = {}
    for index, value in series.items():
        if pd.isna(value):
            continue
        out[str(index)] = float(value)
    return out


def _load_date_value_csv(path: Path) -> dict[str, float]:
    if not path.exists():
        return {}
    frame = pd.read_csv(path, encoding="utf-8-sig")
    if not {"Date", "Value"}.issubset(frame.columns):
        raise ValueError(f"{path} must have Date and Value columns")
    frame["Date"] = pd.to_datetime(frame["Date"], errors="coerce")
    frame["Value"] = pd.to_numeric(frame["Value"], errors="coerce")
    if frame["Date"].isna().any() or frame["Value"].isna().any():
        raise ValueError(f"{path} contains invalid Date or Value rows")
    frame = frame.sort_values("Date").drop_duplicates("Date", keep="last")
    return {
        row.Date.date().isoformat(): float(row.Value)
        for row in frame.itertuples(index=False)
    }


def _write_date_value_csv_with_backup(path: Path, values: Mapping[str, float]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        backup_path = path.with_suffix(
            path.suffix + f".bak-{datetime.now().strftime('%Y%m%dT%H%M%S')}"
        )
        shutil.copy2(path, backup_path)
    rows = [
        {"Date": date, "Value": float(values[date])}
        for date in sorted(values)
    ]
    pd.DataFrame(rows).to_csv(path, index=False)


def _merge_series_dicts(
    base: Mapping[str, float],
    override: Mapping[str, float],
) -> dict[str, float]:
    merged = {str(k): float(v) for k, v in base.items()}
    merged.update({str(k): float(v) for k, v in override.items()})
    return {
        date: merged[date]
        for date in sorted(merged)
    }


__all__ = [
    "DEFAULT_REGIME_PROXY_PATH",
    "DEFAULT_REGIME_RETURNS_PATH",
    "DEFAULT_FRED_OBSERVATION_START",
    "DEFAULT_HY_OAS_HISTORY_PATH",
    "RegimeInputSyncResult",
    "sync_regime_inputs",
]
