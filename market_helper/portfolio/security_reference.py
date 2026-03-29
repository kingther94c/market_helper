from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Optional, Tuple


SourceKey = Tuple[str, str]
IbkrAliasKey = Tuple[str, str, str]

ALLOWED_CURATED_UNIVERSE_TYPES = {"ETF", "EQ", "FX_FUT", "FI_FUT", "OTHER_FUT", "CASH"}
ALLOWED_CURATED_RISK_BUCKETS = {"EQ", "FI", "GOLD", "CM", "CASH", "MACRO"}
CURATED_SECURITY_REFERENCE_HEADERS = [
    "internal_id",
    "is_active",
    "universe_type",
    "canonical_symbol",
    "display_ticker",
    "display_name",
    "currency",
    "primary_exchange",
    "multiplier",
    "ibkr_sec_type",
    "ibkr_symbol",
    "ibkr_exchange",
    "ibkr_conid",
    "google_symbol",
    "yahoo_symbol",
    "bbg_symbol",
    "report_category",
    "risk_bucket",
    "mod_duration",
    "default_expected_vol",
    "price_source_provider",
    "price_source_symbol",
    "fx_source_provider",
    "fx_source_symbol",
]
MONTH_CODES = "FGHJKMNQUVXZ"
DEFAULT_SECURITY_REFERENCE_PATH = (
    Path(__file__).resolve().parents[2] / "configs" / "portfolio_monitor" / "security_reference.csv"
)
RUNTIME_UNMAPPED_PREFIX = "UNMAPPED:"
RUNTIME_OUTSIDE_SCOPE_PREFIX = "OUTSIDE_SCOPE:"


