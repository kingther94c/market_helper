from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from typing import Any

import numpy as np
import pandas as pd


DEFAULT_ANNUALIZATION_FACTOR = 252.0
DEFAULT_EWMA_LAMBDA = 0.94


def compute_returns(
    prices: pd.Series | Sequence[float],
    method: str = "log",
    dropna: bool = True,
) -> pd.Series:
    """Convert a price series into log or simple returns."""
    series = _coerce_series(prices, name="prices")
    normalized_method = _normalize_return_method(method)
    if normalized_method == "log" and (series.dropna() <= 0).any():
        raise ValueError("Log returns require strictly positive prices")
    if normalized_method == "log":
        returns = np.log(series / series.shift(1))
    else:
        returns = series.pct_change()
    returns = pd.Series(returns, index=series.index, dtype=float)
    return returns.dropna() if dropna else returns


def historical_vol(
    *,
    returns: pd.Series | Sequence[float] | None = None,
    prices: pd.Series | Sequence[float] | None = None,
    return_method: str = "log",
    annualization_factor: float = DEFAULT_ANNUALIZATION_FACTOR,
    ddof: int = 1,
) -> float:
    resolved = _resolve_returns(returns=returns, prices=prices, return_method=return_method)
    return _annualized_std(resolved, annualization_factor=annualization_factor, ddof=ddof)


def rolling_vol(
    *,
    returns: pd.Series | Sequence[float] | None = None,
    prices: pd.Series | Sequence[float] | None = None,
    window: int = 21,
    return_method: str = "log",
    annualization_factor: float = DEFAULT_ANNUALIZATION_FACTOR,
    ddof: int = 1,
    min_periods: int | None = None,
) -> pd.Series:
    _validate_positive_int(window, name="window")
    resolved = _resolve_returns(returns=returns, prices=prices, return_method=return_method)
    periods = window if min_periods is None else min_periods
    _validate_positive_int(periods, name="min_periods")
    rolling = resolved.rolling(window=window, min_periods=periods).std(ddof=ddof)
    return annualize_vol(rolling, annualization_factor=annualization_factor)


def trailing_vol(
    *,
    returns: pd.Series | Sequence[float] | None = None,
    prices: pd.Series | Sequence[float] | None = None,
    window: int = 252,
    return_method: str = "log",
    annualization_factor: float = DEFAULT_ANNUALIZATION_FACTOR,
    ddof: int = 1,
) -> float:
    series = rolling_vol(
        returns=returns,
        prices=prices,
        window=window,
        return_method=return_method,
        annualization_factor=annualization_factor,
        ddof=ddof,
        min_periods=window,
    )
    return last_valid_scalar(series) or 0.0


def expanding_vol(
    *,
    returns: pd.Series | Sequence[float] | None = None,
    prices: pd.Series | Sequence[float] | None = None,
    return_method: str = "log",
    annualization_factor: float = DEFAULT_ANNUALIZATION_FACTOR,
    ddof: int = 1,
    min_periods: int = 60,
) -> pd.Series:
    _validate_positive_int(min_periods, name="min_periods")
    resolved = _resolve_returns(returns=returns, prices=prices, return_method=return_method)
    expanding = resolved.expanding(min_periods=min_periods).std(ddof=ddof)
    return annualize_vol(expanding, annualization_factor=annualization_factor)


def long_term_vol(
    *,
    returns: pd.Series | Sequence[float] | None = None,
    prices: pd.Series | Sequence[float] | None = None,
    lookback: int = 252 * 5,
    return_method: str = "log",
    annualization_factor: float = DEFAULT_ANNUALIZATION_FACTOR,
    ddof: int = 1,
) -> float:
    _validate_positive_int(lookback, name="lookback")
    resolved = _resolve_returns(returns=returns, prices=prices, return_method=return_method)
    return _annualized_std(resolved.iloc[-lookback:], annualization_factor=annualization_factor, ddof=ddof)


def halflife_to_alpha(halflife: float) -> float:
    halflife_value = _validate_positive_float(halflife, name="halflife")
    return 1.0 - math.exp(-math.log(2.0) / halflife_value)


def alpha_to_halflife(alpha: float) -> float:
    alpha_value = _validate_unit_interval(alpha, name="alpha")
    return math.log(0.5) / math.log(1.0 - alpha_value)


