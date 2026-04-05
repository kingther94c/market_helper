from __future__ import annotations

import pandas as pd

from .vol_proxies import proxy_regime_scaled_vol


def yield_vol_to_price_vol(
    yield_vol: float | pd.Series,
    modified_duration: float | pd.Series,
    convexity: float | pd.Series | None = None,
    yield_shock_scale: float = 1.0,
) -> float | pd.Series:
    _validate_non_negative(yield_vol, name="yield_vol")
    _validate_non_negative(modified_duration, name="modified_duration")
    if convexity is not None:
        _validate_non_negative(convexity, name="convexity")
    if yield_shock_scale < 0:
        raise ValueError("yield_shock_scale must be non-negative")
    scaled_yield_vol = _binary_operator(yield_vol, yield_shock_scale, lambda left, right: left * right)
    return _binary_operator(modified_duration, scaled_yield_vol, lambda left, right: left * right)


def proxy_index_to_yield_vol(
    proxy_level: float | pd.Series,
    mapping_factor: float,
) -> float | pd.Series:
    _validate_non_negative(proxy_level, name="proxy_level")
    if mapping_factor < 0:
        raise ValueError("mapping_factor must be non-negative")
    return _binary_operator(proxy_level, mapping_factor, lambda left, right: left * right)


def rates_forward_vol_from_proxy(
    proxy_level: float | pd.Series,
    proxy_reference_level: float | pd.Series,
    asset_reference_price_vol: float | pd.Series | None = None,
    asset_reference_yield_vol: float | pd.Series | None = None,
    modified_duration: float | pd.Series | None = None,
    mode: str = "regime_scaled_price_vol",
) -> float | pd.Series:
    normalized_mode = str(mode).strip().lower()
    if normalized_mode == "regime_scaled_price_vol":
        if asset_reference_price_vol is None:
            raise ValueError("asset_reference_price_vol is required for regime_scaled_price_vol mode")
        return proxy_regime_scaled_vol(
            asset_reference_vol=asset_reference_price_vol,
            proxy_current_level=proxy_level,
            proxy_reference_level=proxy_reference_level,
            floor_at_zero=True,
        )
    if normalized_mode == "duration_times_yield_vol":
        if asset_reference_yield_vol is None:
            raise ValueError("asset_reference_yield_vol is required for duration_times_yield_vol mode")
        if modified_duration is None:
            raise ValueError("modified_duration is required for duration_times_yield_vol mode")
        scaled_yield_vol = proxy_regime_scaled_vol(
            asset_reference_vol=asset_reference_yield_vol,
            proxy_current_level=proxy_level,
            proxy_reference_level=proxy_reference_level,
            floor_at_zero=True,
        )
        return yield_vol_to_price_vol(
            yield_vol=scaled_yield_vol,
            modified_duration=modified_duration,
        )
    raise ValueError("mode must be 'regime_scaled_price_vol' or 'duration_times_yield_vol'")


def _binary_operator(
    left: float | pd.Series,
    right: float | pd.Series,
    operator,
) -> float | pd.Series:
    if isinstance(left, pd.Series) and isinstance(right, pd.Series):
        aligned_left, aligned_right = left.align(right, join="inner")
        return pd.Series(operator(aligned_left.astype(float), aligned_right.astype(float)), index=aligned_left.index, dtype=float)
    if isinstance(left, pd.Series):
        return pd.Series(operator(left.astype(float), float(right)), index=left.index, dtype=float)
    if isinstance(right, pd.Series):
        return pd.Series(operator(float(left), right.astype(float)), index=right.index, dtype=float)
    return float(operator(float(left), float(right)))


def _validate_non_negative(value: float | pd.Series, *, name: str) -> None:
    if isinstance(value, pd.Series):
        numeric = pd.to_numeric(value, errors="coerce").dropna()
        if (numeric < 0).any():
            raise ValueError(f"{name} must be non-negative")
        return
    if float(value) < 0:
        raise ValueError(f"{name} must be non-negative")


__all__ = [
    "proxy_index_to_yield_vol",
    "rates_forward_vol_from_proxy",
    "yield_vol_to_price_vol",
]
