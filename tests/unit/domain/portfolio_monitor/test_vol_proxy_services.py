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


# ---------------------------------------------------------------------------
# Validator edge cases: scaling functions must reject pathological inputs.
# These tests pin the input contract that other risk-report code relies on.
# ---------------------------------------------------------------------------


def test_proxy_regime_scaled_vol_rejects_negative_reference_vol() -> None:
    with pytest.raises(ValueError, match="asset_reference_vol"):
        proxy_regime_scaled_vol(-0.10, 25.0, 20.0)


def test_proxy_regime_scaled_vol_rejects_negative_current_proxy_level() -> None:
    with pytest.raises(ValueError, match="proxy_current_level"):
        proxy_regime_scaled_vol(0.20, -25.0, 20.0)


def test_proxy_regime_scaled_vol_rejects_zero_reference_proxy_level() -> None:
    # Reference level is the denominator; must be strictly positive.
    with pytest.raises(ValueError, match="proxy_reference_level"):
        proxy_regime_scaled_vol(0.20, 25.0, 0.0)


def test_proxy_regime_scaled_vol_rejects_negative_reference_proxy_level() -> None:
    with pytest.raises(ValueError, match="proxy_reference_level"):
        proxy_regime_scaled_vol(0.20, 25.0, -20.0)


def test_proxy_regime_scaled_vol_floor_at_zero_clamps_zero_current_to_zero() -> None:
    assert proxy_regime_scaled_vol(0.20, 0.0, 20.0) == pytest.approx(0.0)


def test_proxy_regime_scaled_vol_accepts_pandas_series_inputs() -> None:
    asset_vol = pd.Series([0.10, 0.20, 0.30], index=pd.RangeIndex(3))
    current_level = pd.Series([10.0, 20.0, 30.0], index=pd.RangeIndex(3))
    reference_level = pd.Series([10.0, 10.0, 10.0], index=pd.RangeIndex(3))

    scaled = proxy_regime_scaled_vol(asset_vol, current_level, reference_level)

    assert isinstance(scaled, pd.Series)
    assert scaled.iloc[0] == pytest.approx(0.10)
    assert scaled.iloc[1] == pytest.approx(0.40)
    assert scaled.iloc[2] == pytest.approx(0.90)


def test_relative_vol_multiplier_rejects_zero_anchor() -> None:
    with pytest.raises(ValueError, match="anchor_long_term_vol"):
        relative_vol_multiplier(0.30, 0.0)


def test_relative_vol_multiplier_rejects_negative_anchor() -> None:
    with pytest.raises(ValueError, match="anchor_long_term_vol"):
        relative_vol_multiplier(0.30, -0.20)


def test_relative_vol_multiplier_rejects_negative_asset() -> None:
    with pytest.raises(ValueError, match="asset_long_term_vol"):
        relative_vol_multiplier(-0.30, 0.20)


def test_vol_multiplier_returns_zero_when_benchmark_has_zero_vol() -> None:
    # Constant benchmark series → benchmark realized vol is 0 → multiplier
    # gracefully returns 0.0 instead of dividing by zero.
    index = pd.date_range("2024-01-01", periods=10, freq="D")
    asset_returns = pd.Series([0.01] * 10, index=index)
    flat_benchmark = pd.Series([0.0] * 10, index=index)

    assert vol_multiplier(asset_returns, flat_benchmark) == 0.0
