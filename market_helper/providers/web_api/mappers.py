from __future__ import annotations

from collections.abc import Mapping

from market_helper.domain import AccountSnapshot, PositionSnapshot, QuoteSnapshot
from market_helper.utils import utc_now_iso


def map_account_summary(payload: Mapping[str, object], *, as_of: str | None = None) -> AccountSnapshot:
    timestamp = as_of or utc_now_iso()
    return AccountSnapshot(
        as_of=timestamp,
        account_id=str(_first(payload, "accountId", "account", default="")),
        net_liquidation=_to_float(_first(payload, "netLiquidation", "net_liquidation", default=0.0)),
        available_funds=_to_float(_first(payload, "availableFunds", "available_funds", default=0.0)),
        currency=str(_first(payload, "currency", default="USD")),
    )


def map_position(payload: Mapping[str, object], *, as_of: str | None = None) -> PositionSnapshot:
    timestamp = as_of or utc_now_iso()
    contract_id = str(_first(payload, "contractId", "conid", "conId", default=""))
    account_id = str(_first(payload, "accountId", "account", default=""))
    return PositionSnapshot(
        as_of=timestamp,
        account_id=account_id,
        contract_id=f"IBKR:{contract_id}" if not contract_id.startswith("IBKR:") else contract_id,
        quantity=_to_float(_first(payload, "position", "quantity", default=0.0)),
        avg_cost=_to_optional_float(_first(payload, "avgCost", "averageCost", default=None)),
        market_value=_to_optional_float(_first(payload, "marketValue", "market_value", default=None)),
    )


def map_quote_snapshot(payload: Mapping[str, object], *, as_of: str | None = None) -> QuoteSnapshot:
    timestamp = as_of or utc_now_iso()
    contract_id = str(_first(payload, "contractId", "conid", "conId", default=""))
    return QuoteSnapshot(
        as_of=timestamp,
        contract_id=f"IBKR:{contract_id}" if not contract_id.startswith("IBKR:") else contract_id,
        last=_to_float(_first(payload, "last", "31", default=0.0)),
        bid=_to_optional_float(_first(payload, "bid", "84", default=None)),
        ask=_to_optional_float(_first(payload, "ask", "86", default=None)),
    )


def _first(payload: Mapping[str, object], *keys: str, default: object) -> object:
    for key in keys:
        if key in payload and payload[key] is not None:
            return payload[key]
    return default


def _to_float(value: object) -> float:
    if value in (None, ""):
        return 0.0
    return float(value)


def _to_optional_float(value: object) -> float | None:
    if value in (None, ""):
        return None
    return float(value)
