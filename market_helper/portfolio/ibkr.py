from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Iterable, List, Mapping, Optional

from .security_reference import (
    PriceSnapshot,
    PositionSnapshot,
    RUNTIME_OUTSIDE_SCOPE_PREFIX,
    SecurityMapping,
    SecurityReference,
    SecurityReferenceTable,
    build_internal_security_id,
    now_utc_iso,
)

IBKR_SOURCE = "ibkr"


@dataclass(frozen=True)
class IbkrContract:
    con_id: str
    sec_type: str
    symbol: str
    currency: str
    exchange: str
    local_symbol: str = ""
    multiplier: str = "1"


def contract_to_internal_id(contract: IbkrContract) -> str:
    return build_internal_security_id(
        ibkr_sec_type=contract.sec_type,
        canonical_symbol=contract.symbol,
        primary_exchange=contract.exchange,
    )


def contract_to_security_reference(
    contract: IbkrContract,
    *,
    status: str = "unmapped",
) -> SecurityReference:
    try:
        multiplier = float(contract.multiplier)
    except (TypeError, ValueError):
        multiplier = 1.0

    internal_id = contract_to_internal_id(contract)
    if status == "outside_scope":
        internal_id = f"{RUNTIME_OUTSIDE_SCOPE_PREFIX}{internal_id}"
    return SecurityReference(
        internal_id=internal_id,
        symbol=contract.symbol.upper(),
        currency=contract.currency.upper(),
        exchange=contract.exchange.upper(),
        description=contract.local_symbol,
        multiplier=multiplier,
        metadata={
            "ibkr_con_id": contract.con_id,
            "local_symbol": contract.local_symbol,
            "runtime_sec_type": contract.sec_type.upper(),
        },
        canonical_symbol=contract.symbol.upper(),
        display_ticker=contract.symbol.upper(),
        display_name=contract.local_symbol or contract.symbol.upper(),
        primary_exchange=contract.exchange.upper(),
        ibkr_sec_type=contract.sec_type.upper(),
        ibkr_symbol=contract.symbol.upper(),
        ibkr_exchange=contract.exchange.upper(),
        ibkr_conid=contract.con_id,
        report_category="OUTSIDE_SCOPE" if status == "outside_scope" else "",
        mapping_status_hint=status,
    )


def enrich_security_from_contract_details(
    security: SecurityReference,
    details: Mapping[str, object],
) -> SecurityReference:
    if security.mapping_status != "unmapped":
        return security

    primary_exchange = str(
        _first_non_null(details, "primaryExchange", "exchange", default=security.primary_exchange)
    ).upper()
    symbol = str(_first_non_null(details, "symbol", default=security.symbol)).upper()
    currency = str(_first_non_null(details, "currency", default=security.currency)).upper()
    local_symbol = str(_first_non_null(details, "localSymbol", default=security.description))
    long_name = str(
        _first_non_null(
            details,
            "longName",
            "marketName",
            "localSymbol",
            "symbol",
            default=security.display_name,
        )
    )
    multiplier = _optional_float(_first_non_null(details, "multiplier", default=security.multiplier))
    metadata = dict(security.metadata)
    market_name = str(_first_non_null(details, "marketName", default=""))
    if market_name:
        metadata["market_name"] = market_name
    if long_name:
        metadata["long_name"] = long_name

    return replace(
        security,
        symbol=symbol or security.symbol,
        currency=currency or security.currency,
        exchange=primary_exchange or security.exchange,
        description=local_symbol or security.description,
        multiplier=multiplier if multiplier is not None else security.multiplier,
        metadata=metadata,
        canonical_symbol=symbol or security.canonical_symbol,
        display_ticker=symbol or security.display_ticker,
        display_name=long_name or security.display_name,
        primary_exchange=primary_exchange or security.primary_exchange,
        ibkr_symbol=symbol or security.ibkr_symbol,
        ibkr_exchange=primary_exchange or security.ibkr_exchange,
        ibkr_conid=str(_first_non_null(details, "conId", default=security.ibkr_conid)),
    )


def register_ibkr_contract(
    reference_table: SecurityReferenceTable,
    contract: IbkrContract,
) -> str:
    security = resolve_ibkr_contract(reference_table, contract)
    if not contract.con_id:
        if security.mapping_status != "mapped":
            reference_table.upsert_security(security)
        return security.internal_id
    if security.mapping_status == "mapped":
        return reference_table.register_runtime_contract(
            security=security,
            con_id=contract.con_id,
            symbol=contract.symbol,
            exchange=contract.exchange,
            local_symbol=contract.local_symbol,
            sec_type=contract.sec_type,
        )

    reference_table.upsert_security(security)
    reference_table.upsert_mapping(
        SecurityMapping(
            source=IBKR_SOURCE,
            external_id=contract.con_id,
            internal_id=security.internal_id,
        )
    )
    return security.internal_id


