"""FRED macro panel: fetch, cache, transform, and join macro series to a
daily panel used by the regime-detection macro_rules method.

Data flow:
    configs/regime_detection/fred_series.yml
        -> fetch each series via ``download_fred_series`` (incremental)
        -> cache raw observations at data/interim/fred/{series_id}.feather
        -> apply per-series transform (level / yoy_pct / yoy_diff / ...)
        -> shift by publication_lag_days to avoid lookahead
        -> forward-fill to business-day index
        -> join into data/interim/fred/macro_panel.feather

The panel is keyed by date with one column per series_id, plus two metadata
columns ``_axis:{series_id}`` (not stored) exposed via :func:`load_series_meta`.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Optional, Sequence

import pandas as pd
import yaml

from market_helper.data_library.loader import (
    DownloadError,
    download_fred_series,
    download_fred_series_csv,
)
from market_helper.models import EconomicSeries

DEFAULT_CACHE_DIR = Path("data/interim/fred")
DEFAULT_PANEL_FILENAME = "macro_panel.feather"
DEFAULT_META_FILENAME = "macro_panel_meta.yml"

_ALLOWED_TRANSFORMS = {
    "level",
    "centered",
    "yoy_pct",
    "yoy_diff",
    "inverted_yoy_diff",
}


@dataclass(frozen=True)
class SeriesSpec:
    series_id: str
    axis: str  # "growth" | "inflation"
    transform: str
    transform_param: Optional[float] = None
    weight: float = 1.0
    publication_lag_days: int = 0
    title: Optional[str] = None
    frequency_hint: Optional[str] = None

    def validate(self) -> None:
        if self.axis not in {"growth", "inflation"}:
            raise ValueError(
                f"{self.series_id}: axis must be 'growth' or 'inflation', got {self.axis!r}"
            )
        if self.transform not in _ALLOWED_TRANSFORMS:
            raise ValueError(
                f"{self.series_id}: unsupported transform {self.transform!r}"
            )
        if self.transform == "centered" and self.transform_param is None:
            raise ValueError(
                f"{self.series_id}: 'centered' transform requires transform_param"
            )
        if self.publication_lag_days < 0:
            raise ValueError(
                f"{self.series_id}: publication_lag_days must be non-negative"
            )


def load_series_specs(config_path: str | Path) -> List[SeriesSpec]:
    raw = yaml.safe_load(Path(config_path).read_text())
    if not isinstance(raw, dict) or "series" not in raw:
        raise ValueError(f"{config_path}: missing top-level 'series' key")
    specs: List[SeriesSpec] = []
    for entry in raw["series"]:
        spec = SeriesSpec(
            series_id=str(entry["series_id"]),
            axis=str(entry["axis"]),
            transform=str(entry.get("transform", "level")),
            transform_param=(
                float(entry["transform_param"])
                if entry.get("transform_param") is not None
                else None
            ),
            weight=float(entry.get("weight", 1.0)),
            publication_lag_days=int(entry.get("publication_lag_days", 0)),
            title=entry.get("title"),
            frequency_hint=entry.get("frequency_hint"),
        )
        spec.validate()
        specs.append(spec)
    return specs


# ---------------------------------------------------------------------------
# Raw-cache I/O
# ---------------------------------------------------------------------------

def _raw_cache_path(cache_dir: Path, series_id: str) -> Path:
    return cache_dir / f"{series_id}.feather"


def _series_to_frame(series: EconomicSeries) -> pd.DataFrame:
    if not series.observations:
        return pd.DataFrame(columns=["date", "value"])
    frame = pd.DataFrame(
        [(obs.date, obs.value) for obs in series.observations],
        columns=["date", "value"],
    )
    frame["date"] = pd.to_datetime(frame["date"]).dt.tz_localize(None)
    frame = frame.sort_values("date").drop_duplicates("date", keep="last").reset_index(drop=True)
    return frame


def load_cached_series(cache_dir: Path, series_id: str) -> pd.DataFrame:
    path = _raw_cache_path(cache_dir, series_id)
    if not path.exists():
        return pd.DataFrame(columns=["date", "value"])
    frame = pd.read_feather(path)
    if frame.empty:
        return frame
    frame["date"] = pd.to_datetime(frame["date"]).dt.tz_localize(None)
    return frame.sort_values("date").reset_index(drop=True)


def write_cached_series(cache_dir: Path, series_id: str, frame: pd.DataFrame) -> Path:
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = _raw_cache_path(cache_dir, series_id)
    frame.reset_index(drop=True).to_feather(path)
    return path


def sync_series(
    spec: SeriesSpec,
    api_key: str,
    *,
    cache_dir: Path = DEFAULT_CACHE_DIR,
    observation_start: Optional[str] = None,
    force: bool = False,
) -> pd.DataFrame:
    """Fetch new observations for ``spec`` and merge into the raw-cache feather.

    Incremental: on re-run, queries FRED only from the day *after* the last
    cached observation. Set ``force=True`` to re-fetch full history.
    """
    cache_dir = Path(cache_dir)
    cached = load_cached_series(cache_dir, spec.series_id)

    if force or cached.empty:
        start = observation_start
    else:
        last_date = cached["date"].max()
        start = (last_date + pd.Timedelta(days=1)).strftime("%Y-%m-%d")

    series = _download_series_for_sync(spec, api_key, observation_start=start)
    fresh = _series_to_frame(series)

    if cached.empty:
        merged = fresh
    elif fresh.empty:
        merged = cached
    else:
        merged = (
            pd.concat([cached, fresh], ignore_index=True)
            .sort_values("date")
            .drop_duplicates("date", keep="last")
            .reset_index(drop=True)
        )

    write_cached_series(cache_dir, spec.series_id, merged)
    return merged


def _download_series_for_sync(
    spec: SeriesSpec,
    api_key: str,
    *,
    observation_start: Optional[str],
) -> EconomicSeries:
    csv_error: Exception | None = None
    try:
        return download_fred_series_csv(
            spec.series_id,
            title=spec.title,
            observation_start=observation_start,
        )
    except (DownloadError, ValueError) as exc:
        csv_error = exc

    attempts = 3
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            return download_fred_series(
                series_id=spec.series_id,
                api_key=api_key,
                title=spec.title,
                observation_start=observation_start,
            )
        except (DownloadError, TimeoutError, OSError) as exc:
            last_error = exc
            if attempt >= attempts:
                break
            time.sleep(float(attempt))
    raise RuntimeError(
        f"FRED download failed for {spec.series_id} after CSV fallback and "
        f"{attempts} API attempts. CSV error: {csv_error}. Last API error: {last_error}"
    ) from last_error


def sync_all_series(
    specs: Sequence[SeriesSpec],
    api_key: str,
    *,
    cache_dir: Path = DEFAULT_CACHE_DIR,
    observation_start: Optional[str] = None,
    force: bool = False,
) -> Dict[str, pd.DataFrame]:
    return {
        spec.series_id: sync_series(
            spec,
            api_key,
            cache_dir=cache_dir,
            observation_start=observation_start,
            force=force,
        )
        for spec in specs
    }


# ---------------------------------------------------------------------------
# Transforms
# ---------------------------------------------------------------------------

def _observation_periods_per_year(frame: pd.DataFrame) -> int:
    if len(frame) < 3:
        return 12
    deltas = frame["date"].diff().dropna().dt.days
    if deltas.empty:
        return 12
    median_days = float(deltas.median())
    if median_days <= 2:
        return 252  # daily (business days)
    if median_days <= 8:
        return 52  # weekly
    if median_days <= 45:
        return 12  # monthly
    if median_days <= 100:
        return 4  # quarterly
    return 1


def apply_transform(spec: SeriesSpec, frame: pd.DataFrame) -> pd.DataFrame:
    """Apply the configured transform. Returns a frame with columns
    ``[date, value]`` where value is the transformed signal (NaN where the
    transform is not yet defined, e.g. first 12 months for YoY)."""
    if frame.empty:
        return frame.assign(value=pd.Series(dtype=float))

    working = frame.copy()

    if spec.transform == "level":
        pass
    elif spec.transform == "centered":
        working["value"] = working["value"] - float(spec.transform_param or 0.0)
    elif spec.transform in ("yoy_pct", "yoy_diff", "inverted_yoy_diff"):
        periods = _observation_periods_per_year(working)
        shifted = working["value"].shift(periods)
        if spec.transform == "yoy_pct":
            working["value"] = (working["value"] / shifted - 1.0) * 100.0
        elif spec.transform == "yoy_diff":
            working["value"] = working["value"] - shifted
        else:  # inverted_yoy_diff
            working["value"] = -(working["value"] - shifted)
    else:  # pragma: no cover — guarded by validate()
        raise ValueError(f"unsupported transform {spec.transform!r}")

    return working.reset_index(drop=True)


# ---------------------------------------------------------------------------
# Panel construction
# ---------------------------------------------------------------------------

def _period_end(date: pd.Timestamp, frequency_hint: Optional[str]) -> pd.Timestamp:
    """Approximate the end of the observation period for ``date`` given a
    frequency hint. FRED month-stamps observations to the first day of the
    month; the period actually ends on the last calendar day, so publication
    lag must be measured from month-end not month-start."""
    freq = (frequency_hint or "").lower()
    if freq in ("monthly", "m", "mo"):
        return date + pd.offsets.MonthEnd(0)
    if freq in ("quarterly", "q"):
        return date + pd.offsets.QuarterEnd(0)
    if freq in ("weekly", "w"):
        return date + pd.offsets.Week(weekday=6)
    return date


def build_panel(
    specs: Sequence[SeriesSpec],
    *,
    cache_dir: Path = DEFAULT_CACHE_DIR,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> pd.DataFrame:
    """Build a daily business-day panel of transformed, lag-adjusted series.

    - Raw observations are loaded from the per-series feather cache.
    - Each series is transformed per its ``SeriesSpec`` (YoY etc.).
    - Each observation is shifted forward to the first business day on or
      after ``period_end + publication_lag_days`` so the value only becomes
      visible after its realistic release date.
    - Series are forward-filled into a common business-day index; days before
      a series' first release remain NaN.
    """
    cache_dir = Path(cache_dir)
    raw_frames: Dict[str, pd.DataFrame] = {}
    for spec in specs:
        raw = load_cached_series(cache_dir, spec.series_id)
        if raw.empty:
            continue
        transformed = apply_transform(spec, raw).dropna(subset=["value"])
        if transformed.empty:
            continue

        periods_end = transformed["date"].apply(
            lambda d, hint=spec.frequency_hint: _period_end(d, hint)
        )
        release_date = periods_end + pd.Timedelta(days=spec.publication_lag_days)
        transformed = transformed.assign(release_date=release_date)
        transformed = transformed.sort_values("release_date").reset_index(drop=True)
        raw_frames[spec.series_id] = transformed

    if not raw_frames:
        return pd.DataFrame()

    default_start = min(frame["release_date"].min() for frame in raw_frames.values())
    default_end = max(frame["release_date"].max() for frame in raw_frames.values())
    panel_start = pd.Timestamp(start_date) if start_date else default_start
    panel_end = pd.Timestamp(end_date) if end_date else default_end
    if panel_start > panel_end:
        return pd.DataFrame()

    index = pd.bdate_range(start=panel_start, end=panel_end, name="date")
    panel = pd.DataFrame(index=index)

    for series_id, frame in raw_frames.items():
        aligned = (
            frame.assign(release_bday=_next_bday(frame["release_date"]))
            .drop_duplicates("release_bday", keep="last")
            .set_index("release_bday")["value"]
            .reindex(index)
            .ffill()
        )
        panel[series_id] = aligned

    panel.index.name = "date"
    return panel.reset_index()


def _next_bday(dates: pd.Series) -> pd.Series:
    """Snap each date to the same business day if it's a bday, else the next."""
    return pd.to_datetime(dates).apply(
        lambda d: d if d.weekday() < 5 else d + pd.offsets.BDay(1)
    )


