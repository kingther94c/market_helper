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
    raw_positions: Iterable[Mapping[str, object]],
    reference_table: SecurityReferenceTable,
    *,
    as_of: Optional[str] = None,
) -> List[PositionSnapshot]:
    normalized: List[PositionSnapshot] = []
    timestamp = as_of or now_utc_iso()

    for item in raw_positions:
        contract = IbkrContract(
            con_id=str(item["con_id"]),
            sec_type=str(item.get("sec_type", "")),
            symbol=str(item.get("symbol", "")),
            currency=str(item.get("currency", "")),
            exchange=str(item.get("exchange", "")),
            local_symbol=str(item.get("local_symbol", "")),
            multiplier=str(item.get("multiplier", "1")),
        )

        internal_id = reference_table.resolve_internal_id(IBKR_SOURCE, contract.con_id)
        if internal_id is None:
            internal_id = register_ibkr_contract(reference_table, contract)

        normalized.append(
            PositionSnapshot(
                as_of=timestamp,
                account=str(item.get("account", "")),
                internal_id=internal_id,
                source=IBKR_SOURCE,
                quantity=float(item.get("position", 0.0)),
                avg_cost=_optional_float(item.get("avg_cost")),
                market_value=_optional_float(item.get("market_value")),
            )
        )

    return normalized


def normalize_ibkr_latest_prices(
    raw_prices: Iterable[Mapping[str, object]],
    reference_table: SecurityReferenceTable,
    *,
    as_of: Optional[str] = None,
) -> List[PriceSnapshot]:
    normalized: List[PriceSnapshot] = []
    timestamp = as_of or now_utc_iso()

    for item in raw_prices:
        con_id = str(item["con_id"])
        internal_id = reference_table.require_internal_id(source=IBKR_SOURCE, external_id=con_id)

        last_price = _optional_float(item.get("last"))
        if last_price is None:
            last_price = _optional_float(item.get("close"))
        if last_price is None:
            last_price = _optional_float(item.get("market_price"))
        if last_price is None:
            raise ValueError("No usable price fields for IBKR con_id={con_id}".format(con_id=con_id))

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
