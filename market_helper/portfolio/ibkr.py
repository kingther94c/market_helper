from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List, Mapping, Optional

from .security_reference import (
    PriceSnapshot,
    PositionSnapshot,
    SecurityMapping,
    SecurityReference,
    SecurityReferenceTable,
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
    return "IBKR:{con_id}".format(con_id=contract.con_id)


def contract_to_security_reference(contract: IbkrContract) -> SecurityReference:
    try:
        multiplier = float(contract.multiplier)
    except (TypeError, ValueError):
        multiplier = 1.0

    return SecurityReference(
        internal_id=contract_to_internal_id(contract),
        asset_class=contract.sec_type.lower(),
        symbol=contract.symbol,
        currency=contract.currency,
        exchange=contract.exchange,
        description=contract.local_symbol,
        multiplier=multiplier,
        metadata={"ibkr_con_id": contract.con_id},
    )


def register_ibkr_contract(
    reference_table: SecurityReferenceTable,
    contract: IbkrContract,
) -> str:
    security = contract_to_security_reference(contract)
    reference_table.upsert_security(security)
    reference_table.upsert_mapping(
        SecurityMapping(
            source=IBKR_SOURCE,
            external_id=contract.con_id,
            internal_id=security.internal_id,
        )
    )
    return security.internal_id


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
        contract = IbkrContract(
            con_id=str(_require_any(row, "con_id", "conId")),
            sec_type=str(_first_non_null(row, "sec_type", "secType", default="")),
            symbol=str(_first_non_null(row, "symbol", default="")),
            currency=str(_first_non_null(row, "currency", default="")),
            exchange=str(_first_non_null(row, "exchange", default="")),
            local_symbol=str(
                _first_non_null(row, "local_symbol", "localSymbol", default="")
            ),
            multiplier=str(_first_non_null(row, "multiplier", default="1")),
        )

        internal_id = reference_table.resolve_internal_id(IBKR_SOURCE, contract.con_id)
        if internal_id is None:
            internal_id = register_ibkr_contract(reference_table, contract)

        normalized.append(
            PositionSnapshot(
                as_of=timestamp,
                account=str(_first_non_null(row, "account", default="")),
                internal_id=internal_id,
                source=IBKR_SOURCE,
                quantity=float(_first_non_null(row, "position", default=0.0)),
                avg_cost=_optional_float(
                    _first_non_null(row, "avg_cost", "averageCost", default=None)
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
        con_id = str(_require_any(row, "con_id", "conId"))
        internal_id = reference_table.require_internal_id(
            source=IBKR_SOURCE,
            external_id=con_id,
        )

        last_price = _optional_float(_first_non_null(row, "last", default=None))
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