def halflife_to_lambda(halflife: float) -> float:
    halflife_value = _validate_positive_float(halflife, name="halflife")
    return math.exp(-math.log(2.0) / halflife_value)


def lambda_to_halflife(lambda_: float) -> float:
    lambda_value = _validate_decay(lambda_, name="lambda_")
    return math.log(0.5) / math.log(lambda_value)


def ewma_vol(
    *,
    returns: pd.Series | Sequence[float] | None = None,
    prices: pd.Series | Sequence[float] | None = None,
    return_method: str = "log",
    annualization_factor: float = DEFAULT_ANNUALIZATION_FACTOR,
    halflife: float | None = None,
    lambda_: float | None = None,
    alpha: float | None = None,
    min_periods: int = 20,
    demean: bool = False,
) -> pd.Series:
    _validate_positive_int(min_periods, name="min_periods")
    resolved = _resolve_returns(returns=returns, prices=prices, return_method=return_method)
    smoothing_alpha = _resolve_ewma_alpha(halflife=halflife, lambda_=lambda_, alpha=alpha)
    centered = resolved
    if demean:
        ew_mean = resolved.ewm(alpha=smoothing_alpha, adjust=False, min_periods=min_periods).mean()
        centered = resolved - ew_mean
    variance = centered.pow(2).ewm(alpha=smoothing_alpha, adjust=False, min_periods=min_periods).mean()
    return annualize_vol(variance.pow(0.5), annualization_factor=annualization_factor)


def geometric_blend_vol(
    vol_series_list: Sequence[pd.Series | Sequence[float]],
    weights: Sequence[float] | None = None,
) -> pd.Series:
    if not vol_series_list:
        raise ValueError("vol_series_list must not be empty")
    aligned = align_series(*vol_series_list, join="inner")
    if not aligned:
        return pd.Series(dtype=float)
    frame = pd.concat(aligned, axis=1)
    if (frame < 0).any().any():
        raise ValueError("Volatility inputs must be non-negative")
    resolved_weights = _resolve_weights(len(aligned), weights)
    values = np.ones(len(frame), dtype=float)
    for idx, weight in enumerate(resolved_weights):
        values *= np.power(frame.iloc[:, idx].to_numpy(dtype=float), weight)
    blended = np.power(values, 1.0 / sum(resolved_weights))
    return pd.Series(blended, index=frame.index, dtype=float)


def arithmetic_blend_vol(
    vol_series_list: Sequence[pd.Series | Sequence[float]],
    weights: Sequence[float] | None = None,
) -> pd.Series:
    if not vol_series_list:
        raise ValueError("vol_series_list must not be empty")
    aligned = align_series(*vol_series_list, join="inner")
    if not aligned:
        return pd.Series(dtype=float)
    frame = pd.concat(aligned, axis=1)
    resolved_weights = np.asarray(_resolve_weights(len(aligned), weights), dtype=float)
    weighted = frame.mul(resolved_weights, axis=1).sum(axis=1) / resolved_weights.sum()
    return pd.Series(weighted, index=frame.index, dtype=float)


def dual_window_geometric_vol(
    *,
    returns: pd.Series | Sequence[float] | None = None,
    prices: pd.Series | Sequence[float] | None = None,
    short_window: int = 21,
    long_window: int = 63,
    return_method: str = "log",
    annualization_factor: float = DEFAULT_ANNUALIZATION_FACTOR,
    ddof: int = 1,
) -> pd.Series:
    short_vol = rolling_vol(
        returns=returns,
        prices=prices,
        window=short_window,
        return_method=return_method,
        annualization_factor=annualization_factor,
        ddof=ddof,
    )
    long_vol = rolling_vol(
        returns=returns,
        prices=prices,
        window=long_window,
        return_method=return_method,
        annualization_factor=annualization_factor,
        ddof=ddof,
    )
    return geometric_blend_vol([short_vol, long_vol])


def vol_ratio(
    numerator_vol: float | pd.Series,
    denominator_vol: float | pd.Series,
    clip_inf: bool = True,
) -> float | pd.Series:
    return _binary_numeric_result(
        numerator_vol,
        denominator_vol,
        lambda left, right: left / right,
        clip_inf=clip_inf,
    )


def blend_vol(
    realized_vol: float | pd.Series,
    forward_vol: float | pd.Series,
    weight_realized: float = 0.5,
) -> float | pd.Series:
    return weighted_blend([realized_vol, forward_vol], [weight_realized, 1.0 - weight_realized])


