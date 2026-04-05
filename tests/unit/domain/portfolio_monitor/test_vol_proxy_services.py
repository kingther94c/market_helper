from __future__ import annotations

import pandas as pd
import pytest

from market_helper.domain.portfolio_monitor.services.vol_proxies import (
    proxy_regime_scaled_vol,
    relative_vol_multiplier,
    scaled_forward_vol_from_anchor,
    vol_multiplier,
)


def test_proxy_regime_scaled_vol_scales_reference_vol() -> None:
    assert proxy_regime_scaled_vol(0.20, 25.0, 20.0) == pytest.approx(0.25)


def test_scaled_forward_vol_from_anchor_uses_relative_vol_multiplier() -> None:
    scaled = scaled_forward_vol_from_anchor(0.18, asset_long_term_vol=0.30, anchor_long_term_vol=0.20)
    assert relative_vol_multiplier(0.30, 0.20) == pytest.approx(1.5)
    assert scaled == pytest.approx(0.27)


def test_vol_multiplier_supports_full_sample_and_rolling_modes() -> None:
    index = pd.date_range("2024-01-01", periods=8, freq="D")
    asset_returns = pd.Series([0.02, -0.01, 0.015, -0.012, 0.018, -0.009, 0.014, -0.011], index=index)
    benchmark_returns = pd.Series([0.01, -0.005, 0.008, -0.006, 0.009, -0.004, 0.007, -0.005], index=index)

    full_sample = vol_multiplier(asset_returns, benchmark_returns)
    rolling = vol_multiplier(asset_returns, benchmark_returns, window=4, min_periods=4)

    assert full_sample > 1.0
    assert float(rolling.dropna().iloc[-1]) > 1.0