@dataclass(frozen=True)
class SecurityReference:
    """Canonical instrument record with curated universe + report/risk metadata."""

    internal_id: str
    asset_class: str = ""
    symbol: str = ""
    currency: str = ""
    exchange: str = ""
    description: str = ""
    multiplier: float = 1.0
    metadata: Dict[str, str] = field(default_factory=dict)
    is_active: bool = True
    universe_type: str = ""
    canonical_symbol: str = ""
    display_ticker: str = ""
    display_name: str = ""
    primary_exchange: str = ""
    ibkr_sec_type: str = ""
    ibkr_symbol: str = ""
    ibkr_exchange: str = ""
    ibkr_conid: str = ""
    google_symbol: str = ""
    yahoo_symbol: str = ""
    bbg_symbol: str = ""
    report_category: str = ""
    risk_bucket: str = ""
    mod_duration: float | None = None
    default_expected_vol: float | None = None
    price_source_provider: str = ""
    price_source_symbol: str = ""
    fx_source_provider: str = ""
    fx_source_symbol: str = ""

    def __post_init__(self) -> None:
        metadata = {str(k): str(v) for k, v in (self.metadata or {}).items()}
        ibkr_conid = _clean_optional_str(self.ibkr_conid) or metadata.get("ibkr_con_id", "")
        normalized_risk_bucket = _normalize_risk_bucket(self.risk_bucket or self.asset_class)
        normalized_universe_type = _normalize_universe_type(self.universe_type)
        canonical_symbol = (
            _clean_optional_str(self.canonical_symbol)
            or _clean_optional_str(self.symbol)
            or _clean_optional_str(self.ibkr_symbol)
        )
        primary_exchange = (
            _clean_optional_str(self.primary_exchange)
            or _clean_optional_str(self.exchange)
            or _clean_optional_str(self.ibkr_exchange)
        )
        symbol = _clean_optional_str(self.symbol) or canonical_symbol
        exchange = _clean_optional_str(self.exchange) or primary_exchange
        display_ticker = _clean_optional_str(self.display_ticker) or symbol
        display_name = _clean_optional_str(self.display_name) or _clean_optional_str(self.description) or display_ticker
        description = _clean_optional_str(self.description) or metadata.get("local_symbol", "") or display_name
        ibkr_symbol = _clean_optional_str(self.ibkr_symbol) or symbol
        ibkr_exchange = _clean_optional_str(self.ibkr_exchange) or primary_exchange
        ibkr_sec_type = _clean_optional_str(self.ibkr_sec_type).upper()
        object.__setattr__(self, "metadata", metadata)
        object.__setattr__(self, "ibkr_conid", ibkr_conid)
        object.__setattr__(self, "risk_bucket", normalized_risk_bucket)
        object.__setattr__(self, "asset_class", normalized_risk_bucket or _clean_optional_str(self.asset_class))
        object.__setattr__(self, "universe_type", normalized_universe_type)
        object.__setattr__(self, "canonical_symbol", canonical_symbol)
        object.__setattr__(self, "symbol", symbol)
        object.__setattr__(self, "primary_exchange", primary_exchange)
        object.__setattr__(self, "exchange", exchange)
        object.__setattr__(self, "display_ticker", display_ticker)
        object.__setattr__(self, "display_name", display_name)
        object.__setattr__(self, "description", description)
        object.__setattr__(self, "ibkr_symbol", ibkr_symbol)
        object.__setattr__(self, "ibkr_exchange", ibkr_exchange)
        object.__setattr__(self, "ibkr_sec_type", ibkr_sec_type)
        object.__setattr__(self, "google_symbol", _clean_optional_str(self.google_symbol))
        object.__setattr__(self, "yahoo_symbol", _clean_optional_str(self.yahoo_symbol))
        object.__setattr__(self, "bbg_symbol", _clean_optional_str(self.bbg_symbol))
        object.__setattr__(self, "report_category", _clean_optional_str(self.report_category))
        object.__setattr__(self, "price_source_provider", _clean_optional_str(self.price_source_provider))
        object.__setattr__(self, "price_source_symbol", _clean_optional_str(self.price_source_symbol))
        object.__setattr__(self, "fx_source_provider", _clean_optional_str(self.fx_source_provider))
        object.__setattr__(self, "fx_source_symbol", _clean_optional_str(self.fx_source_symbol))
        object.__setattr__(self, "currency", _clean_optional_str(self.currency).upper())

    @property
    def mapping_status(self) -> str:
        if self.internal_id.startswith(RUNTIME_OUTSIDE_SCOPE_PREFIX):
            return "outside_scope"
        if self.internal_id.startswith(RUNTIME_UNMAPPED_PREFIX):
            return "unmapped"
        return "mapped"

    @property
    def runtime_local_symbol(self) -> str:
        return self.metadata.get("local_symbol", "")

    def with_runtime_contract(
        self,
        *,
        con_id: str,
        symbol: str,
        exchange: str,
        local_symbol: str,
        sec_type: str,
    ) -> SecurityReference:
        metadata = dict(self.metadata)
        metadata.update(
            {
                "ibkr_con_id": str(con_id),
                "local_symbol": str(local_symbol),
                "runtime_symbol": str(symbol).upper(),
                "runtime_exchange": str(exchange).upper(),
                "runtime_sec_type": str(sec_type).upper(),
            }
        )
        return replace(
            self,
            metadata=metadata,
            ibkr_conid=str(con_id),
            symbol=str(symbol).upper() or self.symbol,
            exchange=str(exchange).upper() or self.exchange,
            description=str(local_symbol) or self.description,
        )

    def validate_curated(self) -> None:
        if not self.internal_id:
            raise ValueError("security_reference row is missing internal_id")
        if self.universe_type not in ALLOWED_CURATED_UNIVERSE_TYPES:
            raise ValueError(
                "Invalid universe_type {value} for {internal_id}".format(
                    value=self.universe_type,
                    internal_id=self.internal_id,
                )
            )
        if self.risk_bucket not in ALLOWED_CURATED_RISK_BUCKETS:
            raise ValueError(
                "Invalid risk_bucket {value} for {internal_id}".format(
                    value=self.risk_bucket,
                    internal_id=self.internal_id,
                )
            )

    def to_curated_row(self) -> Dict[str, str]:
        self.validate_curated()
        return {
            "internal_id": self.internal_id,
            "is_active": "true" if self.is_active else "false",
            "universe_type": self.universe_type,
            "canonical_symbol": self.canonical_symbol,
            "display_ticker": self.display_ticker,
            "display_name": self.display_name,
            "currency": self.currency,
            "primary_exchange": self.primary_exchange,
            "multiplier": _stringify_float(self.multiplier),
            "ibkr_sec_type": self.ibkr_sec_type,
            "ibkr_symbol": self.ibkr_symbol,
            "ibkr_exchange": self.ibkr_exchange,
            "ibkr_conid": self.ibkr_conid,
            "google_symbol": self.google_symbol,
            "yahoo_symbol": self.yahoo_symbol,
            "bbg_symbol": self.bbg_symbol,
            "report_category": self.report_category,
            "risk_bucket": self.risk_bucket,
            "mod_duration": _stringify_optional_float(self.mod_duration),
            "default_expected_vol": _stringify_optional_float(self.default_expected_vol),
            "price_source_provider": self.price_source_provider,
            "price_source_symbol": self.price_source_symbol,
            "fx_source_provider": self.fx_source_provider,
            "fx_source_symbol": self.fx_source_symbol,
        }

    @classmethod
    def from_curated_row(cls, row: Mapping[str, object]) -> SecurityReference:
        security = cls(
            internal_id=str(row.get("internal_id") or ""),
            is_active=_parse_bool(row.get("is_active"), default=True),
            universe_type=str(row.get("universe_type") or ""),
            canonical_symbol=str(row.get("canonical_symbol") or ""),
            display_ticker=str(row.get("display_ticker") or ""),
            display_name=str(row.get("display_name") or ""),
            currency=str(row.get("currency") or ""),
            primary_exchange=str(row.get("primary_exchange") or ""),
            multiplier=_parse_float(row.get("multiplier"), default=1.0),
            ibkr_sec_type=str(row.get("ibkr_sec_type") or ""),
            ibkr_symbol=str(row.get("ibkr_symbol") or ""),
            ibkr_exchange=str(row.get("ibkr_exchange") or ""),
            ibkr_conid=str(row.get("ibkr_conid") or ""),
            google_symbol=str(row.get("google_symbol") or ""),
            yahoo_symbol=str(row.get("yahoo_symbol") or ""),
            bbg_symbol=str(row.get("bbg_symbol") or ""),
            report_category=str(row.get("report_category") or ""),
            risk_bucket=str(row.get("risk_bucket") or ""),
            mod_duration=_parse_optional_float(row.get("mod_duration")),
            default_expected_vol=_parse_optional_float(row.get("default_expected_vol")),
            price_source_provider=str(row.get("price_source_provider") or ""),
            price_source_symbol=str(row.get("price_source_symbol") or ""),
            fx_source_provider=str(row.get("fx_source_provider") or ""),
            fx_source_symbol=str(row.get("fx_source_symbol") or ""),
        )
        security.validate_curated()
        return security


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
    """Reference table with curated CSV loading + cross-source runtime resolution."""

    def __init__(self) -> None:
        self._security_by_id: Dict[str, SecurityReference] = {}
        self._mapping_to_internal: Dict[SourceKey, str] = {}
        self._by_ibkr_conid: Dict[str, str] = {}
        self._by_ibkr_alias: Dict[IbkrAliasKey, str] = {}
        self._by_google_symbol: Dict[str, str] = {}
        self._by_yahoo_symbol: Dict[str, str] = {}
        self._by_bbg_symbol: Dict[str, str] = {}
        self._by_cash_alias: Dict[str, str] = {}

    @classmethod
    def from_csv(cls, path: str | Path) -> SecurityReferenceTable:
        table = cls()
        with Path(path).open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            missing = [column for column in CURATED_SECURITY_REFERENCE_HEADERS if column not in (reader.fieldnames or [])]
            if missing:
                raise ValueError(
                    "security_reference CSV is missing required columns: {value}".format(
                        value=", ".join(missing)
                    )
                )
            for row in reader:
                if not any((value or "").strip() for value in row.values()):
                    continue
                table.upsert_security(SecurityReference.from_curated_row(row))
        return table

    @classmethod
    def from_default_csv(cls) -> SecurityReferenceTable:
        return cls.from_csv(DEFAULT_SECURITY_REFERENCE_PATH)

    @property
    def by_internal_id(self) -> Dict[str, SecurityReference]:
        return dict(self._security_by_id)

    @property
    def by_ibkr_conid(self) -> Dict[str, SecurityReference]:
        return {
            conid: self._security_by_id[internal_id]
            for conid, internal_id in self._by_ibkr_conid.items()
            if internal_id in self._security_by_id
        }

    @property
    def by_google_symbol(self) -> Dict[str, SecurityReference]:
        return {
            symbol: self._security_by_id[internal_id]
            for symbol, internal_id in self._by_google_symbol.items()
            if internal_id in self._security_by_id
        }

    @property
    def by_yahoo_symbol(self) -> Dict[str, SecurityReference]:
        return {
            symbol: self._security_by_id[internal_id]
            for symbol, internal_id in self._by_yahoo_symbol.items()
            if internal_id in self._security_by_id
        }

    @property
    def by_bbg_symbol(self) -> Dict[str, SecurityReference]:
        return {
            symbol: self._security_by_id[internal_id]
            for symbol, internal_id in self._by_bbg_symbol.items()
            if internal_id in self._security_by_id
        }

    def upsert_security(self, security: SecurityReference) -> None:
        self._security_by_id[security.internal_id] = security

        if security.ibkr_conid:
            self._by_ibkr_conid[security.ibkr_conid] = security.internal_id
            self._mapping_to_internal[("ibkr", security.ibkr_conid)] = security.internal_id

        if security.ibkr_symbol and security.ibkr_sec_type and security.ibkr_exchange:
            alias_key = self._normalize_ibkr_alias(
                symbol=security.ibkr_symbol,
                sec_type=security.ibkr_sec_type,
                exchange=security.ibkr_exchange,
            )
            self._by_ibkr_alias[alias_key] = security.internal_id

        if security.google_symbol:
            normalized = _normalize_lookup_value(security.google_symbol)
            self._by_google_symbol[normalized] = security.internal_id
            self._mapping_to_internal[("google", normalized)] = security.internal_id
            self._mapping_to_internal[("google_finance", normalized)] = security.internal_id

        if security.yahoo_symbol:
            normalized = _normalize_lookup_value(security.yahoo_symbol)
            self._by_yahoo_symbol[normalized] = security.internal_id
            self._mapping_to_internal[("yahoo", normalized)] = security.internal_id
            self._mapping_to_internal[("yahoo_finance", normalized)] = security.internal_id

        if security.bbg_symbol:
            normalized = _normalize_lookup_value(security.bbg_symbol)
            self._by_bbg_symbol[normalized] = security.internal_id
            self._mapping_to_internal[("bbg", normalized)] = security.internal_id
            self._mapping_to_internal[("bloomberg", normalized)] = security.internal_id

        if security.risk_bucket == "CASH" or security.universe_type == "CASH":
            aliases = {
                security.canonical_symbol,
                security.display_ticker,
                security.symbol,
            }
            if security.ibkr_sec_type == "CASH":
                aliases.add(security.currency)
            for alias in aliases:
                normalized = _normalize_lookup_value(alias)
                if normalized:
                    self._by_cash_alias[normalized] = security.internal_id

    def upsert_mapping(self, mapping: SecurityMapping) -> None:
        if mapping.internal_id not in self._security_by_id:
            raise KeyError(
                "Mapping references unknown internal_id: {value}".format(
                    value=mapping.internal_id
                )
            )
        self._mapping_to_internal[
            (_normalize_source(mapping.source), _normalize_lookup_value(mapping.external_id))
        ] = mapping.internal_id

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
        normalized_source = _normalize_source(source)
        normalized_external_id = _normalize_lookup_value(external_id)
        return self._mapping_to_internal.get((normalized_source, normalized_external_id))

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

    def resolve_by_ibkr_conid(self, con_id: str) -> Optional[SecurityReference]:
        internal_id = self._by_ibkr_conid.get(str(con_id))
        if internal_id is None:
            return None
        return self._security_by_id.get(internal_id)

    def resolve_by_ibkr_alias(
        self,
        *,
        symbol: str,
        sec_type: str,
        exchange: str,
    ) -> Optional[SecurityReference]:
        internal_id = self._by_ibkr_alias.get(
            self._normalize_ibkr_alias(symbol=symbol, sec_type=sec_type, exchange=exchange)
        )
        if internal_id is None:
            return None
        return self._security_by_id.get(internal_id)

    def resolve_cash_reference(
        self,
        *,
        symbol: str,
        currency: str,
    ) -> Optional[SecurityReference]:
        aliases = [
            symbol,
            currency,
            "CASH",
            f"CASH_{currency}",
            f"{currency}_CASH",
        ]
        for alias in aliases:
            normalized = _normalize_lookup_value(alias)
            if not normalized:
                continue
            internal_id = self._by_cash_alias.get(normalized)
            if internal_id is not None:
                return self._security_by_id.get(internal_id)
        return None

    def register_runtime_contract(
        self,
        *,
        security: SecurityReference,
        con_id: str,
        symbol: str,
        exchange: str,
        local_symbol: str,
        sec_type: str,
    ) -> str:
        runtime_security = security.with_runtime_contract(
            con_id=con_id,
            symbol=symbol,
            exchange=exchange,
            local_symbol=local_symbol,
            sec_type=sec_type,
        )
        self.upsert_security(runtime_security)
        self.upsert_mapping(
            SecurityMapping(source="ibkr", external_id=con_id, internal_id=runtime_security.internal_id)
        )
        return runtime_security.internal_id

    def to_security_lookup(self) -> Dict[str, SecurityReference]:
        return dict(self._security_by_id)

    def to_rows(self) -> List[Dict[str, str]]:
        rows: List[Dict[str, str]] = []
        for internal_id in sorted(self._security_by_id):
            security = self._security_by_id[internal_id]
            if security.mapping_status != "mapped":
                continue
            rows.append(security.to_curated_row())
        return rows

    def _normalize_ibkr_alias(self, *, symbol: str, sec_type: str, exchange: str) -> IbkrAliasKey:
        normalized_symbol = _normalize_lookup_value(symbol)
        normalized_sec_type = _normalize_lookup_value(sec_type)
        normalized_exchange = _normalize_lookup_value(exchange)
        if normalized_sec_type == "FUT":
            normalized_symbol = normalize_contract_root(normalized_symbol)
        return (normalized_symbol, normalized_sec_type, normalized_exchange)


