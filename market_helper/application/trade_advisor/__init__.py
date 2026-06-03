"""Application-layer orchestration for the trade_advisor umbrella.

Runs registered advisors over one shared :class:`AdvisorContext` and aggregates
their suggestions into a cross-advisor inbox. Keeps filesystem / dashboard
concerns out of the domain engines (mirrors ``application/portfolio_monitor``).
"""

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
]
