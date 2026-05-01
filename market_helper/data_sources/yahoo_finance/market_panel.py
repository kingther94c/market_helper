"""Cached Yahoo Finance market panel for market-regime detection."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping, Sequence

import pandas as pd

from market_helper.data_sources.yahoo_finance.client import YahooFinanceClient

DEFAULT_MARKET_CACHE_DIR = Path("data/interim/market_regime")
DEFAULT_MARKET_PANEL_FILENAME = "market_panel.feather"


@dataclass(frozen=True)
class MarketSymbolSpec:
    symbol: str
    alias: str | None = None

    @property
    def column(self) -> str:
        return self.alias or self.symbol


def history_payload_to_frame(payload: Mapping[str, object]) -> pd.DataFrame:
    symbol = str(payload.get("symbol") or "")
    rows = []
    for item in payload.get("prices", []):  # type: ignore[union-attr]
        if not isinstance(item, Mapping):
            continue
        value = item.get("adjclose", item.get("close"))
        if value in (None, ""):
            continue
        rows.append(
            {
                "date": pd.to_datetime(int(item["timestamp"]), unit="s", utc=True)
                .tz_convert(None)
                .normalize(),
                "value": float(value),
                "symbol": symbol,
            }
        )
    if not rows:
        return pd.DataFrame(columns=["date", "value", "symbol"])
    return pd.DataFrame(rows).sort_values("date").drop_duplicates("date", keep="last")


def sync_market_symbol(
    spec: MarketSymbolSpec,
    *,
    client: YahooFinanceClient | None = None,
    cache_dir: Path = DEFAULT_MARKET_CACHE_DIR,
    period: str = "max",
    interval: str = "1d",
) -> pd.DataFrame:
    client = client or YahooFinanceClient()
    payload = client.fetch_price_history(spec.symbol, period=period, interval=interval)
    frame = history_payload_to_frame(payload)
    cache_dir.mkdir(parents=True, exist_ok=True)
    frame.reset_index(drop=True).to_feather(cache_dir / f"{_safe_name(spec.column)}.feather")
    return frame


def load_cached_market_symbol(cache_dir: Path, column: str) -> pd.DataFrame:
    path = cache_dir / f"{_safe_name(column)}.feather"
    if not path.exists():
        return pd.DataFrame(columns=["date", "value", "symbol"])
    frame = pd.read_feather(path)
    if not frame.empty:
        frame["date"] = pd.to_datetime(frame["date"]).dt.tz_localize(None)
    return frame


def build_market_panel(
    specs: Sequence[MarketSymbolSpec],
    *,
    cache_dir: Path = DEFAULT_MARKET_CACHE_DIR,
    start_date: str | None = None,
    end_date: str | None = None,
) -> pd.DataFrame:
    frames: dict[str, pd.DataFrame] = {}
    for spec in specs:
        frame = load_cached_market_symbol(Path(cache_dir), spec.column)
        if frame.empty:
            continue
        frames[spec.column] = frame
    if not frames:
        return pd.DataFrame()

    default_start = min(frame["date"].min() for frame in frames.values())
    default_end = max(frame["date"].max() for frame in frames.values())
    panel_start = pd.Timestamp(start_date) if start_date else default_start
    panel_end = pd.Timestamp(end_date) if end_date else default_end
    index = pd.bdate_range(panel_start, panel_end, name="date")
    panel = pd.DataFrame(index=index)
    for column, frame in frames.items():
        series = (
            frame.set_index("date")["value"]
            .sort_index()
            .reindex(index)
            .ffill()
        )
        panel[column] = series
    return panel.reset_index()


def write_market_panel(panel: pd.DataFrame, cache_dir: Path = DEFAULT_MARKET_CACHE_DIR) -> Path:
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / DEFAULT_MARKET_PANEL_FILENAME
    panel.reset_index(drop=True).to_feather(path)
    return path


def load_market_panel(path: str | Path) -> pd.DataFrame:
    frame = pd.read_feather(Path(path))
    if "date" in frame.columns:
        frame["date"] = pd.to_datetime(frame["date"]).dt.tz_localize(None)
    return frame


def sync_market_panel(
    specs: Sequence[MarketSymbolSpec],
    *,
    client: YahooFinanceClient | None = None,
    cache_dir: Path = DEFAULT_MARKET_CACHE_DIR,
    period: str = "max",
    interval: str = "1d",
    start_date: str | None = None,
    end_date: str | None = None,
) -> Path:
    for spec in specs:
        sync_market_symbol(
            spec,
            client=client,
            cache_dir=cache_dir,
            period=period,
            interval=interval,
        )
    panel = build_market_panel(
        specs,
        cache_dir=cache_dir,
        start_date=start_date,
        end_date=end_date,
    )
    return write_market_panel(panel, cache_dir=cache_dir)


def _safe_name(value: str) -> str:
    return value.replace("/", "__").replace("^", "_")


__all__ = [
    "DEFAULT_MARKET_CACHE_DIR",
    "DEFAULT_MARKET_PANEL_FILENAME",
    "MarketSymbolSpec",
    "build_market_panel",
    "history_payload_to_frame",
    "load_market_panel",
    "sync_market_panel",
    "sync_market_symbol",
    "write_market_panel",
]
