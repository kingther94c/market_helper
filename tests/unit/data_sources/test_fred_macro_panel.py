from __future__ import annotations

import json
from pathlib import Path
from typing import List

import pandas as pd
import pytest
import yaml

from market_helper.data_sources.fred import macro_panel as mp
from market_helper.data_sources.fred.macro_panel import (
    FRESHNESS_AGE_COLUMN_PREFIX,
    SeriesSpec,
    apply_transform,
    build_panel,
    load_cached_series,
    load_panel,
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


def test_load_panel_projects_requested_columns(tmp_path: Path) -> None:
    path = tmp_path / "macro_panel.feather"
    pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-01-02"]),
            "KEEP": [1.0],
            "DROP": [2.0],
        }
    ).to_feather(path)

    frame = load_panel(path, columns=["KEEP"])

    assert frame.columns.tolist() == ["date", "KEEP"]


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

    first, first_outcome = sync_series(spec, "key", cache_dir=tmp_path)
    assert first["value"].tolist() == [1.0, 2.0]
    assert first_outcome.status == "ok"
    assert first_outcome.source == "fred_api"

    second, _ = sync_series(spec, "key", cache_dir=tmp_path)
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
    synced, outcome = sync_series(spec, "key", cache_dir=tmp_path)

    assert api_calls == []
    assert synced["value"].tolist() == [1.0, 2.0]
    assert outcome.source == "fred_graph_csv"


def test_resolve_fred_http_timeout_respects_env_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("FRED_HTTP_TIMEOUT_SECONDS", raising=False)
    assert mp._resolve_fred_http_timeout() == 60
    monkeypatch.setenv("FRED_HTTP_TIMEOUT_SECONDS", "120")
    assert mp._resolve_fred_http_timeout() == 120
    # Garbage / non-positive values fall back to the safe 60s default.
    monkeypatch.setenv("FRED_HTTP_TIMEOUT_SECONDS", "not-a-number")
    assert mp._resolve_fred_http_timeout() == 60


def test_sync_series_passes_http_timeout_and_backs_off_on_api_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The CSV + API fetches carry the resolved (generous) HTTP timeout, and a
    transient (non-timeout) API failure gets one backed-off retry rather than
    failing the whole macro sync. Timeout-class CSV failures skip the retry
    loop entirely (covered separately) — repeated 30-60s timeouts were the
    observed multi-minute stall mode."""
    api_calls: List[dict] = []
    sleeps: List[float] = []

    def _fake_download_csv(series_id: str, **kwargs):
        # Simulate a genuine fredgraph transport failure (curl/connection
        # error, NOT a timeout) so the API fallback with retry takes over. An
        # *empty* incremental window is a no-op (covered by the dedicated
        # test below) and would NOT reach the API path.
        assert kwargs.get("timeout") == mp.DEFAULT_FRED_HTTP_TIMEOUT_SECONDS
        raise mp.DownloadError("fredgraph CSV fetch failed: bad gateway")

    def _fake_download(series_id: str, api_key: str, **kwargs):
        api_calls.append({"series_id": series_id, **kwargs})
        if len(api_calls) < 2:
            raise mp.DownloadError("api transport error")
        return EconomicSeries(
            series_id=series_id,
            title=series_id,
            units="lin",
            frequency="m",
            observations=[Observation(date="2020-01-01", value=1.0)],
        )

    monkeypatch.setattr(mp, "download_fred_series_csv", _fake_download_csv)
    monkeypatch.setattr(mp, "download_fred_series", _fake_download)
    monkeypatch.setattr(mp.time, "sleep", lambda seconds: sleeps.append(seconds))

    spec = SeriesSpec(series_id="UNRATE", axis="growth", transform="level")
    synced, outcome = sync_series(spec, "key", cache_dir=tmp_path)

    assert synced["value"].tolist() == [1.0]
    assert outcome.status == "ok"
    assert len(api_calls) == 2  # failed once, succeeded on the retry
    assert all(
        call.get("timeout") == mp.DEFAULT_FRED_HTTP_TIMEOUT_SECONDS for call in api_calls
    )
    assert sleeps == [2.0]  # backoff between the two attempts


def test_sync_series_timeout_csv_failure_skips_api_retry_loop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When the CSV transport *timed out*, the network path to FRED is the
    problem — the API gets a single attempt, no retry loop (each attempt costs
    a 30-60s timeout)."""
    api_calls: List[dict] = []
    sleeps: List[float] = []

    def _fake_download_csv(series_id: str, **kwargs):
        raise mp.DownloadError("Timeout while requesting https://fred.stlouisfed.org/...")

    def _fake_download(series_id: str, api_key: str, **kwargs):
        api_calls.append({"series_id": series_id})
        raise mp.DownloadError("Timeout while requesting https://api.stlouisfed.org/...")

    monkeypatch.setattr(mp, "download_fred_series_csv", _fake_download_csv)
    monkeypatch.setattr(mp, "download_fred_series", _fake_download)
    monkeypatch.setattr(mp.time, "sleep", lambda seconds: sleeps.append(seconds))

    seed = pd.DataFrame({"date": pd.to_datetime(["2026-06-01"]), "value": [4.0]})
    mp.write_cached_series(tmp_path, "UNRATE", seed)
    spec = SeriesSpec(series_id="UNRATE", axis="growth", transform="level")

    synced, outcome = sync_series(spec, "key", cache_dir=tmp_path)

    assert len(api_calls) == 1
    assert sleeps == []
    # Cached real observations are preserved and the degradation is explicit.
    assert outcome.status == "cached"
    assert "cached observations through 2026-06-01" in outcome.detail
    assert synced["value"].tolist() == [4.0]


