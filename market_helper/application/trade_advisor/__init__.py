"""Application-layer orchestration for the trade_advisor umbrella.

Runs registered advisors over one shared :class:`AdvisorContext` and aggregates
their suggestions into a cross-advisor inbox. Keeps filesystem / dashboard
concerns out of the domain engines (mirrors ``application/portfolio_monitor``).
"""

from .option_scan import load_option_scan, save_option_scan
from .portfolio import context_from_positions_csv, currency_exposure_from_positions_csv
from .regime_seed import RegimeSeed, current_regime_seed
from .service import (
    TradeAdvisorRun,
    TradeAdvisorService,
    default_decision_journal,
    write_decision_snapshot,
)

__all__ = [
    "TradeAdvisorService",
    "TradeAdvisorRun",
    "default_decision_journal",
    "write_decision_snapshot",
    "context_from_positions_csv",
    "currency_exposure_from_positions_csv",
    "RegimeSeed",
    "current_regime_seed",
    "load_option_scan",
    "save_option_scan",
]
