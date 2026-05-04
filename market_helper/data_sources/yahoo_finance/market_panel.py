"""Cached Yahoo Finance market panel for market-regime detection."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

import pandas as pd
import yaml

from market_helper.data_sources.yahoo_finance.client import YahooFinanceClient

DEFAULT_MARKET_CACHE_DIR = Path("data/interim/market_regime")
DEFAULT_MARKET_PANEL_FILENAME = "market_panel.feather"
DEFAULT_MARKET_META_FILENAME = "market_panel_meta.yml"
DEFAULT_INCREMENTAL_PERIOD = "2mo"


@dataclass(frozen=True)
class MarketSymbolSpec:
    symbol: str
    alias: str | None = None

    @property
    def column(self) -> str:
        return self.alias or self.symbol


@dataclass(frozen=True)
class PanelValidationDiagnostics:
    duplicate_dates_removed: int = 0
    duplicate_dates: list[str] = field(default_factory=list)
    unexpected_gap_count: int = 0
    unexpected_gaps: list[str] = field(default_factory=list)
    unique_dates: bool = True
    strictly_increasing: bool = True
    rows: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


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


def normalize_price_frame(frame: pd.DataFrame) -> tuple[pd.DataFrame, PanelValidationDiagnostics]:
    """Normalize a dated price frame and report duplicate/gap diagnostics."""
    if frame.empty:
        return (
            pd.DataFrame(columns=["date", "value", "symbol"]),
            PanelValidationDiagnostics(rows=0),
        )
    working = frame.copy()
    working["date"] = pd.to_datetime(working["date"]).dt.tz_localize(None).dt.normalize()
    duplicate_mask = working.duplicated("date", keep=False)
    duplicate_dates = sorted(
        {pd.Timestamp(value).strftime("%Y-%m-%d") for value in working.loc[duplicate_mask, "date"]}
    )
    duplicate_removed = int(max(0, duplicate_mask.sum() - len(duplicate_dates)))
    normalized = (
        working.sort_values("date")
        .drop_duplicates("date", keep="last")
        .reset_index(drop=True)
    )
    strictly_increasing = bool(
        normalized["date"].is_monotonic_increasing
        and not normalized["date"].duplicated().any()
    )
    unexpected_gaps = _unexpected_business_gaps(normalized["date"])
    diagnostics = PanelValidationDiagnostics(
        duplicate_dates_removed=duplicate_removed,
        duplicate_dates=duplicate_dates,
        unexpected_gap_count=len(unexpected_gaps),
        unexpected_gaps=unexpected_gaps[:20],
        unique_dates=not normalized["date"].duplicated().any(),
        strictly_increasing=strictly_increasing,
        rows=len(normalized),
    )
    return normalized, diagnostics


def sync_market_symbol(
    spec: MarketSymbolSpec,
    *,
    client: YahooFinanceClient | None = None,
    cache_dir: Path = DEFAULT_MARKET_CACHE_DIR,
    period: str = DEFAULT_INCREMENTAL_PERIOD,
    interval: str = "1d",
    force: bool = False,
) -> pd.DataFrame:
    client = client or YahooFinanceClient()
    cache_dir.mkdir(parents=True, exist_ok=True)
    cached = load_cached_market_symbol(cache_dir, spec.column)
    payload = client.fetch_price_history(
        spec.symbol,
        period=("max" if force else period),
        interval=interval,
    )
    fresh = history_payload_to_frame(payload)
    merged = fresh if force or cached.empty else pd.concat([cached, fresh], ignore_index=True)
    frame, diagnostics = normalize_price_frame(merged)
    frame.reset_index(drop=True).to_feather(cache_dir / f"{_safe_name(spec.column)}.feather")
    write_market_symbol_meta(
        cache_dir,
        spec.column,
        {
            "symbol": spec.symbol,
            "alias": spec.alias,
            "force": bool(force),
            "period": "max" if force else period,
            "interval": interval,
            "diagnostics": diagnostics.to_dict(),
        },
    )
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


def validate_market_panel(panel: pd.DataFrame) -> PanelValidationDiagnostics:
    if panel.empty or "date" not in panel.columns:
        return PanelValidationDiagnostics(rows=0)
    dates = pd.to_datetime(panel["date"]).dt.tz_localize(None).dt.normalize()
    duplicate_mask = dates.duplicated(keep=False)
    duplicate_dates = sorted(
        {pd.Timestamp(value).strftime("%Y-%m-%d") for value in dates[duplicate_mask]}
    )
    unexpected_gaps = _unexpected_business_gaps(dates.drop_duplicates().sort_values())
    return PanelValidationDiagnostics(
        duplicate_dates_removed=0,
        duplicate_dates=duplicate_dates,
        unexpected_gap_count=len(unexpected_gaps),
        unexpected_gaps=unexpected_gaps[:20],
        unique_dates=not dates.duplicated().any(),
        strictly_increasing=bool(dates.is_monotonic_increasing and not dates.duplicated().any()),
        rows=len(panel),
    )


def write_market_panel(panel: pd.DataFrame, cache_dir: Path = DEFAULT_MARKET_CACHE_DIR) -> Path:
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / DEFAULT_MARKET_PANEL_FILENAME
    panel.reset_index(drop=True).to_feather(path)
    return path


def write_market_panel_meta(
    cache_dir: Path,
    *,
    specs: Sequence[MarketSymbolSpec],
    diagnostics: Mapping[str, Any],
) -> Path:
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / DEFAULT_MARKET_META_FILENAME
    payload = {
        "symbols": [{"symbol": spec.symbol, "alias": spec.alias, "column": spec.column} for spec in specs],
        "diagnostics": dict(diagnostics),
    }
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return path


def write_market_symbol_meta(cache_dir: Path, column: str, payload: Mapping[str, Any]) -> Path:
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / f"{_safe_name(column)}_meta.yml"
    path.write_text(yaml.safe_dump(dict(payload), sort_keys=False), encoding="utf-8")
    return path


def load_market_panel(path: str | Path, columns: Sequence[str] | None = None) -> pd.DataFrame:
    requested = _date_first_columns(columns)
    try:
        frame = pd.read_feather(Path(path), columns=requested)
    except (KeyError, ValueError):
        frame = pd.read_feather(Path(path))
        if requested:
            available = [column for column in requested if column in frame.columns]
            frame = frame.loc[:, available]
    if "date" in frame.columns:
        frame["date"] = pd.to_datetime(frame["date"]).dt.tz_localize(None)
    return frame


def _date_first_columns(columns: Sequence[str] | None) -> list[str] | None:
    if columns is None:
        return None
    out: list[str] = ["date"]
    for column in columns:
        text = str(column)
        if text != "date" and text not in out:
            out.append(text)
    return out


def sync_market_panel(
    specs: Sequence[MarketSymbolSpec],
    *,
    client: YahooFinanceClient | None = None,
    cache_dir: Path = DEFAULT_MARKET_CACHE_DIR,
    period: str = DEFAULT_INCREMENTAL_PERIOD,
    interval: str = "1d",
    start_date: str | None = None,
    end_date: str | None = None,
    force: bool = False,
) -> Path:
    symbol_diagnostics: dict[str, Any] = {}
    for spec in specs:
        frame = sync_market_symbol(
            spec,
            client=client,
            cache_dir=cache_dir,
            period=period,
            interval=interval,
            force=force,
        )
        _, diagnostics = normalize_price_frame(frame)
        symbol_diagnostics[spec.column] = diagnostics.to_dict()
    panel = build_market_panel(
        specs,
        cache_dir=cache_dir,
        start_date=start_date,
        end_date=end_date,
    )
    panel_diagnostics = validate_market_panel(panel)
    write_market_panel_meta(
        Path(cache_dir),
        specs=specs,
        diagnostics={
            "symbols": symbol_diagnostics,
            "panel": panel_diagnostics.to_dict(),
            "force": bool(force),
            "period": "max" if force else period,
            "interval": interval,
        },
    )
    return write_market_panel(panel, cache_dir=cache_dir)


def _safe_name(value: str) -> str:
    return value.replace("/", "__").replace("^", "_")


def _unexpected_business_gaps(dates: pd.Series) -> list[str]:
    if len(dates) < 2:
        return []
    unique = pd.Series(pd.to_datetime(dates).dropna().drop_duplicates()).sort_values().reset_index(drop=True)
    if len(unique) < 2:
        return []
    gaps: list[str] = []
    for prev, curr in zip(unique.iloc[:-1], unique.iloc[1:]):
        expected_next = prev + pd.offsets.BDay(1)
        if expected_next.normalize() < curr.normalize():
            missing = pd.bdate_range(expected_next, curr - pd.offsets.BDay(1))
            if len(missing) <= 1:
                continue
            gaps.append(
                f"{pd.Timestamp(prev).strftime('%Y-%m-%d')}..{pd.Timestamp(curr).strftime('%Y-%m-%d')}"
            )
    return gaps


__all__ = [
    "DEFAULT_MARKET_CACHE_DIR",
    "DEFAULT_MARKET_PANEL_FILENAME",
    "DEFAULT_MARKET_META_FILENAME",
    "DEFAULT_INCREMENTAL_PERIOD",
    "MarketSymbolSpec",
    "PanelValidationDiagnostics",
    "build_market_panel",
    "history_payload_to_frame",
    "load_market_panel",
    "normalize_price_frame",
    "sync_market_panel",
    "sync_market_symbol",
    "validate_market_panel",
    "write_market_panel_meta",
    "write_market_panel",
]