def export_security_reference_csv(
    rows: Iterable[SecurityReference],
    output_path: str | Path,
) -> Path:
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    materialized = list(rows)
    with destination.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CURATED_SECURITY_REFERENCE_HEADERS)
        writer.writeheader()
        for row in materialized:
            writer.writerow(row.to_curated_row())
    return destination


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


def normalize_contract_root(symbol: str) -> str:
    upper = _normalize_lookup_value(symbol)
    if "_" in upper:
        return upper
    if upper.endswith("W00") and len(upper) > 3:
        return upper[:-3]
    match = re.match(rf"^([A-Z0-9]+?)[{MONTH_CODES}]\d{{1,2}}$", upper)
    if match is not None:
        return match.group(1)
    return upper


def _normalize_universe_type(value: str) -> str:
    return _clean_optional_str(value).upper()


def _normalize_risk_bucket(value: str) -> str:
    normalized = _clean_optional_str(value).upper()
    if normalized == "MACRO":
        return "MACRO"
    return normalized


def _normalize_source(value: str) -> str:
    return _clean_optional_str(value).lower()


def _normalize_lookup_value(value: object) -> str:
    return _clean_optional_str(value).upper()


def _clean_optional_str(value: object) -> str:
    if value in (None, ""):
        return ""
    return str(value).strip()


def _parse_bool(value: object, *, default: bool) -> bool:
    if value in (None, ""):
        return default
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "y"}:
        return True
    if normalized in {"0", "false", "no", "n"}:
        return False
    return default


def _parse_float(value: object, *, default: float) -> float:
    if value in (None, ""):
        return default
    return float(value)


def _parse_optional_float(value: object) -> float | None:
    if value in (None, ""):
        return None
    return float(value)


def _stringify_float(value: float) -> str:
    rendered = "{value:.12g}".format(value=value)
    return rendered


def _stringify_optional_float(value: float | None) -> str:
    if value is None:
        return ""
    return _stringify_float(value)
