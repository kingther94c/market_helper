from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping, Optional

from market_helper.portfolio import PositionSnapshot


@dataclass(frozen=True)
class PositionReportRow:
    as_of: str
    account: str
    internal_id: str
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
) -> list[PositionReportRow]:
    materialized_positions = list(positions)
    effective_market_values = [
        _effective_market_value(position=position, latest_price=prices.get(position.internal_id))
        for position in materialized_positions
    ]
    total_market_value = sum(value for value in effective_market_values if value is not None)

    rows: list[PositionReportRow] = []
    for position, effective_market_value in zip(materialized_positions, effective_market_values):
        latest_price = prices.get(position.internal_id)
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
