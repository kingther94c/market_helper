from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BrokerAccountSnapshot:
    as_of: str
    account_id: str
    net_liquidation: float
    available_funds: float
    currency: str = "USD"


@dataclass(frozen=True)
class BrokerPositionSnapshot:
    as_of: str
    account_id: str
    contract_id: str
    quantity: float
    avg_cost: float | None = None
    market_value: float | None = None


@dataclass(frozen=True)
class BrokerQuoteSnapshot:
    as_of: str
    contract_id: str
    last: float
    bid: float | None = None
    ask: float | None = None
