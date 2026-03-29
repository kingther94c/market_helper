from __future__ import annotations

from market_helper.domain.integration.services.regime_portfolio_mapper import map_portfolio_to_regime


def generate_combined_report(*, portfolio_snapshot, regime_snapshot):
    return map_portfolio_to_regime(portfolio_snapshot, regime_snapshot)


__all__ = ["generate_combined_report"]
