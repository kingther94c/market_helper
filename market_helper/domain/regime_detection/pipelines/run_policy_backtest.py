from __future__ import annotations

from market_helper.domain.regime_detection.services.policy_backtester import evaluate_regime_policy


def run_policy_backtest(
    *,
    regimes,
    asset_returns,
    policy_targets,
):
    return evaluate_regime_policy(
        regimes=regimes,
        asset_returns=asset_returns,
        policy_targets=policy_targets,
    )


__all__ = ["run_policy_backtest"]
