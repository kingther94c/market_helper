from __future__ import annotations

import math
from statistics import mean, pstdev

from .models import FactorSnapshot


def rolling_mean(values: list[float], window: int) -> list[float]:
    """Compute rolling mean with expanding prefix behavior."""
    if window <= 0:
        raise ValueError("window must be positive")
    out: list[float] = []
    for idx in range(len(values)):
        left = max(0, idx - window + 1)
        segment = values[left : idx + 1]
        out.append(sum(segment) / len(segment))
    return out


def rolling_std(values: list[float], window: int) -> list[float]:
    """Compute rolling population std with expanding prefix behavior."""
    if window <= 0:
        raise ValueError("window must be positive")
    out: list[float] = []
    for idx in range(len(values)):
        left = max(0, idx - window + 1)
        segment = values[left : idx + 1]
        out.append(pstdev(segment) if len(segment) > 1 else 0.0)
    return out


def ema(values: list[float], span: int) -> list[float]:
    """Exponential moving average."""
    if span <= 0:
        raise ValueError("span must be positive")
    if not values:
        return []
    alpha = 2.0 / (span + 1.0)
    out = [values[0]]
    for value in values[1:]:
        out.append((alpha * value) + ((1.0 - alpha) * out[-1]))
    return out


def rolling_zscore(values: list[float], window: int) -> list[float]:
    """Rolling z-score using rolling mean/std."""
    means = rolling_mean(values, window)
    stds = rolling_std(values, window)
    out: list[float] = []
    for value, m, s in zip(values, means, stds, strict=True):
        if s == 0:
            out.append(0.0)
        else:
            out.append((value - m) / s)
    return out


def rolling_percentile(values: list[float], window: int) -> list[float]:
    """Rolling percentile rank of the current point in trailing window [0, 1]."""
    if window <= 0:
        raise ValueError("window must be positive")
    out: list[float] = []
    for idx, value in enumerate(values):
        left = max(0, idx - window + 1)
        segment = values[left : idx + 1]
        below = sum(1 for point in segment if point <= value)
        out.append(below / len(segment))
    return out


def cumulative_return(returns: list[float], lookback: int) -> list[float]:
    """Trailing cumulative return over a lookback window."""
    if lookback <= 0:
        raise ValueError("lookback must be positive")
    out: list[float] = []
    for idx in range(len(returns)):
        left = max(0, idx - lookback + 1)
        acc = 1.0
        for value in returns[left : idx + 1]:
            acc *= 1.0 + value
        out.append(acc - 1.0)
    return out


def _normalize01(zvalue: float) -> float:
    """Squash z-score into a bounded [0, 1] interval."""
    return max(0.0, min(1.0, 0.5 + 0.2 * zvalue))


def compute_factor_snapshots(
    *,
    dates: list[str],
    vix: list[float],
    move: list[float],
    hy_oas: list[float],
    y2: list[float],
    y10: list[float],
    eq_returns: list[float],
    fi_returns: list[float],
    stress_weight_vol: float = 0.55,
    stress_weight_credit: float = 0.45,
) -> list[FactorSnapshot]:
    """Build v1 factor snapshots from normalized public-data-friendly inputs."""
    lengths = {len(dates), len(vix), len(move), len(hy_oas), len(y2), len(y10), len(eq_returns), len(fi_returns)}
    if len(lengths) != 1:
        raise ValueError("all input series must share the same length")

    vix_norm = [_normalize01(v) for v in rolling_zscore(vix, 60)]
    move_norm = [_normalize01(v) for v in rolling_zscore(move, 60)]
    vol = [(a + b) / 2.0 for a, b in zip(vix_norm, move_norm, strict=True)]

    spread_change = [0.0]
    spread_change.extend(hy_oas[idx] - hy_oas[idx - 1] for idx in range(1, len(hy_oas)))
    oas_level_norm = [_normalize01(v) for v in rolling_zscore(hy_oas, 90)]
    oas_change_norm = [_normalize01(v) for v in rolling_zscore(spread_change, 30)]
    credit = [0.7 * level + 0.3 * change for level, change in zip(oas_level_norm, oas_change_norm, strict=True)]

    d2 = [0.0]
    d10 = [0.0]
    d2.extend(y2[idx] - y2[idx - 5] if idx >= 5 else y2[idx] - y2[0] for idx in range(1, len(y2)))
    d10.extend(y10[idx] - y10[idx - 5] if idx >= 5 else y10[idx] - y10[0] for idx in range(1, len(y10)))
    rates = [max(-1.0, min(1.0, mean([a, b]) * 10.0)) for a, b in zip(d2, d10, strict=True)]

    curve_slope = [a - b for a, b in zip(y10, y2, strict=True)]
    slope_norm = [max(-1.0, min(1.0, x * 4.0)) for x in rolling_mean(curve_slope, 10)]
    credit_relief = [1.0 - (2.0 * c - 1.0) for c in credit]
    eq_momo = cumulative_return(eq_returns, 20)
    fi_momo = cumulative_return(fi_returns, 20)
    risk_appetite = [max(-1.0, min(1.0, (eq - fi) * 5.0)) for eq, fi in zip(eq_momo, fi_momo, strict=True)]
    growth = [
        max(-1.0, min(1.0, 0.5 * ra + 0.3 * cr + 0.2 * sl))
        for ra, cr, sl in zip(risk_appetite, credit_relief, slope_norm, strict=True)
    ]

    eq_20 = cumulative_return(eq_returns, 20)
    eq_60 = cumulative_return(eq_returns, 60)
    fi_20 = cumulative_return(fi_returns, 20)
    fi_60 = cumulative_return(fi_returns, 60)
    trend = []
    for a, b, c, d in zip(eq_20, eq_60, fi_20, fi_60, strict=True):
        score = 0.0
        score += 0.5 if a > 0 else -0.5
        score += 0.5 if b > 0 else -0.5
        score += 0.25 if c > 0 else -0.25
        score += 0.25 if d > 0 else -0.25
        trend.append(max(-1.0, min(1.0, score)))

    stress = [
        max(0.0, min(1.0, stress_weight_vol * v + stress_weight_credit * c))
        for v, c in zip(vol, credit, strict=True)
    ]

    return [
        FactorSnapshot(
            as_of=dates[idx],
            vol=vol[idx],
            credit=credit[idx],
            rates=rates[idx],
            growth=growth[idx],
            trend=trend[idx],
            stress=stress[idx],
            inputs={
                "vix": vix[idx],
                "move": move[idx],
                "hy_oas": hy_oas[idx],
                "y2": y2[idx],
                "y10": y10[idx],
            },
        )
        for idx in range(len(dates))
    ]
