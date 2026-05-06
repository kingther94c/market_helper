from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from market_helper.domain.portfolio_monitor.services.commodity_spread_risk import (
    CommoditySpreadLeg,
    CommoditySpreadParameters,
    CommoditySpreadRootConfig,
    commodity_spread_cache_key,
    commodity_spread_cache_path,
    compute_or_load_commodity_spread_risk,
    ewma_weights,
    robust_beta_huber,
    rolling_clip,
)


def test_ewma_weights_normalize_to_mean_one() -> None:
    weights = ewma_weights(20, half_life=5)

    assert len(weights) == 20
    assert weights.mean() == pytest.approx(1.0)
    assert weights[-1] > weights[0]


def test_rolling_clip_bounds_outlier_after_warmup() -> None:
    values = pd.Series([1.0] * 25 + [100.0])

    clipped = rolling_clip(values, window=20, z=2.0)

    assert clipped.iloc[-1] < 100.0


def test_robust_beta_huber_recovers_known_beta_with_outlier() -> None:
    x = pd.Series(np.linspace(-2, 2, 80))
    y = 3.0 + 2.5 * x
    y.iloc[-1] = 100.0

    fitted = robust_beta_huber(y, x, half_life=20, epsilon=1.5, min_observations=30)

    assert fitted is not None
    alpha, beta = fitted
    assert alpha == pytest.approx(3.0, abs=0.5)
    assert beta == pytest.approx(2.5, abs=0.3)


def test_commodity_spread_risk_computes_and_reuses_weekly_cache(tmp_path: Path) -> None:
    config = _ng_config()
    legs = _ng_legs()
    client = _FakeYahooClient(_price_payloads())

    first = compute_or_load_commodity_spread_risk(
        legs,
        config=config,
        yahoo_client=client,
        cache_dir=tmp_path,
        cache_ttl_days=7,
        trading_days=252,
        now=pd.Timestamp("2026-05-06"),
    )

    assert first is not None
    assert first.from_cache is False
    assert first.beta < 0
    assert first.display_quantity == -1.0
    assert first.total_vol_usd > 0
    assert first.vol_ratio == pytest.approx(first.total_vol_usd / first.gross_exposure_usd)
    assert client.calls

    second = compute_or_load_commodity_spread_risk(
        legs,
        config=config,
        yahoo_client=_ExplodingYahooClient(),
        cache_dir=tmp_path,
        cache_ttl_days=7,
        trading_days=252,
        now=pd.Timestamp("2026-05-07"),
    )

    assert second is not None
    assert second.from_cache is True
    assert second.beta == pytest.approx(first.beta)


def test_stale_cache_recomputes_and_failed_recompute_returns_none(tmp_path: Path) -> None:
    config = _ng_config()
    legs = _ng_legs()
    key = commodity_spread_cache_key(legs, config=config, trading_days=252)
    path = commodity_spread_cache_path(key, cache_dir=tmp_path, root="NG", exchange="NYMEX")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "cache_key": key,
                "generated_at": "2026-04-01T00:00:00",
                "alpha": 0.0,
                "beta": -0.5,
                "beta_vol_usd": 1.0,
                "residual_vol_usd": 1.0,
                "total_vol_usd": 2.0,
                "spread_pnl_series": {},
            }
        ),
        encoding="utf-8",
    )

    result = compute_or_load_commodity_spread_risk(
        legs,
        config=config,
        yahoo_client=_ExplodingYahooClient(),
        cache_dir=tmp_path,
        cache_ttl_days=7,
        trading_days=252,
        now=pd.Timestamp("2026-05-06"),
    )

    assert result is None


def test_quantity_change_invalidates_cache_key() -> None:
    config = _ng_config()
    original = _ng_legs()
    changed = (
        original[0],
        CommoditySpreadLeg(
            account="U1",
            root="NG",
            exchange="NYMEX",
            local_symbol="NGF27",
            quantity=2.0,
            multiplier=10000.0,
            latest_price=4.8,
            market_value=96_000.0,
        ),
    )

    assert commodity_spread_cache_key(original, config=config, trading_days=252) != commodity_spread_cache_key(
        changed,
        config=config,
        trading_days=252,
    )


class _FakeYahooClient:
    def __init__(self, payloads: dict[str, dict[str, object]]) -> None:
        self.payloads = payloads
        self.calls: list[str] = []

    def fetch_price_history(self, symbol: str, *, period: str = "5y", interval: str = "1d") -> dict[str, object]:
        self.calls.append(symbol)
        if symbol not in self.payloads:
            raise ValueError(f"missing symbol {symbol}")
        return self.payloads[symbol]


class _ExplodingYahooClient:
    def fetch_price_history(self, symbol: str, *, period: str = "5y", interval: str = "1d") -> dict[str, object]:
        raise AssertionError(f"unexpected Yahoo call for {symbol}")


def _ng_config() -> CommoditySpreadRootConfig:
    return CommoditySpreadRootConfig(
        root="NG",
        exchange="NYMEX",
        front_yahoo_symbol="NG=F",
        contract_yahoo_suffix="NYM",
        parameters=CommoditySpreadParameters(
            window=40,
            half_life=15,
            clip_window=20,
            clip_z=5.0,
            huber_epsilon=1.5,
            min_observations=20,
        ),
    )


def _ng_legs() -> tuple[CommoditySpreadLeg, CommoditySpreadLeg]:
    return (
        CommoditySpreadLeg(
            account="U1",
            root="NG",
            exchange="NYMEX",
            local_symbol="NGN26",
            quantity=-1.0,
            multiplier=10000.0,
            latest_price=3.1,
            market_value=-31_000.0,
        ),
        CommoditySpreadLeg(
            account="U1",
            root="NG",
            exchange="NYMEX",
            local_symbol="NGF27",
            quantity=1.0,
            multiplier=10000.0,
            latest_price=4.8,
            market_value=48_000.0,
        ),
    )


def _price_payloads() -> dict[str, dict[str, object]]:
    index = pd.bdate_range("2025-01-01", periods=180)
    front_moves = pd.Series(0.006 * np.sin(np.arange(len(index)) / 5.0), index=index)
    front = 4.0 + front_moves.cumsum()
    near = 3.0 + (0.70 * front_moves).cumsum()
    far = 4.6 + (0.45 * front_moves).cumsum()
    return {
        "NG=F": _history("NG=F", front),
        "NGN26.NYM": _history("NGN26.NYM", near),
        "NGF27.NYM": _history("NGF27.NYM", far),
    }


def _history(symbol: str, prices: pd.Series) -> dict[str, object]:
    return {
        "symbol": symbol,
        "currency": "USD",
        "prices": [
            {
                "timestamp": int(pd.Timestamp(index).tz_localize("UTC").timestamp()),
                "close": float(value),
                "adjclose": float(value),
            }
            for index, value in prices.items()
        ],
    }
