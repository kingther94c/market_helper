from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, Iterable, List, Mapping, Optional, Tuple


SourceKey = Tuple[str, str]


@dataclass(frozen=True)
class SecurityReference:
    """Canonical instrument record used across broker and market-data sources."""

    internal_id: str
    asset_class: str
    symbol: str
    currency: str
    exchange: str
    description: str = ""
    multiplier: float = 1.0
    metadata: Dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class SecurityMapping:
    """One-to-one mapping from external source identifier to canonical instrument."""

    source: str
    external_id: str
    internal_id: str


@dataclass(frozen=True)
class PositionSnapshot:
    """Normalized position row (suitable for later risk calculations)."""

    as_of: str
    account: str
    internal_id: str
    source: str
    quantity: float
    avg_cost: Optional[float]
    market_value: Optional[float]


@dataclass(frozen=True)
class PriceSnapshot:
    """Normalized latest price row."""

    as_of: str
    internal_id: str
    source: str
    last_price: float


class SecurityReferenceTable:
    """In-memory reference table with cross-source id resolution."""

    def __init__(self) -> None:
        self._security_by_id: Dict[str, SecurityReference] = {}
        self._mapping_to_internal: Dict[SourceKey, str] = {}

    def upsert_security(self, security: SecurityReference) -> None:
        self._security_by_id[security.internal_id] = security

    def upsert_mapping(self, mapping: SecurityMapping) -> None:
        if mapping.internal_id not in self._security_by_id:
            raise KeyError(
                "Mapping references unknown internal_id: {value}".format(
                    value=mapping.internal_id
                )
            )
        self._mapping_to_internal[(mapping.source, mapping.external_id)] = mapping.internal_id

    def add_security_with_mappings(
        self,
        security: SecurityReference,
        mappings: Iterable[SecurityMapping],
    ) -> None:
        self.upsert_security(security)
        for mapping in mappings:
            if mapping.internal_id != security.internal_id:
                raise ValueError(
                    "Mapping internal_id {mapping_id} does not match security {security_id}".format(
                        mapping_id=mapping.internal_id,
                        security_id=security.internal_id,
                    )
                )
            self.upsert_mapping(mapping)

    def resolve_internal_id(self, source: str, external_id: str) -> Optional[str]:
        return self._mapping_to_internal.get((source, external_id))

    def require_internal_id(self, source: str, external_id: str) -> str:
        internal_id = self.resolve_internal_id(source=source, external_id=external_id)
        if internal_id is None:
            raise KeyError(
                "No mapping for source={source}, external_id={external_id}".format(
                    source=source,
                    external_id=external_id,
                )
            )
        return internal_id

    def get_security(self, internal_id: str) -> Optional[SecurityReference]:
        return self._security_by_id.get(internal_id)

    def to_rows(self) -> List[Dict[str, str]]:
        rows: List[Dict[str, str]] = []
        for (source, external_id), internal_id in sorted(self._mapping_to_internal.items()):
            security = self._security_by_id[internal_id]
            rows.append(
                {
                    "internal_id": security.internal_id,
                    "asset_class": security.asset_class,
                    "symbol": security.symbol,
                    "currency": security.currency,
                    "exchange": security.exchange,
                    "source": source,
                    "external_id": external_id,
                }
            )
        return rows


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def build_price_lookup(prices: Iterable[PriceSnapshot]) -> Dict[str, float]:
    return {item.internal_id: item.last_price for item in prices}


def join_positions_with_latest_price(
    positions: Iterable[PositionSnapshot],
    prices: Mapping[str, float],
) -> List[Dict[str, object]]:
    rows: List[Dict[str, object]] = []
    for position in positions:
        rows.append(
            {
                "as_of": position.as_of,
                "account": position.account,
                "internal_id": position.internal_id,
                "quantity": position.quantity,
                "avg_cost": position.avg_cost,
                "market_value": position.market_value,
                "latest_price": prices.get(position.internal_id),
            }
        )
    return rows
