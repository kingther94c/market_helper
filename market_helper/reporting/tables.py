from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping, Optional

from market_helper.portfolio import PositionSnapshot, SecurityReference


@dataclass(frozen=True)
class PositionReportRow:
    as_of: str
    account: str
    internal_id: str
    con_id: Optional[str]
    symbol: str
    local_symbol: str
    exchange: str
    currency: str
    source: str
    quantity: float
    avg_cost: Optional[float]
    latest_price: Optional[float]
    market_value: Optional[float]
    cost_basis: Optional[float]
    unrealized_pnl: Optional[float]
    weight: Optional[float]


def build_position_report_rows(
    positions: Iterable[PositionSnapshot],
    prices: Mapping[str, float],
    security_lookup: Mapping[str, SecurityReference] | None = None,
) -> list[PositionReportRow]:
    materialized_positions = list(positions)
    metadata_lookup = security_lookup or {}
    effective_market_values = [
        _effective_market_value(position=position, latest_price=prices.get(position.internal_id))
        for position in materialized_positions
    ]
    total_market_value = sum(value for value in effective_market_values if value is not None)

    rows: list[PositionReportRow] = []
    for position, effective_market_value in zip(materialized_positions, effective_market_values):
        latest_price = prices.get(position.internal_id)
        security = metadata_lookup.get(position.internal_id)
        cost_basis = _cost_basis(position)
        unrealized_pnl = (
            effective_market_value - cost_basis
            if effective_market_value is not None and cost_basis is not None
            else None
        )
        weight = (
            effective_market_value / total_market_value
            if effective_market_value is not None and total_market_value > 0
            else None
        )
        rows.append(
            PositionReportRow(
                as_of=position.as_of,
                account=position.account,
                internal_id=position.internal_id,
                con_id=_con_id(security),
                symbol=security.symbol if security is not None else "",
                local_symbol=security.description if security is not None else "",
                exchange=security.exchange if security is not None else "",
                currency=security.currency if security is not None else "",
                source=position.source,
                quantity=position.quantity,
                avg_cost=position.avg_cost,
                latest_price=latest_price,
                market_value=effective_market_value,
                cost_basis=cost_basis,
                unrealized_pnl=unrealized_pnl,
                weight=weight,
            )
        )

    return rows


def _con_id(security: Optional[SecurityReference]) -> Optional[str]:
    if security is None:
        return None
    return security.metadata.get("ibkr_con_id") or security.ibkr_conid or None


def _effective_market_value(
    *,
    position: PositionSnapshot,
    latest_price: Optional[float],
) -> Optional[float]:
    if position.market_value is not None:
        return position.market_value
    if latest_price is None:
        return None
    return position.quantity * latest_price


def _cost_basis(position: PositionSnapshot) -> Optional[float]:
    if position.avg_cost is None:
        return None
    return position.quantity * position.avg_cost