def weighted_blend(
    values: Sequence[float | pd.Series],
    weights: Sequence[float],
) -> float | pd.Series:
    if not values:
        raise ValueError("values must not be empty")
    resolved_weights = _resolve_weights(len(values), weights)
    if any(isinstance(value, pd.Series) for value in values):
        index = _common_index_for_series([value for value in values if isinstance(value, pd.Series)])
        if index is None:
            return pd.Series(dtype=float)
        series_values = [_broadcast_to_index(value, index) for value in values]
        frame = pd.concat(series_values, axis=1)
        weighted = frame.mul(np.asarray(resolved_weights, dtype=float), axis=1).sum(axis=1) / sum(resolved_weights)
        return pd.Series(weighted, index=index, dtype=float)
    return float(sum(float(value) * weight for value, weight in zip(values, resolved_weights)) / sum(resolved_weights))


def conservative_vol(*vols: float | pd.Series) -> float | pd.Series:
    if not vols:
        raise ValueError("At least one volatility input is required")
    if any(isinstance(vol, pd.Series) for vol in vols):
        index = _common_index_for_series([vol for vol in vols if isinstance(vol, pd.Series)])
        if index is None:
            return pd.Series(dtype=float)
        frame = pd.concat([_broadcast_to_index(vol, index) for vol in vols], axis=1)
        return pd.Series(frame.max(axis=1), index=index, dtype=float)
    return max(float(vol) for vol in vols)


def annualize_vol(
    period_vol: float | pd.Series,
    annualization_factor: float = DEFAULT_ANNUALIZATION_FACTOR,
) -> float | pd.Series:
    factor = math.sqrt(_validate_positive_float(annualization_factor, name="annualization_factor"))
    if isinstance(period_vol, pd.Series):
        return pd.Series(period_vol.astype(float) * factor, index=period_vol.index, dtype=float)
    return float(period_vol) * factor


def deannualize_vol(
    annualized_vol: float | pd.Series,
    annualization_factor: float = DEFAULT_ANNUALIZATION_FACTOR,
) -> float | pd.Series:
    factor = math.sqrt(_validate_positive_float(annualization_factor, name="annualization_factor"))
    if isinstance(annualized_vol, pd.Series):
        return pd.Series(annualized_vol.astype(float) / factor, index=annualized_vol.index, dtype=float)
    return float(annualized_vol) / factor


def align_series(*series: pd.Series | Sequence[float], join: str = "inner") -> list[pd.Series]:
    if not series:
        return []
    normalized = [_coerce_series(value, name=f"series_{idx}") for idx, value in enumerate(series)]
    frame = pd.concat(normalized, axis=1, join=join)
    return [pd.Series(frame.iloc[:, idx], index=frame.index, dtype=float) for idx in range(frame.shape[1])]


def last_valid_scalar(series: pd.Series | Sequence[float]) -> float | None:
    normalized = _coerce_series(series, name="series")
    valid = normalized.dropna()
    if valid.empty:
        return None
    return float(valid.iloc[-1])


def _resolve_returns(
    *,
    returns: pd.Series | Sequence[float] | None,
    prices: pd.Series | Sequence[float] | None,
    return_method: str,
) -> pd.Series:
    if (returns is None) == (prices is None):
        raise ValueError("Exactly one of returns or prices must be provided")
    if returns is not None:
        return _coerce_series(returns, name="returns").dropna()
    return compute_returns(prices, method=return_method, dropna=True)


def _normalize_return_method(method: str) -> str:
    normalized = str(method).strip().lower()
    if normalized not in {"log", "simple"}:
        raise ValueError("return_method must be 'log' or 'simple'")
    return normalized


def _resolve_ewma_alpha(
    *,
    halflife: float | None,
    lambda_: float | None,
    alpha: float | None,
) -> float:
    specified = [value is not None for value in (halflife, lambda_, alpha)]
    if sum(specified) > 1:
        raise ValueError("Specify only one of halflife, lambda_, or alpha")
    if halflife is not None:
        return halflife_to_alpha(halflife)
    if lambda_ is not None:
        return 1.0 - _validate_decay(lambda_, name="lambda_")
    if alpha is not None:
        return _validate_unit_interval(alpha, name="alpha")
    return 1.0 - DEFAULT_EWMA_LAMBDA