def write_panel(panel: pd.DataFrame, cache_dir: Path = DEFAULT_CACHE_DIR) -> Path:
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / DEFAULT_PANEL_FILENAME
    panel.reset_index(drop=True).to_feather(path)
    return path


def load_panel(path: str | Path) -> pd.DataFrame:
    frame = pd.read_feather(Path(path))
    if "date" in frame.columns:
        frame["date"] = pd.to_datetime(frame["date"]).dt.tz_localize(None)
    return frame


def write_series_meta(
    specs: Sequence[SeriesSpec], cache_dir: Path = DEFAULT_CACHE_DIR
) -> Path:
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / DEFAULT_META_FILENAME
    meta = {
        "series": [
            {
                "series_id": s.series_id,
                "axis": s.axis,
                "transform": s.transform,
                "transform_param": s.transform_param,
                "weight": s.weight,
                "publication_lag_days": s.publication_lag_days,
                "title": s.title,
                "frequency_hint": s.frequency_hint,
            }
            for s in specs
        ]
    }
    path.write_text(yaml.safe_dump(meta, sort_keys=False))
    return path


def load_series_meta(path: str | Path) -> List[SeriesSpec]:
    return load_series_specs(path)


# ---------------------------------------------------------------------------
# Top-level sync entry
# ---------------------------------------------------------------------------

