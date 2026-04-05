from __future__ import annotations

import math

import pandas as pd
import pytest

from market_helper.domain.portfolio_monitor.services.volatility import (
    alpha_to_halflife,
    align_series,
    annualize_vol,
    arithmetic_blend_vol,
    compute_returns,
    conservative_vol,
    deannualize_vol,
    dual_window_geometric_vol,
    ewma_vol,
    expanding_vol,
    geometric_blend_vol,
    halflife_to_alpha,
    halflife_to_lambda,
    historical_vol,
    lambda_to_halflife,
    last_valid_scalar,
    long_term_vol,
    rolling_vol,
    trailing_vol,
    vol_ratio,
    weighted_blend,
)


def test_compute_returns_supports_log_and_simple_methods() -> None:
    prices = pd.Series([100.0, 110.0, 121.0], index=pd.date_range("2024-01-01", periods=3, freq="D"))

    log_returns = compute_returns(prices, method="log")
    simple_returns = compute_returns(prices, method="simple")

    assert len(log_returns) == 2
    assert log_returns.iloc[0] == pytest.approx(math.log(1.1))
    assert simple_returns.iloc[0] == pytest.approx(0.1)


def test_volatility_helpers_accept_prices_and_returns() -> None:
    prices = pd.Series(
        [100.0, 101.0, 103.0, 102.0, 104.0, 107.0, 109.0],
        index=pd.date_range("2024-01-01", periods=7, freq="D"),
    )
    returns = compute_returns(prices, method="log")

    hist = historical_vol(prices=prices)
    trailing = trailing_vol(returns=returns, window=3)
    rolling = rolling_vol(returns=returns, window=3, min_periods=3)
    expanding = expanding_vol(returns=returns, min_periods=3)
    long_term = long_term_vol(returns=returns, lookback=5)

    assert hist > 0
    assert trailing == pytest.approx(last_valid_scalar(rolling) or 0.0)
    assert pd.isna(expanding.iloc[1])
    assert long_term > 0


def test_ewma_parameter_conversions_round_trip() -> None:
    halflife = 21.0
    alpha = halflife_to_alpha(halflife)
    lambda_ = halflife_to_lambda(halflife)

    assert alpha_to_halflife(alpha) == pytest.approx(halflife)
    assert lambda_to_halflife(lambda_) == pytest.approx(halflife)


def test_ewma_vol_validates_parameterization() -> None:
    returns = pd.Series([0.01, -0.02, 0.015, -0.01, 0.012])

    with pytest.raises(ValueError):
        ewma_vol(returns=returns, halflife=10.0, lambda_=0.94)


def test_blend_and_alignment_helpers_preserve_common_index() -> None:
    left = pd.Series([0.10, 0.20, 0.30], index=pd.date_range("2024-01-01", periods=3, freq="D"))
    right = pd.Series([0.40, 0.50, 0.60], index=pd.date_range("2024-01-02", periods=3, freq="D"))

    aligned_left, aligned_right = align_series(left, right)
    geomean = geometric_blend_vol([left, right])
    arithmetic = arithmetic_blend_vol([left, right], weights=[1.0, 3.0])
    blended = weighted_blend([left, right], [2.0, 1.0])
    conservative = conservative_vol(left, right)
    ratio = vol_ratio(right, left)

    assert list(aligned_left.index) == list(aligned_right.index)
    assert len(geomean) == 2
    assert arithmetic.iloc[-1] == pytest.approx((0.30 * 1.0 + 0.50 * 3.0) / 4.0)
    assert blended.iloc[0] == pytest.approx((0.20 * 2.0 + 0.40) / 3.0)
    assert conservative.iloc[-1] == pytest.approx(0.50)
    assert ratio.iloc[-1] == pytest.approx(0.50 / 0.30)


def test_dual_window_and_annualization_helpers_behave_consistently() -> None:
    returns = pd.Series(
        [0.001 * ((idx % 7) - 3) for idx in range(90)],
        index=pd.date_range("2024-01-01", periods=90, freq="D"),
    )

    dual = dual_window_geometric_vol(returns=returns, short_window=21, long_window=63)
    annualized = annualize_vol(0.02)
    deannualized = deannualize_vol(annualized)

    assert (last_valid_scalar(dual) or 0.0) > 0
    assert deannualized == pytest.approx(0.02)
