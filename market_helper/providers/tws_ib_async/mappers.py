from __future__ import annotations

from typing import Iterable


def portfolio_items_to_ibkr_position_rows(items: Iterable[object]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []

    for item in items:
        contract = _require_attr(item, "contract")
        exchange = _first_non_empty_attr(contract, "primaryExchange", "exchange")

        rows.append(
            {
                "account": _string_attr(item, "account"),
                "conId": _require_attr(contract, "conId"),
                "secType": _string_attr(contract, "secType"),
                "symbol": _string_attr(contract, "symbol"),
                "currency": _string_attr(contract, "currency"),
                "exchange": exchange,
                "localSymbol": _string_attr(contract, "localSymbol"),
                "multiplier": _string_attr(contract, "multiplier", default="1"),
                "position": getattr(item, "position", 0.0),
                "avgCost": getattr(item, "averageCost", None),
                "marketValue": getattr(item, "marketValue", None),
            }
        )

    return rows


def portfolio_items_to_ibkr_price_rows(items: Iterable[object]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []

    for item in items:
        contract = _require_attr(item, "contract")
        market_price = _derive_market_price(item)
        if market_price is None:
            continue

        rows.append(
            {
                "conId": _require_attr(contract, "conId"),
                "marketPrice": market_price,
            }
        )

    return rows


def _derive_market_price(item: object) -> float | None:
    market_price = _optional_float(getattr(item, "marketPrice", None))
    if market_price is not None:
        return market_price

    quantity = _optional_float(getattr(item, "position", None))
    market_value = _optional_float(getattr(item, "marketValue", None))
    if quantity in (None, 0.0) or market_value is None:
        return None
    return market_value / quantity


def _require_attr(value: object, name: str) -> object:
    item = getattr(value, name, None)
    if item in (None, ""):
        raise ValueError("Missing required TWS portfolio field: {name}".format(name=name))
    return item


def _string_attr(value: object, name: str, *, default: str = "") -> str:
    item = getattr(value, name, default)
    if item in (None, ""):
        return default
    return str(item)


def _first_non_empty_attr(value: object, *names: str) -> str:
    for name in names:
        item = getattr(value, name, "")
        if item not in (None, ""):
            return str(item)
    return ""


def _optional_float(value: object) -> float | None:
    if value in (None, ""):
        return None
    return float(value)