def sync_macro_panel(
    config_path: str | Path,
    api_key: str,
    *,
    cache_dir: Path = DEFAULT_CACHE_DIR,
    observation_start: Optional[str] = None,
    force: bool = False,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> Path:
    """End-to-end: read config, sync each series, build + persist panel.

    Returns the path to the panel feather.
    """
    specs = load_series_specs(config_path)
    sync_all_series(
        specs,
        api_key,
        cache_dir=cache_dir,
        observation_start=observation_start,
        force=force,
    )
    panel = build_panel(
        specs,
        cache_dir=cache_dir,
        start_date=start_date,
        end_date=end_date,
    )
    write_series_meta(specs, cache_dir=cache_dir)
    return write_panel(panel, cache_dir=cache_dir)


def specs_by_axis(specs: Iterable[SeriesSpec]) -> Dict[str, List[SeriesSpec]]:
    axes: Dict[str, List[SeriesSpec]] = {"growth": [], "inflation": []}
    for spec in specs:
        axes.setdefault(spec.axis, []).append(spec)
    return axes


__all__ = [
    "SeriesSpec",
    "DEFAULT_CACHE_DIR",
    "DEFAULT_PANEL_FILENAME",
    "DEFAULT_META_FILENAME",
    "load_series_specs",
    "load_series_meta",
    "write_series_meta",
    "load_cached_series",
    "write_cached_series",
    "sync_series",
    "sync_all_series",
    "apply_transform",
    "build_panel",
    "load_panel",
    "write_panel",
    "sync_macro_panel",
    "specs_by_axis",
]
