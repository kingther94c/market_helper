from __future__ import annotations

import pytest

from market_helper.domain.portfolio_monitor.services.fixed_income_vol import (
    proxy_index_to_yield_vol,
    rates_forward_vol_from_proxy,
    yield_vol_to_price_vol,
)


def test_yield_vol_to_price_vol_scales_by_modified_duration() -> None:
    assert yield_vol_to_price_vol(0.01, 7.5) == pytest.approx(0.075)


def test_proxy_index_to_yield_vol_applies_mapping_factor() -> None:
    assert proxy_index_to_yield_vol(110.0, 0.0001) == pytest.approx(0.011)


def test_rates_forward_vol_from_proxy_supports_both_modes() -> None:
    regime_scaled = rates_forward_vol_from_proxy(
        proxy_level=120.0,
        proxy_reference_level=100.0,
        asset_reference_price_vol=0.08,
        mode="regime_scaled_price_vol",
    )
    duration_scaled = rates_forward_vol_from_proxy(
        proxy_level=120.0,
        proxy_reference_level=100.0,
        asset_reference_yield_vol=0.01,
        modified_duration=7.0,
        mode="duration_times_yield_vol",
    )

    assert regime_scaled == pytest.approx(0.096)
    assert duration_scaled == pytest.approx(0.084)