def _annualized_std(
    series: pd.Series,
    *,
    annualization_factor: float,
    ddof: int,
) -> float:
    _validate_positive_float(annualization_factor, name="annualization_factor")
    if ddof < 0:
        raise ValueError("ddof must be non-negative")
    valid = series.dropna()
    if len(valid) <= ddof:
        return 0.0
    std = float(valid.std(ddof=ddof))
    if math.isnan(std):
        return 0.0
    return float(annualize_vol(std, annualization_factor=annualization_factor))


def _coerce_series(values: pd.Series | Sequence[float], *, name: str) -> pd.Series:
    if isinstance(values, pd.Series):
        series = values.copy()
    elif isinstance(values, np.ndarray):
        series = pd.Series(values)
    elif isinstance(values, Iterable) and not isinstance(values, (str, bytes)):
        series = pd.Series(list(values))
    else:
        raise ValueError(f"{name} must be a pandas Series or a numeric sequence")
    return pd.to_numeric(series, errors="coerce")


def _resolve_weights(expected_length: int, weights: Sequence[float] | None) -> list[float]:
    if expected_length <= 0:
        raise ValueError("expected_length must be positive")
    if weights is None:
        return [1.0] * expected_length
    if len(weights) != expected_length:
        raise ValueError("weights must match the number of inputs")
    resolved = [float(weight) for weight in weights]
    if any(weight < 0 for weight in resolved):
        raise ValueError("weights must be non-negative")
    if sum(resolved) <= 0:
        raise ValueError("weights must sum to a positive value")
    return resolved


def _common_index_for_series(series_list: Sequence[pd.Series]) -> pd.Index | None:
    if not series_list:
        return None
    aligned = align_series(*series_list, join="inner")
    if not aligned:
        return None
    return aligned[0].index


def _broadcast_to_index(value: float | pd.Series, index: pd.Index) -> pd.Series:
    if isinstance(value, pd.Series):
        return _coerce_series(value, name="value").reindex(index)
    return pd.Series(float(value), index=index, dtype=float)


def _binary_numeric_result(
    left: float | pd.Series,
    right: float | pd.Series,
    operator: Any,
    *,
    clip_inf: bool,
) -> float | pd.Series:
    if isinstance(left, pd.Series) or isinstance(right, pd.Series):
        series_inputs = [value for value in (left, right) if isinstance(value, pd.Series)]
        index = _common_index_for_series(series_inputs)
        if index is None:
            return pd.Series(dtype=float)
        left_series = _broadcast_to_index(left, index)
        right_series = _broadcast_to_index(right, index)
        result = pd.Series(operator(left_series, right_series), index=index, dtype=float)
        if clip_inf:
            result = result.replace([np.inf, -np.inf], np.nan)
        return result
    try:
        result = float(operator(float(left), float(right)))
    except ZeroDivisionError:
        result = math.nan
    if clip_inf and not math.isfinite(result):
        return math.nan
    return result


def _validate_positive_float(value: float, *, name: str) -> float:
    parsed = float(value)
    if parsed <= 0:
        raise ValueError(f"{name} must be positive")
    return parsed


def _validate_positive_int(value: int, *, name: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise ValueError(f"{name} must be positive")
    return parsed


def _validate_unit_interval(value: float, *, name: str) -> float:
    parsed = float(value)
    if not 0 < parsed < 1:
        raise ValueError(f"{name} must be strictly between 0 and 1")
    return parsed


def _validate_decay(value: float, *, name: str) -> float:
    parsed = float(value)
    if not 0 < parsed < 1:
        raise ValueError(f"{name} must be strictly between 0 and 1")
    return parsed


__all__ = [
    "DEFAULT_ANNUALIZATION_FACTOR",
    "DEFAULT_EWMA_LAMBDA",
    "align_series",
    "alpha_to_halflife",
    "annualize_vol",
    "arithmetic_blend_vol",
    "blend_vol",
    "compute_returns",
    "conservative_vol",
    "deannualize_vol",
    "dual_window_geometric_vol",
    "ewma_vol",
    "expanding_vol",
    "geometric_blend_vol",
    "halflife_to_alpha",
    "halflife_to_lambda",
    "historical_vol",
    "lambda_to_halflife",
    "last_valid_scalar",
    "long_term_vol",
    "rolling_vol",
    "trailing_vol",
    "vol_ratio",
    "weighted_blend",
]
