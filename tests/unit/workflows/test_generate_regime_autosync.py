"""Unit tests for the auto-sync + historical-baseline behavior of generate_regime."""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

import market_helper.workflows.generate_regime as generate_regime
from market_helper.workflows.generate_regime import (
    _load_or_sync_macro_panel,
    _load_or_sync_market_panel,
)


def _write_market_frame(path: Path, dates: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame({"date": pd.to_datetime(dates), "SPY": [100.0] * len(dates)})
    frame.to_feather(path)


def test_market_loader_merges_historical_baseline_with_live_cache(tmp_path, monkeypatch) -> None:
    historical = tmp_path / "historical.feather"
    live = tmp_path / "live.feather"
    _write_market_frame(historical, ["2024-12-30", "2024-12-31"])
    _write_market_frame(live, ["2025-01-02", "2025-01-03"])
    monkeypatch.setattr(generate_regime, "HISTORICAL_MARKET_PANEL_PATH", historical)

    merged = _load_or_sync_market_panel(
        live_cache_path=live,
        market_config_path=tmp_path / "unused.yml",
        auto_sync=False,
    )

    assert list(merged["date"].dt.strftime("%Y-%m-%d")) == [
        "2024-12-30",
        "2024-12-31",
        "2025-01-02",
        "2025-01-03",
    ]


def test_market_loader_lets_live_cache_win_on_overlapping_dates(tmp_path, monkeypatch) -> None:
    # Historical and live cover the same date — live SPY should win so an
    # operator who re-runs the sync with a corrected feed gets that value.
    historical = tmp_path / "historical.feather"
    live = tmp_path / "live.feather"
    historical.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame({"date": pd.to_datetime(["2024-12-31"]), "SPY": [100.0]}).to_feather(historical)
    pd.DataFrame({"date": pd.to_datetime(["2024-12-31"]), "SPY": [555.0]}).to_feather(live)
    monkeypatch.setattr(generate_regime, "HISTORICAL_MARKET_PANEL_PATH", historical)

    merged = _load_or_sync_market_panel(
        live_cache_path=live,
        market_config_path=tmp_path / "unused.yml",
        auto_sync=False,
    )
    assert len(merged) == 1
    assert float(merged.iloc[0]["SPY"]) == 555.0


def test_market_loader_returns_historical_when_live_missing(tmp_path, monkeypatch) -> None:
    historical = tmp_path / "historical.feather"
    _write_market_frame(historical, ["2024-12-31"])
    monkeypatch.setattr(generate_regime, "HISTORICAL_MARKET_PANEL_PATH", historical)

    merged = _load_or_sync_market_panel(
        live_cache_path=tmp_path / "does_not_exist.feather",
        market_config_path=tmp_path / "unused.yml",
        auto_sync=False,
    )
    assert merged is not None
    assert list(merged["date"].dt.strftime("%Y-%m-%d")) == ["2024-12-31"]


def test_market_loader_returns_none_when_both_missing(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        generate_regime, "HISTORICAL_MARKET_PANEL_PATH", tmp_path / "does_not_exist.feather"
    )
    merged = _load_or_sync_market_panel(
        live_cache_path=tmp_path / "also_missing.feather",
        market_config_path=tmp_path / "unused.yml",
        auto_sync=False,
    )
    assert merged is None


def test_market_loader_triggers_sync_when_live_missing_and_auto_sync_true(
    tmp_path, monkeypatch
) -> None:
    historical = tmp_path / "historical.feather"
    live = tmp_path / "live.feather"
    _write_market_frame(historical, ["2024-12-31"])
    monkeypatch.setattr(generate_regime, "HISTORICAL_MARKET_PANEL_PATH", historical)

    sync_calls: list[dict] = []

    def fake_sync(*, config_path, cache_dir, **kwargs):
        sync_calls.append({"config_path": config_path, "cache_dir": cache_dir})
        _write_market_frame(live, ["2025-01-02"])
        return live

    import market_helper.workflows.sync_market_regime_panel as sync_module

    monkeypatch.setattr(sync_module, "run_market_regime_sync", fake_sync)

    merged = _load_or_sync_market_panel(
        live_cache_path=live,
        market_config_path=tmp_path / "config.yml",
        auto_sync=True,
    )
    assert len(sync_calls) == 1
    assert merged is not None
    assert "2025-01-02" in merged["date"].dt.strftime("%Y-%m-%d").tolist()


def test_macro_loader_returns_none_when_key_missing(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    monkeypatch.setattr(generate_regime, "_have_fred_api_key", lambda: False)

    panel = _load_or_sync_macro_panel(
        panel_path=tmp_path / "missing.feather",
        series_config_path=tmp_path / "unused.yml",
        auto_sync=True,
    )
    assert panel is None


def test_macro_loader_skips_sync_when_auto_sync_disabled(tmp_path, monkeypatch) -> None:
    # Even with a key present, --no-auto-sync should not trigger a real
    # FRED roundtrip. Engine output gracefully degrades to market-only.
    monkeypatch.setattr(generate_regime, "_have_fred_api_key", lambda: True)
    panel = _load_or_sync_macro_panel(
        panel_path=tmp_path / "missing.feather",
        series_config_path=tmp_path / "unused.yml",
        auto_sync=False,
    )
    assert panel is None
