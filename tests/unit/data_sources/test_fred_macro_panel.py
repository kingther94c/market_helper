from __future__ import annotations

from pathlib import Path
from typing import List

import pandas as pd
import pytest
import yaml

from market_helper.data_sources.fred import macro_panel as mp
from market_helper.data_sources.fred.macro_panel import (
    SeriesSpec,
    apply_transform,
    build_panel,
    load_cached_series,
    load_series_specs,
    sync_series,
)
from market_helper.models import EconomicSeries, Observation


# ---------------------------------------------------------------------------
# SeriesSpec + config loading
# ---------------------------------------------------------------------------

def test_series_spec_validate_rejects_bad_axis() -> None:
    with pytest.raises(ValueError, match="axis"):
        SeriesSpec(series_id="X", axis="bogus", transform="level").validate()


def test_series_spec_validate_rejects_bad_transform() -> None:
    with pytest.raises(ValueError, match="transform"):
        SeriesSpec(series_id="X", axis="growth", transform="nope").validate()


def test_series_spec_centered_requires_transform_param() -> None:
    with pytest.raises(ValueError, match="transform_param"):
        SeriesSpec(series_id="X", axis="growth", transform="centered").validate()


def test_load_series_specs_from_yaml(tmp_path: Path) -> None:
    cfg = tmp_path / "series.yml"
    cfg.write_text(
        yaml.safe_dump(
            {
                "series": [
                    {
                        "series_id": "NAPM",
                        "axis": "growth",
                        "transform": "centered",
                        "transform_param": 50.0,
                        "publication_lag_days": 3,
                        "frequency_hint": "monthly",
                    },
                    {
                        "series_id": "CPIAUCSL",
                        "axis": "inflation",
                        "transform": "yoy_pct",
                        "weight": 1.5,
                        "publication_lag_days": 14,
                        "frequency_hint": "monthly",
                    },
                ]
            }
        )
    )
    specs = load_series_specs(cfg)
    assert [s.series_id for s in specs] == ["NAPM", "CPIAUCSL"]
    assert specs[0].transform_param == 50.0
    assert specs[1].weight == 1.5


# ---------------------------------------------------------------------------
# apply_transform
# ---------------------------------------------------------------------------

def _monthly_frame(values: List[float], start: str = "2020-01-01") -> pd.DataFrame:
    dates = pd.date_range(start=start, periods=len(values), freq="MS")
    return pd.DataFrame({"date": dates, "value": values})


def test_apply_transform_level_passthrough() -> None:
    frame = _monthly_frame([1.0, 2.0, 3.0])
    spec = SeriesSpec(series_id="X", axis="growth", transform="level")
    out = apply_transform(spec, frame)
    assert out["value"].tolist() == [1.0, 2.0, 3.0]


def test_apply_transform_centered() -> None:
    frame = _monthly_frame([48.0, 50.0, 52.0])
    spec = SeriesSpec(
        series_id="NAPM", axis="growth", transform="centered", transform_param=50.0
    )
    out = apply_transform(spec, frame)
    assert out["value"].tolist() == [-2.0, 0.0, 2.0]


def test_apply_transform_yoy_pct_monthly() -> None:
    # 14 months so month-13 vs month-1 exists
    values = [100.0 + i for i in range(14)]
    frame = _monthly_frame(values)
    spec = SeriesSpec(series_id="X", axis="inflation", transform="yoy_pct")
    out = apply_transform(spec, frame)
    # First 12 are NaN (no 12-month prior), then month-13 = (113/101 - 1)*100
    assert out["value"].iloc[:12].isna().all()
    assert out["value"].iloc[12] == pytest.approx((112.0 / 100.0 - 1.0) * 100.0)
    assert out["value"].iloc[13] == pytest.approx((113.0 / 101.0 - 1.0) * 100.0)


def test_apply_transform_inverted_yoy_diff() -> None:
    # unemployment rising by 0.5 over 12 months -> inverted_yoy_diff = -0.5
    values = [5.0] * 12 + [5.5]
    frame = _monthly_frame(values)
    spec = SeriesSpec(series_id="UNRATE", axis="growth", transform="inverted_yoy_diff")
    out = apply_transform(spec, frame)
    assert out["value"].iloc[12] == pytest.approx(-0.5)


# ---------------------------------------------------------------------------
# Raw cache + incremental sync
# ---------------------------------------------------------------------------