def test_sync_series_incremental_empty_window_is_noop_without_api_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A monthly series whose latest print is already cached has no new
    observations until the next release. The incremental CSV fetch then returns
    an empty window, which must be treated as 'already current': keep the cache
    and do NOT fall through to the JSON API.

    Regression for the recurring mid-month breakage
    ``Regime engine failed: FRED download failed for UNRATE ...`` — the empty
    window was raised as a download error, which then hit the JSON API and
    timed out, failing the whole regime refresh.
    """
    from market_helper.data_library import loader

    # fredgraph returns the full history; the latest print (2026-04-01) is
    # already cached, so the incremental window [2026-04-02, today] is empty.
    full_rows = [
        {"observation_date": "2026-02-01", "UNRATE": "4.0"},
        {"observation_date": "2026-03-01", "UNRATE": "4.1"},
        {"observation_date": "2026-04-01", "UNRATE": "4.2"},
    ]
    monkeypatch.setattr(
        loader,
        "_download_fred_graph_csv_rows",
        lambda series_id, *, timeout, observation_start=None, observation_end=None: (
            full_rows,
            ["observation_date", "UNRATE"],
        ),
    )

    api_calls: List[dict] = []

    def _boom_api(series_id: str, api_key: str, **kwargs):
        api_calls.append({"series_id": series_id, **kwargs})
        raise AssertionError(
            "JSON FRED API must not be hit for an empty incremental window"
        )

    monkeypatch.setattr(mp, "download_fred_series", _boom_api)

    spec = SeriesSpec(
        series_id="UNRATE", axis="growth", transform="level", frequency_hint="monthly"
    )
    seed = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-02-01", "2026-03-01", "2026-04-01"]),
            "value": [4.0, 4.1, 4.2],
        }
    )
    mp.write_cached_series(tmp_path, "UNRATE", seed)

    synced, outcome = sync_series(spec, "key", cache_dir=tmp_path)

    assert api_calls == []  # no JSON API call -> no timeout surface
    assert outcome.status == "ok"
    assert synced["value"].tolist() == [4.0, 4.1, 4.2]  # cache preserved
    reloaded = load_cached_series(tmp_path, "UNRATE")
    assert reloaded["value"].tolist() == [4.0, 4.1, 4.2]


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
    assert panel.loc[pd.Timestamp("2020-02-10"), f"{FRESHNESS_AGE_COLUMN_PREFIX}TEST"] == 0.0
    # ffill into a mid-month bday
    assert panel.loc[pd.Timestamp("2020-02-20"), "TEST"] == 1.0
    assert panel.loc[pd.Timestamp("2020-02-20"), f"{FRESHNESS_AGE_COLUMN_PREFIX}TEST"] == 8.0
    # Feb observation: period end = 2020-02-29; released on 2020-03-10.
    assert panel.loc[pd.Timestamp("2020-03-10"), "TEST"] == 2.0
    assert panel.loc[pd.Timestamp("2020-03-10"), f"{FRESHNESS_AGE_COLUMN_PREFIX}TEST"] == 0.0


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
    assert set(panel.columns) == {
        "date",
        "FAST",
        "SLOW",
        f"{FRESHNESS_AGE_COLUMN_PREFIX}FAST",
        f"{FRESHNESS_AGE_COLUMN_PREFIX}SLOW",
    }
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


# ---------------------------------------------------------------------------
# Treasury fallback + per-series tolerance + circuit breaker
# ---------------------------------------------------------------------------


def test_sync_series_falls_back_to_treasury_for_derivable_series(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When both FRED transports fail for a treasury-derivable series, the
    observations are rebuilt from treasury.gov (real published data) and the
    outcome is tagged as a fallback — never silently, never fabricated."""

    def _csv_boom(series_id: str, **kwargs):
        raise mp.DownloadError("Timeout while requesting fredgraph")

    def _api_boom(series_id: str, api_key: str, **kwargs):
        raise mp.DownloadError("Timeout while requesting api.stlouisfed.org")

    def _fake_treasury(series_id: str, **kwargs):
        assert series_id == "T10Y2Y"
        return EconomicSeries(
            series_id=series_id,
            title=series_id,
            units="lin",
            frequency="daily",
            observations=[Observation(date="2026-06-10", value=0.42)],
            metadata={"source": "treasury_par_yield_curve"},
        )

    monkeypatch.setattr(mp, "download_fred_series_csv", _csv_boom)
    monkeypatch.setattr(mp, "download_fred_series", _api_boom)
    monkeypatch.setattr(mp, "download_treasury_derived_series", _fake_treasury)
    monkeypatch.setattr(mp.time, "sleep", lambda seconds: None)

    spec = SeriesSpec(series_id="T10Y2Y", axis="growth", transform="level")
    synced, outcome = sync_series(spec, "key", cache_dir=tmp_path)

    assert outcome.status == "fallback"
    assert outcome.source == "treasury_par_yield_curve"
    assert synced["value"].tolist() == [0.42]
    # The treasury observations are merged into the same real-data cache.
    reloaded = load_cached_series(tmp_path, "T10Y2Y")
    assert reloaded["value"].tolist() == [0.42]


