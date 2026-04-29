from __future__ import annotations

import json
from pathlib import Path

import pytest

from market_helper.models import EconomicSeries, Observation
import market_helper.workflows.sync_regime_inputs as sync_module


class FakeYahooClient:
    def fetch_price_history(self, symbol: str, *, period: str, interval: str):
        base = {
            "SPY": [100.0, 101.0, 103.02],
            "AGG": [50.0, 50.5, 50.0],
            "^VIX": [18.0, 18.5, 19.0],
            "^MOVE": [100.0, 105.0, 110.0],
        }[symbol]
        return {
            "symbol": symbol,
            "prices": [
                {"timestamp": 1_704_067_200 + idx * 86_400, "adjclose": value}
                for idx, value in enumerate(base)
            ],
        }


def test_sync_regime_inputs_writes_returns_and_proxy_json(monkeypatch, tmp_path: Path) -> None:
    def fake_resolve_fred_api_key(api_key):
        return "test-key"

    def fake_download_fred_series(series_id, api_key, observation_start=None):
        values = {
            "BAMLH0A0HYM2": 3.5,
            "DGS2": 4.1,
            "DGS10": 4.3,
        }
        return EconomicSeries(
            series_id=series_id,
            title=series_id,
            units="lin",
            frequency="D",
            observations=[
                Observation(date="2024-01-01", value=values[series_id]),
                Observation(date="2024-01-02", value=values[series_id] + 0.1),
            ],
        )

    def fake_download_fred_csv_rows(series_id):
        raise sync_module.DownloadError("csv unavailable")

    monkeypatch.setattr(sync_module, "_resolve_fred_api_key", fake_resolve_fred_api_key)
    monkeypatch.setattr(sync_module, "download_fred_series", fake_download_fred_series)
    monkeypatch.setattr(sync_module, "_download_fred_csv_rows", fake_download_fred_csv_rows)

    result = sync_module.sync_regime_inputs(
        returns_output_path=tmp_path / "regime_returns.json",
        proxy_output_path=tmp_path / "regime_proxies.json",
        hy_oas_history_path=None,
        yahoo_client=FakeYahooClient(),
    )

    returns = json.loads(result.returns_path.read_text(encoding="utf-8"))
    proxy = json.loads(result.proxy_path.read_text(encoding="utf-8"))
    assert set(returns) == {"EQ", "FI"}
    assert len(returns["EQ"]) == 2
    assert set(proxy) == {"VIX", "MOVE", "HY_OAS", "UST2Y", "UST10Y"}
    assert len(proxy["VIX"]) == 3
    assert len(proxy["MOVE"]) == 3


def test_sync_regime_inputs_wraps_fred_timeout(monkeypatch, tmp_path: Path) -> None:
    def fake_resolve_fred_api_key(api_key):
        return "test-key"

    def fake_download_fred_series(series_id, api_key, observation_start=None):
        raise TimeoutError("read timed out")

    def fake_download_fred_csv_rows(series_id):
        raise sync_module.DownloadError("csv failed")

    monkeypatch.setattr(sync_module, "_resolve_fred_api_key", fake_resolve_fred_api_key)
    monkeypatch.setattr(sync_module, "download_fred_series", fake_download_fred_series)
    monkeypatch.setattr(sync_module, "_download_fred_csv_rows", fake_download_fred_csv_rows)
    monkeypatch.setattr(sync_module.time, "sleep", lambda seconds: None)

    with pytest.raises(RuntimeError, match="FRED download failed for BAMLH0A0HYM2"):
        sync_module.sync_regime_inputs(
            returns_output_path=tmp_path / "regime_returns.json",
            proxy_output_path=tmp_path / "regime_proxies.json",
            hy_oas_history_path=None,
            yahoo_client=FakeYahooClient(),
        )


def test_sync_regime_inputs_uses_fred_csv_fallback(monkeypatch, tmp_path: Path) -> None:
    def fake_resolve_fred_api_key(api_key):
        return "test-key"

    def fake_download_fred_series(series_id, api_key, observation_start=None):
        raise TimeoutError("read timed out")

    def fake_download_fred_csv_rows(series_id):
        return [
            {"observation_date": "2024-01-01", series_id: "1.5"},
            {"observation_date": "2024-01-02", series_id: "1.6"},
        ]

    monkeypatch.setattr(sync_module, "_resolve_fred_api_key", fake_resolve_fred_api_key)
    monkeypatch.setattr(sync_module, "download_fred_series", fake_download_fred_series)
    monkeypatch.setattr(sync_module, "_download_fred_csv_rows", fake_download_fred_csv_rows)
    monkeypatch.setattr(sync_module.time, "sleep", lambda seconds: None)

    result = sync_module.sync_regime_inputs(
        returns_output_path=tmp_path / "regime_returns.json",
        proxy_output_path=tmp_path / "regime_proxies.json",
        hy_oas_history_path=None,
        yahoo_client=FakeYahooClient(),
    )

    proxy = json.loads(result.proxy_path.read_text(encoding="utf-8"))
    assert proxy["HY_OAS"] == {"2024-01-01": 1.5, "2024-01-02": 1.6}


def test_sync_regime_inputs_merges_and_updates_hy_oas_history(monkeypatch, tmp_path: Path) -> None:
    def fake_resolve_fred_api_key(api_key):
        return "test-key"

    def fake_download_fred_series(series_id, api_key, observation_start=None):
        if series_id == "BAMLH0A0HYM2":
            return EconomicSeries(
                series_id=series_id,
                title=series_id,
                units="lin",
                frequency="D",
                observations=[
                    Observation(date="2024-01-02", value=2.0),
                    Observation(date="2024-01-03", value=2.1),
                ],
            )
        return EconomicSeries(
            series_id=series_id,
            title=series_id,
            units="lin",
            frequency="D",
            observations=[Observation(date="2024-01-03", value=4.0)],
        )

    def fake_download_fred_csv_rows(series_id):
        raise sync_module.DownloadError("csv unavailable")

    history_path = tmp_path / "hy_oas_history.csv"
    history_path.write_text("Date,Value\n2024-01-01,1.0\n2024-01-02,1.5\n", encoding="utf-8")
    monkeypatch.setattr(sync_module, "_resolve_fred_api_key", fake_resolve_fred_api_key)
    monkeypatch.setattr(sync_module, "download_fred_series", fake_download_fred_series)
    monkeypatch.setattr(sync_module, "_download_fred_csv_rows", fake_download_fred_csv_rows)

    result = sync_module.sync_regime_inputs(
        returns_output_path=tmp_path / "regime_returns.json",
        proxy_output_path=tmp_path / "regime_proxies.json",
        hy_oas_history_path=history_path,
        yahoo_client=FakeYahooClient(),
    )

    proxy = json.loads(result.proxy_path.read_text(encoding="utf-8"))
    assert proxy["HY_OAS"] == {
        "2024-01-01": 1.0,
        "2024-01-02": 2.0,
        "2024-01-03": 2.1,
    }
    assert list(tmp_path.glob("hy_oas_history.csv.bak-*"))
    updated = history_path.read_text(encoding="utf-8")
    assert "2024-01-03,2.1" in updated
