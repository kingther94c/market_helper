from __future__ import annotations

import math
from dataclasses import dataclass

from market_helper.regimes.models import RegimeSnapshot


@dataclass(frozen=True)
class RegimeBacktestResult:
    total_return: float
    annualized_vol: float
    sharpe_like: float
    max_drawdown: float
    turnover: float


def evaluate_regime_policy(
    *,
    regimes: list[RegimeSnapshot],
    asset_returns: dict[str, dict[str, float]],
    policy_targets: dict[str, dict[str, float]],
) -> RegimeBacktestResult:
    """Minimal read/analyze scaffold for regime-conditioned target evaluation."""
    if not regimes:
        return RegimeBacktestResult(0.0, 0.0, 0.0, 0.0, 0.0)

    daily: list[float] = []
    turnover = 0.0
    previous_weights: dict[str, float] | None = None

    for snapshot in regimes:
        weights = policy_targets.get(snapshot.regime, {})
        day_ret = 0.0
        for bucket, weight in weights.items():
            series = asset_returns.get(bucket, {})
            day_ret += weight * float(series.get(snapshot.as_of, 0.0))
        daily.append(day_ret)

        if previous_weights is not None:
            keys = set(previous_weights) | set(weights)
            turnover += 0.5 * sum(abs(weights.get(k, 0.0) - previous_weights.get(k, 0.0)) for k in keys)
        previous_weights = dict(weights)

    equity = 1.0
    peak = 1.0
    max_drawdown = 0.0
    for value in daily:
        equity *= 1.0 + value
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, (peak - equity) / peak if peak > 0 else 0.0)

    mean = sum(daily) / len(daily)
    variance = sum((x - mean) ** 2 for x in daily) / len(daily)
    annualized_vol = math.sqrt(variance) * math.sqrt(252)
    sharpe_like = (mean * 252 / annualized_vol) if annualized_vol > 0 else 0.0

    return RegimeBacktestResult(
        total_return=equity - 1.0,
        annualized_vol=annualized_vol,
        sharpe_like=sharpe_like,
        max_drawdown=max_drawdown,
        turnover=turnover,
    )