def test_sync_all_series_tolerates_one_failure_and_trips_breaker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One failing series must not abort the others (the 2026-06-10 outage
    aborted a 24-series sync on its 6th series). After two timeout-class
    failures the breaker opens — but only for *treasury-derivable* series
    (the observed failure class): other series still get their FRED attempt,
    because monthly/weekly fetches were healthy throughout the outage."""
    csv_calls: List[str] = []

    def _fake_csv(series_id: str, **kwargs):
        csv_calls.append(series_id)
        if series_id in ("BAD1", "BAD2"):
            raise mp.DownloadError("Timeout while requesting fredgraph")
        return EconomicSeries(
            series_id=series_id,
            title=series_id,
            units="lin",
            frequency="m",
            observations=[Observation(date="2026-06-01", value=1.0)],
        )

    def _api_boom(series_id: str, api_key: str, **kwargs):
        raise mp.DownloadError("Timeout while requesting api.stlouisfed.org")

    def _fake_treasury(series_id: str, **kwargs):
        return EconomicSeries(
            series_id=series_id,
            title=series_id,
            units="lin",
            frequency="daily",
            observations=[Observation(date="2026-06-10", value=0.42)],
            metadata={"source": "treasury_par_yield_curve"},
        )

    monkeypatch.setattr(mp, "download_fred_series_csv", _fake_csv)
    monkeypatch.setattr(mp, "download_fred_series", _api_boom)
    monkeypatch.setattr(mp, "download_treasury_derived_series", _fake_treasury)
    monkeypatch.setattr(mp.time, "sleep", lambda seconds: None)

    # Seed caches for the failing series so their real history survives.
    seed = pd.DataFrame({"date": pd.to_datetime(["2026-05-30"]), "value": [9.0]})
    mp.write_cached_series(tmp_path, "BAD1", seed)
    mp.write_cached_series(tmp_path, "BAD2", seed)

    specs = [
        SeriesSpec(series_id="GOOD1", axis="growth", transform="level"),
        SeriesSpec(series_id="BAD1", axis="growth", transform="level"),
        SeriesSpec(series_id="BAD2", axis="growth", transform="level"),
        # Treasury-derivable: breaker sends it straight to treasury.gov.
        SeriesSpec(series_id="T5YIE", axis="inflation", transform="level"),
        # Not derivable: still gets its normal FRED attempt.
        SeriesSpec(series_id="GOOD2", axis="growth", transform="level"),
    ]
    frames, outcomes = mp.sync_all_series(specs, "key", cache_dir=tmp_path)

    assert outcomes["GOOD1"].status == "ok"
    assert outcomes["BAD1"].status == "cached"
    assert outcomes["BAD2"].status == "cached"
    # Breaker open after BAD1+BAD2 timeouts: the derivable series skips FRED
    # and lands on treasury.gov without burning another 60-120s of timeouts...
    assert "T5YIE" not in csv_calls
    assert outcomes["T5YIE"].status == "fallback"
    assert outcomes["T5YIE"].source == "treasury_par_yield_curve"
    # ...while the non-derivable series still tries (and here succeeds on) FRED.
    assert "GOOD2" in csv_calls
    assert outcomes["GOOD2"].status == "ok"
    # Failing series kept their cached real observations.
    assert frames["BAD1"]["value"].tolist() == [9.0]


def test_sync_macro_panel_builds_panel_despite_partial_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = tmp_path / "fred_series.yml"
    config.write_text(
        """
