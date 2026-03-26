from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class AccountSnapshot:
    as_of: str
    account_id: str
    net_liquidation: float
    available_funds: float
    currency: str = "USD"


@dataclass(frozen=True)
class Contract:
    internal_id: str
    symbol: str
    sec_type: str
    exchange: str
    currency: str
    multiplier: float = 1.0


@dataclass(frozen=True)
class PositionSnapshot:
    as_of: str
    account_id: str
    contract_id: str
    quantity: float
    avg_cost: float | None = None
    market_value: float | None = None


@dataclass(frozen=True)
class QuoteSnapshot:
    as_of: str
    contract_id: str
    last: float
    bid: float | None = None
    ask: float | None = None


@dataclass(frozen=True)
class AllocationRow:
    contract_id: str
    weight: float
    market_value: float


@dataclass(frozen=True)
class RiskRow:
    contract_id: str
    exposure: float
    concentration: float


@dataclass(frozen=True)
class MonitorView:
    generated_at: str
    account: AccountSnapshot
    positions: list[PositionSnapshot] = field(default_factory=list)
    allocations: list[AllocationRow] = field(default_factory=list)
    risks: list[RiskRow] = field(default_factory=list)
