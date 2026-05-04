from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from market_helper.data_sources.yahoo_finance.market_panel import (
    MarketSymbolSpec,
    load_cached_market_symbol,
    sync_market_panel,
    validate_market_panel,
)


class _FakeYahooClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []

    def fetch_price_history(self, symbol: str, *, period: str, interval: str):
        self.calls.append((symbol, period, interval))
        dates = ["2026-01-05", "2026-01-06", "2026-01-06", "2026-01-07"]
        return {
            "symbol": symbol,
            "prices": [
                {
                    "timestamp": int(datetime.fromisoformat(day).replace(tzinfo=timezone.utc).timestamp()),
                    "close": 100.0 + idx,
                    "adjclose": 100.0 + idx,
                }
                for idx, day in enumerate(dates)
            ],
        }


def test_incremental_market_sync_merges_cache_and_dedupes(tmp_path: Path) -> None:
    cached = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-01-02", "2026-01-05"]),
            "value": [98.0, 99.0],
            "symbol": ["SPY", "SPY"],
        }
    )
    cached.to_feather(tmp_path / "SPY.feather")
    client = _FakeYahooClient()

    panel_path = sync_market_panel(
        [MarketSymbolSpec("SPY", "SPY")],
        client=client,
        cache_dir=tmp_path,
        period="5d",
        interval="1d",
    )

    assert panel_path.exists()
    assert client.calls == [("SPY", "5d", "1d")]
    merged = load_cached_market_symbol(tmp_path, "SPY")
    assert merged["date"].dt.strftime("%Y-%m-%d").tolist() == [
        "2026-01-02",
        "2026-01-05",
        "2026-01-06",
        "2026-01-07",
    ]
    assert merged["date"].is_unique
    meta = (tmp_path / "market_panel_meta.yml").read_text(encoding="utf-8")
    assert "duplicate_dates_removed" in meta


def test_market_panel_validation_reports_gaps() -> None:
    panel = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-01-02", "2026-01-08"]),
            "SPY": [100.0, 101.0],
        }
    )
    diagnostics = validate_market_panel(panel)
    assert diagnostics.unique_dates is True
    assert diagnostics.unexpected_gap_count >= 1
