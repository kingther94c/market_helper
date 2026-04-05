from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from .volatility import historical_vol, rolling_vol, vol_ratio


def proxy_regime_scaled_vol(
    asset_reference_vol: float | pd.Series,
    proxy_current_level: float | pd.Series,
    proxy_reference_level: float | pd.Series,
    floor_at_zero: bool = True,
) -> float | pd.Series:
    _validate_non_negative(asset_reference_vol, name="asset_reference_vol")
    _validate_non_negative(proxy_current_level, name="proxy_current_level")
    _validate_positive(proxy_reference_level, name="proxy_reference_level")
    scaled = _binary_operator(
        asset_reference_vol,
        _binary_operator(proxy_current_level, proxy_reference_level, lambda left, right: left / right),
        lambda left, right: left * right,
    )
    if floor_at_zero:
        return _clip_lower(scaled, floor=0.0)
    return scaled


def relative_vol_multiplier(
    asset_long_term_vol: float,
    anchor_long_term_vol: float,
) -> float:
    _validate_non_negative(asset_long_term_vol, name="asset_long_term_vol")
    _validate_positive(anchor_long_term_vol, name="anchor_long_term_vol")
    return float(asset_long_term_vol) / float(anchor_long_term_vol)


def scaled_forward_vol_from_anchor(
    anchor_forward_vol: float | pd.Series,
    asset_long_term_vol: float,
    anchor_long_term_vol: float,
) -> float | pd.Series:
    multiplier = relative_vol_multiplier(asset_long_term_vol, anchor_long_term_vol)
    return _binary_operator(anchor_forward_vol, multiplier, lambda left, right: left * right)


def vol_multiplier(
    asset_returns: pd.Series,
    benchmark_returns: pd.Series,
    window: int | None = None,
    annualization_factor: float = 252,
    ddof: int = 1,
    min_periods: int | None = None,
) -> float | pd.Series:
    if window is None:
        numerator = historical_vol(returns=asset_returns, annualization_factor=annualization_factor, ddof=ddof)
        denominator = historical_vol(returns=benchmark_returns, annualization_factor=annualization_factor, ddof=ddof)
        if denominator <= 0:
            return 0.0
        return numerator / denominator
    numerator_series = rolling_vol(
        returns=asset_returns,
        window=window,
        annualization_factor=annualization_factor,
        ddof=ddof,
        min_periods=min_periods,
    )
    denominator_series = rolling_vol(
        returns=benchmark_returns,
        window=window,
        annualization_factor=annualization_factor,
        ddof=ddof,
        min_periods=min_periods,
    )
    return vol_ratio(numerator_series, denominator_series, clip_inf=True)


def _binary_operator(
    left: float | pd.Series,
    right: float | pd.Series,
    operator: Any,
) -> float | pd.Series:
    if isinstance(left, pd.Series) and isinstance(right, pd.Series):
        aligned_left, aligned_right = left.align(right, join="inner")
        return pd.Series(operator(aligned_left.astype(float), aligned_right.astype(float)), index=aligned_left.index, dtype=float)
    if isinstance(left, pd.Series):
        return pd.Series(operator(left.astype(float), float(right)), index=left.index, dtype=float)
    if isinstance(right, pd.Series):
        return pd.Series(operator(float(left), right.astype(float)), index=right.index, dtype=float)
    return float(operator(float(left), float(right)))


def _clip_lower(value: float | pd.Series, *, floor: float) -> float | pd.Series:
    if isinstance(value, pd.Series):
        return pd.Series(value.clip(lower=floor), index=value.index, dtype=float)
    return max(float(value), floor)


def _validate_positive(value: float | pd.Series, *, name: str) -> None:
    if isinstance(value, pd.Series):
        numeric = pd.to_numeric(value, errors="coerce").dropna()
        if (numeric <= 0).any():
            raise ValueError(f"{name} must be positive")
        return
    if float(value) <= 0:
        raise ValueError(f"{name} must be positive")


def _validate_non_negative(value: float | pd.Series, *, name: str) -> None:
    if isinstance(value, pd.Series):
        numeric = pd.to_numeric(value, errors="coerce").dropna()
        if (numeric < 0).any():
            raise ValueError(f"{name} must be non-negative")
        return
    if float(value) < 0:
        raise ValueError(f"{name} must be non-negative")


__all__ = [
    "proxy_regime_scaled_vol",
    "relative_vol_multiplier",
    "scaled_forward_vol_from_anchor",
    "vol_multiplier",
]