def test_sync_series_incremental_merges(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: List[dict] = []

    def _fake_download(series_id: str, api_key: str, **kwargs):
        calls.append({"series_id": series_id, **kwargs})
        if kwargs.get("observation_start") is None:
            observations = [
                Observation(date="2020-01-01", value=1.0),
                Observation(date="2020-02-01", value=2.0),
            ]
        else:
            observations = [Observation(date="2020-03-01", value=3.0)]
        return EconomicSeries(
            series_id=series_id,
            title=series_id,
            units="lin",
            frequency="m",
            observations=observations,
        )

    def _fake_download_csv(series_id: str, **kwargs):
        raise mp.DownloadError("csv unavailable")

    monkeypatch.setattr(mp, "download_fred_series", _fake_download)
    monkeypatch.setattr(mp, "download_fred_series_csv", _fake_download_csv)
    spec = SeriesSpec(series_id="TEST", axis="growth", transform="level")

    first = sync_series(spec, "key", cache_dir=tmp_path)
    assert first["value"].tolist() == [1.0, 2.0]

    second = sync_series(spec, "key", cache_dir=tmp_path)
    assert second["value"].tolist() == [1.0, 2.0, 3.0]

    # Second call should have passed observation_start past the last cached date.
    assert calls[1]["observation_start"] is not None
    assert calls[1]["observation_start"] >= "2020-02-02"

    reloaded = load_cached_series(tmp_path, "TEST")
    assert reloaded["value"].tolist() == [1.0, 2.0, 3.0]


def test_sync_series_force_replaces_history(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: List[dict] = []

    def _fake_download(series_id: str, api_key: str, **kwargs):
        calls.append(kwargs)
        return EconomicSeries(
            series_id=series_id,
            title=series_id,
            units="lin",
            frequency="m",
            observations=[Observation(date="2020-01-01", value=99.0)],
        )

    def _fake_download_csv(series_id: str, **kwargs):
        raise mp.DownloadError("csv unavailable")

    monkeypatch.setattr(mp, "download_fred_series", _fake_download)
    monkeypatch.setattr(mp, "download_fred_series_csv", _fake_download_csv)
    spec = SeriesSpec(series_id="TEST", axis="growth", transform="level")
    sync_series(spec, "key", cache_dir=tmp_path)
    sync_series(spec, "key", cache_dir=tmp_path, force=True)
    # force=True sends observation_start=None on the second call
    assert calls[1]["observation_start"] is None


def test_sync_series_uses_fred_csv_before_api(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    api_calls: List[dict] = []

    def _fake_download(series_id: str, api_key: str, **kwargs):
        api_calls.append({"series_id": series_id, **kwargs})
        raise mp.DownloadError("api timed out")

    def _fake_download_csv(series_id: str, **kwargs):
        return EconomicSeries(
            series_id=series_id,
            title=series_id,
            units="lin",
            frequency="m",
            observations=[
                Observation(date="2020-01-01", value=1.0),
                Observation(date="2020-02-01", value=2.0),
            ],
        )

    monkeypatch.setattr(mp, "download_fred_series", _fake_download)
    monkeypatch.setattr(mp, "download_fred_series_csv", _fake_download_csv)
    monkeypatch.setattr(mp.time, "sleep", lambda seconds: None)

    spec = SeriesSpec(series_id="NAPM", axis="growth", transform="level")
    synced = sync_series(spec, "key", cache_dir=tmp_path)

    assert api_calls == []
    assert synced["value"].tolist() == [1.0, 2.0]


# ---------------------------------------------------------------------------
# Panel construction
# ---------------------------------------------------------------------------

def _write_cached(cache_dir: Path, series_id: str, frame: pd.DataFrame) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    frame.reset_index(drop=True).to_feather(cache_dir / f"{series_id}.feather")


def test_build_panel_forward_fills_with_publication_lag(tmp_path: Path) -> None:
    # Monthly series; observation date = first-of-month (FRED convention).
    # With publication_lag_days=10 and frequency_hint=monthly, month-end + 10d
    # determines release date. value should be NaN before release, then carry.
    frame = _monthly_frame([1.0, 2.0, 3.0], start="2020-01-01")
    _write_cached(tmp_path, "TEST", frame)
    spec = SeriesSpec(
        series_id="TEST",
        axis="growth",
        transform="level",
        publication_lag_days=10,
        frequency_hint="monthly",
    )
    panel = build_panel(
        [spec],
        cache_dir=tmp_path,
        start_date="2020-01-15",
        end_date="2020-04-30",
    )
    panel = panel.set_index("date")

    # Jan observation: period end = 2020-01-31; released on 2020-02-10.
    assert pd.isna(panel.loc[pd.Timestamp("2020-02-07"), "TEST"])
    assert panel.loc[pd.Timestamp("2020-02-10"), "TEST"] == 1.0
    # ffill into a mid-month bday
    assert panel.loc[pd.Timestamp("2020-02-20"), "TEST"] == 1.0
    # Feb observation: period end = 2020-02-29; released on 2020-03-10.
    assert panel.loc[pd.Timestamp("2020-03-10"), "TEST"] == 2.0


def test_build_panel_multi_series_joins_independently(tmp_path: Path) -> None:
    fast = _monthly_frame([10.0, 20.0, 30.0], start="2020-01-01")
    slow = pd.DataFrame(
        {"date": pd.to_datetime(["2020-03-01"]), "value": [99.0]}
    )
    _write_cached(tmp_path, "FAST", fast)
    _write_cached(tmp_path, "SLOW", slow)
    specs = [
        SeriesSpec(
            series_id="FAST",
            axis="growth",
            transform="level",
            publication_lag_days=0,
            frequency_hint="monthly",
        ),
        SeriesSpec(
            series_id="SLOW",
            axis="inflation",
            transform="level",
            publication_lag_days=0,
            frequency_hint="monthly",
        ),
    ]
    panel = build_panel(
        specs,
        cache_dir=tmp_path,
        start_date="2020-01-31",
        end_date="2020-04-10",
    )
    assert set(panel.columns) == {"date", "FAST", "SLOW"}
    indexed = panel.set_index("date")
    # Before SLOW releases, FAST is populated but SLOW is NaN.
    snapshot = indexed.loc[pd.Timestamp("2020-02-28")]
    assert snapshot["FAST"] == 10.0
    assert pd.isna(snapshot["SLOW"])
    # After SLOW's March release, both populated.
    snapshot = indexed.loc[pd.Timestamp("2020-04-10")]
    assert snapshot["FAST"] == 30.0
    assert snapshot["SLOW"] == 99.0


def test_build_panel_empty_when_no_caches(tmp_path: Path) -> None:
    specs = [SeriesSpec(series_id="MISSING", axis="growth", transform="level")]
    panel = build_panel(specs, cache_dir=tmp_path)
    assert panel.empty
