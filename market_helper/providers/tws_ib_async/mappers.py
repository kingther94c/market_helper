from __future__ import annotations

from collections import defaultdict
from typing import Iterable

_CASH_BALANCE_TAG_PRIORITY = {
    "TOTALCASHBALANCE": 0,
    "CASHBALANCE": 1,
}
_CASH_TARGET_CURRENCY = "SGD"


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


def account_values_to_ibkr_cash_position_rows(values: Iterable[object]) -> list[dict[str, object]]:
    selected: dict[tuple[str, str], tuple[int, str, float]] = {}
    exchange_rates: dict[tuple[str, str], float] = {}

    for item in values:
        account = _string_or_key(item, "account")
        tag = _string_or_key(item, "tag").upper()
        currency = _string_or_key(item, "currency").upper()
        raw_value = _value_or_key(item, "value")

        if tag == "EXCHANGERATE":
            rate = _optional_float(raw_value)
            if currency not in {"", "BASE"} and rate not in (None, 0.0):
                exchange_rates[(account, currency)] = rate
            continue

        if tag not in _CASH_BALANCE_TAG_PRIORITY:
            continue
        amount = _optional_float(raw_value)
        if currency in {"", "BASE"} or amount in (None, 0.0):
            continue

        key = (account, currency)
        candidate = (_CASH_BALANCE_TAG_PRIORITY[tag], tag, amount)
        existing = selected.get(key)
        if existing is None or candidate[0] < existing[0]:
            selected[key] = candidate

    rows: list[dict[str, object]] = []
    balances_by_account: dict[str, dict[str, tuple[str, float]]] = defaultdict(dict)
    for (account, currency), (_, tag, amount) in selected.items():
        balances_by_account[account][currency] = (tag, amount)

    for account in sorted(balances_by_account):
        balances = balances_by_account[account]
        converted_amount = _convert_cash_balances(
            {currency: amount for currency, (_, amount) in balances.items()},
            {currency: rate for (acct, currency), rate in exchange_rates.items() if acct == account},
            target_currency=_CASH_TARGET_CURRENCY,
        )
        if converted_amount is None:
            continue

        source_currencies = ",".join(sorted(balances))
        rows.append(
            {
                "account": account,
                "secType": "CASH",
                "symbol": _CASH_TARGET_CURRENCY,
                "currency": _CASH_TARGET_CURRENCY,
                "exchange": "IDEALPRO",
                "localSymbol": f"{_CASH_TARGET_CURRENCY} Cash",
                "multiplier": "1",
                "position": converted_amount,
                "avgCost": 1.0,
                "marketValue": converted_amount,
                "cashTag": "TOTALCASHBALANCE_CONVERTED_TO_SGD",
                "cashTargetCurrency": _CASH_TARGET_CURRENCY,
                "cashSourceCurrencies": source_currencies,
                "cashConversionMode": _cash_conversion_mode(
                    currencies=tuple(sorted(balances)),
                    target_currency=_CASH_TARGET_CURRENCY,
                ),
            }
        )

    return rows


def _convert_cash_balances(
    balances: dict[str, float],
    exchange_rates: dict[str, float],
    *,
    target_currency: str,
) -> float | None:
    target = target_currency.upper()
    target_rate = exchange_rates.get(target, 1.0 if target in balances else None)
    if target_rate in (None, 0.0):
        return None

    total = 0.0
    for currency, amount in balances.items():
        if currency == target:
            total += amount
            continue
        rate = exchange_rates.get(currency)
        if rate in (None, 0.0):
            return None
        total += amount * rate / target_rate
    return total


def _cash_conversion_mode(
    *,
    currencies: tuple[str, ...],
    target_currency: str,
) -> str:
    if len(currencies) > 1:
        return "multi_currency_to_sgd"
    if currencies and currencies[0] == target_currency.upper():
        return "already_sgd"
    return "single_currency_to_sgd"


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


def _value_or_key(value: object, name: str) -> object:
    if isinstance(value, dict):
        return value.get(name, None)
    return getattr(value, name, None)


def _string_or_key(value: object, name: str, *, default: str = "") -> str:
    item = _value_or_key(value, name)
    if item in (None, ""):
        return default
    return str(item)


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
