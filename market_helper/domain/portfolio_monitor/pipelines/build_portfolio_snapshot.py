from __future__ import annotations

import json
from pathlib import Path

from market_helper.common.models import PortfolioPositionView, PortfolioSnapshot
from market_helper.common.models.security_reference import (
    PortfolioPositionSnapshot,
    PortfolioPriceSnapshot,
)
from market_helper.presentation.tables.portfolio_report import build_position_report_rows


def build_portfolio_snapshot(
    *,
    positions_path: str | Path,
    prices_path: str | Path,
) -> PortfolioSnapshot:
    positions = _load_positions(positions_path)
    prices = _load_prices(prices_path)
    rows = build_position_report_rows(positions, {item.internal_id: item.last_price for item in prices})

    account_id = rows[0].account if rows else ""
    as_of_date = rows[0].as_of if rows else ""
    positions_view = [
        PortfolioPositionView(
            internal_id=row.internal_id,
            quantity=row.quantity,
            market_value=row.market_value,
            weight=row.weight,
        )
        for row in rows
    ]
    market_values = {
        row.internal_id: row.market_value
        for row in rows
        if row.market_value is not None
    }
    pnl = {
        row.internal_id: row.unrealized_pnl
        for row in rows
        if row.unrealized_pnl is not None
    }
    allocation_views = {
        row.internal_id: row.weight
        for row in rows
        if row.weight is not None
    }
    return PortfolioSnapshot(
        account_id=account_id,
        as_of_date=as_of_date,
        positions=positions_view,
        market_values=market_values,
        pnl=pnl,
        allocation_views=allocation_views,
    )


def _load_positions(path: str | Path) -> list[PortfolioPositionSnapshot]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return [
        PortfolioPositionSnapshot(
            as_of=str(row["as_of"]),
            account=str(row["account"]),
            internal_id=str(row["internal_id"]),
            source=str(row["source"]),
            quantity=float(row["quantity"]),
            avg_cost=_optional_float(row.get("avg_cost")),
            market_value=_optional_float(row.get("market_value")),
        )
        for row in payload
    ]


def _load_prices(path: str | Path) -> list[PortfolioPriceSnapshot]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return [
        PortfolioPriceSnapshot(
            as_of=str(row["as_of"]),
            internal_id=str(row["internal_id"]),
            source=str(row["source"]),
            last_price=float(row["last_price"]),
        )
        for row in payload
    ]


def _optional_float(value: object) -> float | None:
    if value in (None, ""):
        return None
    return float(value)


__all__ = ["build_portfolio_snapshot"]