def resolve_ibkr_contract(
    reference_table: SecurityReferenceTable,
    contract: IbkrContract,
) -> SecurityReference:
    existing = reference_table.resolve_by_ibkr_conid(contract.con_id)
    if existing is not None:
        return existing

    existing_internal_id = reference_table.resolve_internal_id(IBKR_SOURCE, contract.con_id)
    if existing_internal_id is not None:
        existing = reference_table.get_security(existing_internal_id)
        if existing is not None:
            return existing

    alias_match = reference_table.resolve_by_ibkr_alias(
        symbol=contract.symbol,
        sec_type=contract.sec_type,
        exchange=contract.exchange,
    )
    if alias_match is not None:
        return alias_match

    symbol_matches = reference_table.search_by_ibkr_symbol_sec_type(
        symbol=contract.symbol,
        sec_type=contract.sec_type,
    )
    if len(symbol_matches) == 1:
        return symbol_matches[0]

    if contract.sec_type.upper() == "CASH":
        cash_match = reference_table.resolve_cash_reference(
            symbol=contract.symbol,
            currency=contract.currency,
        )
        if cash_match is not None:
            return cash_match

    if contract.sec_type.upper() == "OPT":
        return contract_to_security_reference(contract, status="outside_scope")

    return contract_to_security_reference(contract, status="unmapped")


def normalize_ibkr_positions(
    raw_positions: Iterable[Mapping[str, object] | object],
    reference_table: SecurityReferenceTable,
    *,
    as_of: Optional[str] = None,
) -> List[PositionSnapshot]:
    normalized: List[PositionSnapshot] = []
    timestamp = as_of or now_utc_iso()

    for item in raw_positions:
        row = _as_ibkr_dict(item)
        sec_type = str(_first_non_null(row, "sec_type", "secType", default="")).upper()
        con_id = _first_non_null(row, "con_id", "conid", "conId", default=None)
        if con_id in (None, "") and sec_type != "CASH":
            raise KeyError(
                "Missing required IBKR field. Expected one of: con_id, conid, conId"
            )
        contract = IbkrContract(
            con_id=str(con_id or ""),
            sec_type=sec_type,
            symbol=str(_first_non_null(row, "symbol", default="")).upper(),
            currency=str(_first_non_null(row, "currency", default="")).upper(),
            exchange=str(_first_non_null(row, "primary_exchange", "primaryExchange", "exchange", default="")).upper(),
            local_symbol=str(
                _first_non_null(row, "local_symbol", "localSymbol", default="")
            ),
            multiplier=str(_first_non_null(row, "multiplier", default="1")),
        )

        internal_id = (
            reference_table.resolve_internal_id(IBKR_SOURCE, contract.con_id)
            if contract.con_id
            else None
        )
        if internal_id is None:
            internal_id = register_ibkr_contract(reference_table, contract)

        normalized.append(
            PositionSnapshot(
                as_of=timestamp,
                account=str(_first_non_null(row, "account", "accountId", default="")),
                internal_id=internal_id,
                source=IBKR_SOURCE,
                quantity=float(_first_non_null(row, "position", default=0.0)),
                avg_cost=_optional_float(
                    _first_non_null(row, "avg_cost", "avgCost", "averageCost", default=None)
                ),
                market_value=_optional_float(
                    _first_non_null(row, "market_value", "marketValue", default=None)
                ),
            )
        )

    return normalized


def normalize_ibkr_latest_prices(
    raw_prices: Iterable[Mapping[str, object] | object],
    reference_table: SecurityReferenceTable,
    *,
    as_of: Optional[str] = None,
) -> List[PriceSnapshot]:
    normalized: List[PriceSnapshot] = []
    timestamp = as_of or now_utc_iso()

    for item in raw_prices:
        row = _as_ibkr_dict(item)
        con_id = str(_require_any(row, "con_id", "conid", "conId"))
        internal_id = reference_table.require_internal_id(
            source=IBKR_SOURCE,
            external_id=con_id,
        )

        last_price = _optional_float(_first_non_null(row, "last", "31", default=None))
        if last_price is None:
            last_price = _optional_float(_first_non_null(row, "close", default=None))
        if last_price is None:
            last_price = _optional_float(
                _first_non_null(row, "market_price", "marketPrice", default=None)
            )
        if last_price is None:
            raise ValueError(
                "No usable price fields for IBKR con_id={con_id}".format(con_id=con_id)
            )

        normalized.append(
            PriceSnapshot(
                as_of=timestamp,
                internal_id=internal_id,
                source=IBKR_SOURCE,
                last_price=last_price,
            )
        )

    return normalized


def _optional_float(value: object) -> Optional[float]:
    if value in (None, ""):
        return None
    return float(value)


def _as_ibkr_dict(value: Mapping[str, object] | object) -> Mapping[str, object]:
    if isinstance(value, Mapping):
        return value
    if hasattr(value, "__dict__"):
        return {key: item for key, item in vars(value).items() if not key.startswith("_")}
    raise TypeError("IBKR payload must be mapping-like or expose __dict__")


def _first_non_null(
    payload: Mapping[str, object],
    *keys: str,
    default: object,
) -> object:
    for key in keys:
        if key in payload and payload[key] is not None:
            return payload[key]
    return default


def _require_any(payload: Mapping[str, object], *keys: str) -> object:
    value = _first_non_null(payload, *keys, default=None)
    if value is None:
        raise KeyError(
            "Missing required IBKR field. Expected one of: {keys}".format(
                keys=", ".join(keys)
            )
        )
    return value