series:
  - series_id: GOODM
    axis: growth
    transform: level
    frequency_hint: monthly
  - series_id: BADM
    axis: inflation
    transform: level
    frequency_hint: monthly
""",
        encoding="utf-8",
    )

    def _fake_csv(series_id: str, **kwargs):
        if series_id == "BADM":
            raise mp.DownloadError("Timeout while requesting fredgraph")
        return EconomicSeries(
            series_id=series_id,
            title=series_id,
            units="lin",
            frequency="m",
            observations=[
                Observation(date="2026-05-01", value=1.0),
                Observation(date="2026-06-01", value=2.0),
            ],
        )

    def _api_boom(series_id: str, api_key: str, **kwargs):
        raise mp.DownloadError("Timeout while requesting api.stlouisfed.org")

    monkeypatch.setattr(mp, "download_fred_series_csv", _fake_csv)
    monkeypatch.setattr(mp, "download_fred_series", _api_boom)
    monkeypatch.setattr(mp.time, "sleep", lambda seconds: None)

    cache_dir = tmp_path / "cache"
    seed = pd.DataFrame({"date": pd.to_datetime(["2026-04-01"]), "value": [7.0]})
    mp.write_cached_series(cache_dir, "BADM", seed)

    panel_path = mp.sync_macro_panel(config, "key", cache_dir=cache_dir)

    # Panel rebuilt with the good series fresh and the bad series from cache.
    panel = mp.load_panel(panel_path)
    assert "GOODM" in panel.columns
    assert "BADM" in panel.columns

    status = json.loads((cache_dir / mp.DEFAULT_SYNC_STATUS_FILENAME).read_text(encoding="utf-8"))
    assert status["series"]["GOODM"]["status"] == "ok"
    assert status["series"]["BADM"]["status"] == "cached"
    assert "cached observations through 2026-04-01" in status["series"]["BADM"]["detail"]
