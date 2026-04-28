from __future__ import annotations

import json
from pathlib import Path

from market_helper.models import EconomicSeries, Observation
import market_helper.workflows.sync_regime_inputs as sync_module


class FakeYahooClient:
    def fetch_price_history(self, symbol: str, *, period: str, interval: str):
        base = {
            "SPY": [100.0, 101.0, 103.02],
            "AGG": [50.0, 50.5, 50.0],
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
            "VIXCLS": 18.0,
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

    monkeypatch.setattr(sync_module, "_resolve_fred_api_key", fake_resolve_fred_api_key)
    monkeypatch.setattr(sync_module, "download_fred_series", fake_download_fred_series)

    result = sync_module.sync_regime_inputs(
        returns_output_path=tmp_path / "regime_returns.json",
        proxy_output_path=tmp_path / "regime_proxies.json",
        yahoo_client=FakeYahooClient(),
    )

    returns = json.loads(result.returns_path.read_text(encoding="utf-8"))
    proxy = json.loads(result.proxy_path.read_text(encoding="utf-8"))
    assert set(returns) == {"EQ", "FI"}
    assert len(returns["EQ"]) == 2
    assert set(proxy) == {"VIX", "MOVE", "HY_OAS", "UST2Y", "UST10Y"}
    assert proxy["VIX"]["2024-01-01"] == 18.0
    assert len(proxy["MOVE"]) == 3
