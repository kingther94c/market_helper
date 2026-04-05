from __future__ import annotations

"""Universe-first security-reference and lookup helpers.

The tracked ``security_universe.csv`` is the manual source of truth for report
and risk semantics. ``security_reference.csv`` is a generated wide table that
combines those semantics with cached broker/vendor lookup fields.
"""

import csv
import re
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Optional, Tuple


SourceKey = Tuple[str, str]
IbkrAliasKey = Tuple[str, str, str]

FUTURES_VENUES = {"CBOT", "CFE", "CME", "COMEX", "ICE", "NYMEX"}
ALLOWED_ASSET_CLASSES = {"CASH", "CM", "EQ", "FI", "FX", "MACRO"}
ALLOWED_DIR_EXPOSURES = {"L", "S"}
ALLOWED_FI_TENORS = {"0-3Y", "3-7Y", "7-10Y", "10Y+"}
SECURITY_UNIVERSE_HEADERS = [
    "asset_class",
    "ibkr_symbol",
    "display_name",
    "ibkr_exchange",
    "yahoo_symbol",
    "eq_country",
    "eq_sector",
    "dir_exposure",
    "fi_mod_duration",
    "fi_tenor",
]
SECURITY_UNIVERSE_PROPOSAL_HEADERS = SECURITY_UNIVERSE_HEADERS + [
    "lookup_primary_exchange",
    "lookup_currency",
    "lookup_multiplier",
    "lookup_sec_type",
    "lookup_conid",
    "proposal_reason",
]
SECURITY_REFERENCE_HEADERS = [
    "internal_id",
    "is_active",
    "asset_class",
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
    "yahoo_symbol",
    "eq_country",
    "eq_sector",
    "dir_exposure",
    "fi_mod_duration",
    "fi_tenor",
    "lookup_status",
    "last_verified_at",
]
CURATED_SECURITY_REFERENCE_HEADERS = SECURITY_REFERENCE_HEADERS
LEGACY_SECURITY_REFERENCE_HEADERS = [
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
DEFAULT_SECURITY_UNIVERSE_PATH = (
    Path(__file__).resolve().parents[2] / "configs" / "security_universe.csv"
)
RUNTIME_OUTSIDE_SCOPE_PREFIX = "OUTSIDE_SCOPE:"


@dataclass(frozen=True)
class SecurityUniverseRow:
    asset_class: str
    ibkr_symbol: str
    display_name: str
    ibkr_exchange: str
    yahoo_symbol: str = ""
    eq_country: str = ""
    eq_sector: str = ""
    dir_exposure: str = "L"
    fi_mod_duration: float | None = None
    fi_tenor: str = ""

    def __post_init__(self) -> None:
        asset_class = _clean_optional_str(self.asset_class).upper()
        if asset_class not in ALLOWED_ASSET_CLASSES:
            raise ValueError(f"Unsupported asset_class in security_universe: {asset_class or '<empty>'}")
        dir_exposure = _clean_optional_str(self.dir_exposure).upper() or "L"
        if dir_exposure not in ALLOWED_DIR_EXPOSURES:
            raise ValueError(f"Unsupported dir_exposure in security_universe: {dir_exposure}")
        fi_tenor = _clean_optional_str(self.fi_tenor).upper()
        if fi_tenor and fi_tenor not in ALLOWED_FI_TENORS:
            raise ValueError(f"Unsupported fi_tenor in security_universe: {fi_tenor}")
        object.__setattr__(self, "asset_class", asset_class)
        object.__setattr__(self, "ibkr_symbol", _clean_optional_str(self.ibkr_symbol).upper())
        object.__setattr__(self, "display_name", _clean_optional_str(self.display_name))
        object.__setattr__(self, "ibkr_exchange", _clean_optional_str(self.ibkr_exchange).upper())
        object.__setattr__(self, "yahoo_symbol", _clean_optional_str(self.yahoo_symbol))
        object.__setattr__(self, "eq_country", _clean_optional_str(self.eq_country).upper())
        object.__setattr__(self, "eq_sector", _clean_optional_str(self.eq_sector))
        object.__setattr__(self, "dir_exposure", dir_exposure)
        object.__setattr__(self, "fi_tenor", fi_tenor)

    @property
    def canonical_symbol(self) -> str:
        if self.asset_class == "CASH" and self.ibkr_exchange == "MANUAL":
            return f"{self.ibkr_symbol}_CASH_VALUE"
        return self.ibkr_symbol

    @property
    def resolved_ibkr_sec_type(self) -> str:
        if self.asset_class == "CASH" and self.ibkr_exchange == "MANUAL":
            return "CASH"
        if self.ibkr_exchange in FUTURES_VENUES:
            return "FUT"
        return "STK"

    @property
    def internal_id(self) -> str:
        return build_internal_security_id(
            ibkr_sec_type=self.resolved_ibkr_sec_type,
            canonical_symbol=self.canonical_symbol,
            primary_exchange=self.ibkr_exchange,
        )

    def to_csv_row(self) -> Dict[str, str]:
        return {
            "asset_class": self.asset_class,
            "ibkr_symbol": self.ibkr_symbol,
            "display_name": self.display_name,
            "ibkr_exchange": self.ibkr_exchange,
            "yahoo_symbol": self.yahoo_symbol,
            "eq_country": self.eq_country,
            "eq_sector": self.eq_sector,
            "dir_exposure": self.dir_exposure,
            "fi_mod_duration": _stringify_optional_float(self.fi_mod_duration),
            "fi_tenor": self.fi_tenor,
        }

    def to_reference_seed(self, prior: SecurityReference | None = None) -> SecurityReference:
        currency = prior.currency if prior is not None and prior.currency else _default_currency_for_universe_row(self)
        primary_exchange = (
            prior.primary_exchange
            if prior is not None and prior.primary_exchange
            else _default_primary_exchange_for_universe_row(self)
        )
        multiplier = prior.multiplier if prior is not None else 1.0
        lookup_status = (
            prior.lookup_status
            if prior is not None and prior.lookup_status
            else ("cached" if prior is not None and _has_cached_lookup(prior) else "seeded")
        )
        last_verified_at = prior.last_verified_at if prior is not None else ""
        return SecurityReference(
            internal_id=self.internal_id,
            is_active=True,
            asset_class=self.asset_class,
            canonical_symbol=self.canonical_symbol,
            display_ticker=self.canonical_symbol,
            display_name=self.display_name or self.canonical_symbol,
            currency=currency,
            primary_exchange=primary_exchange,
            multiplier=multiplier,
            ibkr_sec_type=self.resolved_ibkr_sec_type,
            ibkr_symbol=self.ibkr_symbol,
            ibkr_exchange=self.ibkr_exchange,
            ibkr_conid=prior.ibkr_conid if prior is not None else "",
            yahoo_symbol=self.yahoo_symbol,
            eq_country=self.eq_country,
            eq_sector=self.eq_sector,
            dir_exposure=self.dir_exposure,
            mod_duration=self.fi_mod_duration,
            fi_tenor=self.fi_tenor,
            lookup_status=lookup_status,
            last_verified_at=last_verified_at,
            symbol=prior.symbol if prior is not None and prior.symbol else self.canonical_symbol,
            exchange=prior.exchange if prior is not None and prior.exchange else (primary_exchange or self.ibkr_exchange),
            description=prior.description if prior is not None and prior.description else self.display_name,
            metadata=prior.metadata if prior is not None else {},
            mapping_status_hint="mapped",
        )


@dataclass(frozen=True)
class SecurityReference:
    internal_id: str
    asset_class: str = ""
    symbol: str = ""
    currency: str = ""
    exchange: str = ""
    description: str = ""
    multiplier: float = 1.0
    metadata: Dict[str, str] = field(default_factory=dict)
    is_active: bool = True
    canonical_symbol: str = ""
    display_ticker: str = ""
    display_name: str = ""
    primary_exchange: str = ""
    ibkr_sec_type: str = ""
    ibkr_symbol: str = ""
    ibkr_exchange: str = ""
    ibkr_conid: str = ""
    yahoo_symbol: str = ""
    eq_country: str = ""
    eq_sector: str = ""
    dir_exposure: str = "L"
    mod_duration: float | None = None
    fi_tenor: str = ""
    lookup_status: str = ""
    last_verified_at: str = ""
    mapping_status_hint: str = ""

    def __post_init__(self) -> None:
        metadata = {str(key): str(value) for key, value in (self.metadata or {}).items()}
        canonical_symbol = (
            _clean_optional_str(self.canonical_symbol)
            or _clean_optional_str(self.symbol)
            or _clean_optional_str(self.ibkr_symbol)
        )
        primary_exchange = _clean_optional_str(self.primary_exchange).upper()
        ibkr_exchange = _clean_optional_str(self.ibkr_exchange).upper() or primary_exchange
        exchange = _clean_optional_str(self.exchange).upper() or primary_exchange or ibkr_exchange
        symbol = _clean_optional_str(self.symbol).upper() or canonical_symbol
        display_ticker = _clean_optional_str(self.display_ticker) or canonical_symbol
        display_name = _clean_optional_str(self.display_name) or _clean_optional_str(self.description) or display_ticker
        description = _clean_optional_str(self.description) or display_name
        dir_exposure = _clean_optional_str(self.dir_exposure).upper() or "L"
        fi_tenor = _clean_optional_str(self.fi_tenor).upper()
        object.__setattr__(self, "metadata", metadata)
        object.__setattr__(self, "asset_class", _clean_optional_str(self.asset_class).upper())
        object.__setattr__(self, "symbol", symbol)
        object.__setattr__(self, "currency", _clean_optional_str(self.currency).upper())
        object.__setattr__(self, "exchange", exchange)
        object.__setattr__(self, "description", description)
        object.__setattr__(self, "canonical_symbol", canonical_symbol)
        object.__setattr__(self, "display_ticker", display_ticker)
        object.__setattr__(self, "display_name", display_name)
        object.__setattr__(self, "primary_exchange", primary_exchange)
        object.__setattr__(self, "ibkr_sec_type", _clean_optional_str(self.ibkr_sec_type).upper())
        object.__setattr__(self, "ibkr_symbol", _clean_optional_str(self.ibkr_symbol).upper() or symbol)
        object.__setattr__(self, "ibkr_exchange", ibkr_exchange)
        object.__setattr__(self, "ibkr_conid", _clean_optional_str(self.ibkr_conid))
        object.__setattr__(self, "yahoo_symbol", _clean_optional_str(self.yahoo_symbol))
        object.__setattr__(self, "eq_country", _clean_optional_str(self.eq_country).upper())
        object.__setattr__(self, "eq_sector", _clean_optional_str(self.eq_sector))
        object.__setattr__(self, "dir_exposure", dir_exposure)
        object.__setattr__(self, "fi_tenor", fi_tenor)
        object.__setattr__(self, "lookup_status", _clean_optional_str(self.lookup_status).lower())
        object.__setattr__(self, "last_verified_at", _clean_optional_str(self.last_verified_at))
        object.__setattr__(self, "mapping_status_hint", _clean_optional_str(self.mapping_status_hint).lower())

    @property
    def mapping_status(self) -> str:
        if self.mapping_status_hint:
            return self.mapping_status_hint
        if self.internal_id.startswith(RUNTIME_OUTSIDE_SCOPE_PREFIX):
            return "outside_scope"
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
        primary_exchange: str,
        local_symbol: str,
        sec_type: str,
        currency: str = "",
        multiplier: float | None = None,
    ) -> SecurityReference:
        metadata = dict(self.metadata)
        metadata.update(
            {
                "ibkr_con_id": str(con_id),
                "local_symbol": str(local_symbol),
                "runtime_symbol": str(symbol).upper(),
                "runtime_exchange": str(exchange).upper(),
                "runtime_primary_exchange": str(primary_exchange).upper(),
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
            primary_exchange=str(primary_exchange).upper() or self.primary_exchange,
            currency=str(currency).upper() or self.currency,
            multiplier=self.multiplier if multiplier is None else float(multiplier),
            ibkr_sec_type=str(sec_type).upper() or self.ibkr_sec_type,
            lookup_status="verified",
            last_verified_at=now_utc_iso(),
        )

    def validate_curated(self) -> None:
        if not self.internal_id:
            raise ValueError("security_reference row is missing internal_id")
        if self.mapping_status != "mapped":
            raise ValueError(f"Generated security_reference cannot export runtime row: {self.internal_id}")
        if self.asset_class not in ALLOWED_ASSET_CLASSES:
            raise ValueError(f"Invalid asset_class for {self.internal_id}: {self.asset_class}")
        if self.dir_exposure not in ALLOWED_DIR_EXPOSURES:
            raise ValueError(f"Invalid dir_exposure for {self.internal_id}: {self.dir_exposure}")
        if self.fi_tenor and self.fi_tenor not in ALLOWED_FI_TENORS:
            raise ValueError(f"Invalid fi_tenor for {self.internal_id}: {self.fi_tenor}")

    def to_csv_row(self, *, validate_curated: bool = True) -> Dict[str, str]:
        if validate_curated:
            self.validate_curated()
        return {
            "internal_id": self.internal_id,
            "is_active": "true" if self.is_active else "false",
            "asset_class": self.asset_class,
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
            "yahoo_symbol": self.yahoo_symbol,
            "eq_country": self.eq_country,
            "eq_sector": self.eq_sector,
            "dir_exposure": self.dir_exposure,
            "fi_mod_duration": _stringify_optional_float(self.mod_duration),
            "fi_tenor": self.fi_tenor,
            "lookup_status": self.lookup_status,
            "last_verified_at": self.last_verified_at,
        }

    def to_curated_row(self) -> Dict[str, str]:
        return self.to_csv_row(validate_curated=True)

    def to_universe_proposal_row(self, *, proposal_reason: str) -> Dict[str, str]:
        return {
            "asset_class": self.asset_class or _infer_asset_class_from_security(self),
            "ibkr_symbol": self.ibkr_symbol or self.symbol or self.canonical_symbol,
            "display_name": self.display_name or self.description or self.canonical_symbol,
            "ibkr_exchange": self.exchange or self.primary_exchange or self.ibkr_exchange,
            "yahoo_symbol": self.yahoo_symbol,
            "eq_country": self.eq_country,
            "eq_sector": self.eq_sector,
            "dir_exposure": self.dir_exposure or "L",
            "fi_mod_duration": _stringify_optional_float(self.mod_duration),
            "fi_tenor": self.fi_tenor,
            "lookup_primary_exchange": self.primary_exchange,
            "lookup_currency": self.currency,
            "lookup_multiplier": _stringify_float(self.multiplier),
            "lookup_sec_type": self.ibkr_sec_type,
            "lookup_conid": self.ibkr_conid,
            "proposal_reason": proposal_reason,
        }

    @classmethod
    def from_curated_row(cls, row: Mapping[str, object]) -> SecurityReference:
        return cls(
            internal_id=str(row.get("internal_id") or ""),
            is_active=_parse_bool(row.get("is_active"), default=True),
            asset_class=str(row.get("asset_class") or ""),
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
            yahoo_symbol=str(row.get("yahoo_symbol") or ""),
            eq_country=str(row.get("eq_country") or ""),
            eq_sector=str(row.get("eq_sector") or ""),
            dir_exposure=str(row.get("dir_exposure") or "L"),
            mod_duration=_parse_optional_float(row.get("fi_mod_duration")),
            fi_tenor=str(row.get("fi_tenor") or ""),
            lookup_status=str(row.get("lookup_status") or ""),
            last_verified_at=str(row.get("last_verified_at") or ""),
        )

    @classmethod
    def from_legacy_curated_row(cls, row: Mapping[str, object]) -> SecurityReference:
        asset_class = _legacy_asset_class(row)
        canonical_symbol = str(row.get("canonical_symbol") or "")
        primary_exchange = str(row.get("primary_exchange") or "")
        ibkr_exchange = str(row.get("ibkr_exchange") or primary_exchange)
        ibkr_sec_type = str(row.get("ibkr_sec_type") or "")
        internal_id = str(row.get("internal_id") or "")
        if not internal_id:
            internal_id = build_internal_security_id(
                ibkr_sec_type=ibkr_sec_type,
                canonical_symbol=canonical_symbol,
                primary_exchange=ibkr_exchange,
            )
        return cls(
            internal_id=internal_id,
            is_active=_parse_bool(row.get("is_active"), default=True),
            asset_class=asset_class,
            canonical_symbol=canonical_symbol,
            display_ticker=str(row.get("display_ticker") or ""),
            display_name=str(row.get("display_name") or ""),
            currency=str(row.get("currency") or ""),
            primary_exchange=primary_exchange,
            multiplier=_parse_float(row.get("multiplier"), default=1.0),
            ibkr_sec_type=ibkr_sec_type,
            ibkr_symbol=str(row.get("ibkr_symbol") or canonical_symbol),
            ibkr_exchange=ibkr_exchange,
            ibkr_conid=str(row.get("ibkr_conid") or ""),
            yahoo_symbol=str(row.get("yahoo_symbol") or ""),
            dir_exposure="L",
            mod_duration=_parse_optional_float(row.get("mod_duration")),
            fi_tenor="",
            lookup_status="cached",
            last_verified_at="",
        )


@dataclass(frozen=True)
class SecurityMapping:
    source: str
    external_id: str
    internal_id: str


@dataclass(frozen=True)
class PositionSnapshot:
    as_of: str
    account: str
    internal_id: str
    source: str
    quantity: float
    avg_cost: Optional[float]
    market_value: Optional[float]


@dataclass(frozen=True)
class PriceSnapshot:
    as_of: str
    internal_id: str
    source: str
    last_price: float


class SecurityUniverseTable:
    def __init__(self, rows: Iterable[SecurityUniverseRow]) -> None:
        self.rows = list(rows)

    @classmethod
    def from_csv(cls, path: str | Path) -> SecurityUniverseTable:
        with Path(path).open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            fieldnames = reader.fieldnames or []
            missing = [column for column in SECURITY_UNIVERSE_HEADERS if column not in fieldnames]
            if missing:
                raise ValueError(
                    "security_universe CSV is missing required columns: {value}".format(
                        value=", ".join(missing)
                    )
                )
            rows = [
                SecurityUniverseRow(
                    asset_class=str(row.get("asset_class") or ""),
                    ibkr_symbol=str(row.get("ibkr_symbol") or ""),
                    display_name=str(row.get("display_name") or ""),
                    ibkr_exchange=str(row.get("ibkr_exchange") or ""),
                    yahoo_symbol=str(row.get("yahoo_symbol") or ""),
                    eq_country=str(row.get("eq_country") or ""),
                    eq_sector=str(row.get("eq_sector") or ""),
                    dir_exposure=str(row.get("dir_exposure") or "L"),
                    fi_mod_duration=_parse_optional_float(row.get("fi_mod_duration")),
                    fi_tenor=str(row.get("fi_tenor") or ""),
                )
                for row in reader
                if any((value or "").strip() for value in row.values())
            ]
        return cls(rows)

    @classmethod
    def from_default_csv(cls) -> SecurityUniverseTable:
        return cls.from_csv(DEFAULT_SECURITY_UNIVERSE_PATH)


class SecurityReferenceTable:
    def __init__(self) -> None:
        self._security_by_id: Dict[str, SecurityReference] = {}
        self._mapping_to_internal: Dict[SourceKey, str] = {}
        self._by_ibkr_conid: Dict[str, str] = {}
        self._by_ibkr_alias: Dict[IbkrAliasKey, str] = {}
        self._by_yahoo_symbol: Dict[str, str] = {}
        self._by_cash_alias: Dict[str, str] = {}

    @classmethod
    def from_csv(cls, path: str | Path) -> SecurityReferenceTable:
        table = cls()
        with Path(path).open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            fieldnames = reader.fieldnames or []
            if _is_new_reference_schema(fieldnames):
                for row in reader:
                    if not any((value or "").strip() for value in row.values()):
                        continue
                    table.upsert_security(SecurityReference.from_curated_row(row))
                return table

            if _is_legacy_reference_schema(fieldnames):
                for row in reader:
                    if not any((value or "").strip() for value in row.values()):
                        continue
                    table.upsert_security(SecurityReference.from_legacy_curated_row(row))
                return table

            missing = [column for column in SECURITY_REFERENCE_HEADERS if column not in fieldnames]
            raise ValueError(
                "security_reference CSV is missing required columns: {value}".format(
                    value=", ".join(missing)
                )
            )

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
    def by_yahoo_symbol(self) -> Dict[str, SecurityReference]:
        return {
            symbol: self._security_by_id[internal_id]
            for symbol, internal_id in self._by_yahoo_symbol.items()
            if internal_id in self._security_by_id
        }

    def upsert_security(self, security: SecurityReference) -> None:
        self._security_by_id[security.internal_id] = security

        if security.ibkr_conid:
            self._by_ibkr_conid[security.ibkr_conid] = security.internal_id
            self._mapping_to_internal[("ibkr", security.ibkr_conid)] = security.internal_id

        if security.ibkr_symbol and security.ibkr_sec_type:
            exchanges = {
                security.ibkr_exchange,
                security.primary_exchange,
                security.exchange,
                security.metadata.get("runtime_exchange", ""),
                security.metadata.get("runtime_primary_exchange", ""),
            }
            for exchange in exchanges:
                normalized = _clean_optional_str(exchange).upper()
                if not normalized:
                    continue
                alias_key = self._normalize_ibkr_alias(
                    symbol=security.ibkr_symbol,
                    sec_type=security.ibkr_sec_type,
                    exchange=normalized,
                )
                self._by_ibkr_alias[alias_key] = security.internal_id

        if security.yahoo_symbol:
            normalized = _normalize_lookup_value(security.yahoo_symbol)
            self._by_yahoo_symbol[normalized] = security.internal_id
            self._mapping_to_internal[("yahoo", normalized)] = security.internal_id
            self._mapping_to_internal[("yahoo_finance", normalized)] = security.internal_id

        if security.asset_class == "CASH":
            aliases = {
                security.canonical_symbol,
                security.display_ticker,
                security.symbol,
                security.currency,
                security.ibkr_symbol,
            }
            for alias in aliases:
                normalized = _normalize_lookup_value(alias)
                if normalized:
                    self._by_cash_alias[normalized] = security.internal_id

    def upsert_mapping(self, mapping: SecurityMapping) -> None:
        if mapping.internal_id not in self._security_by_id:
            raise KeyError(f"Mapping references unknown internal_id: {mapping.internal_id}")
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
            self.upsert_mapping(mapping)

    def resolve_internal_id(self, source: str, external_id: str) -> Optional[str]:
        return self._mapping_to_internal.get(
            (_normalize_source(source), _normalize_lookup_value(external_id))
        )

    def require_internal_id(self, source: str, external_id: str) -> str:
        internal_id = self.resolve_internal_id(source=source, external_id=external_id)
        if internal_id is None:
            raise KeyError(f"No mapping for source={source}, external_id={external_id}")
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

    def resolve_by_yahoo_symbol(self, symbol: str) -> Optional[SecurityReference]:
        internal_id = self._by_yahoo_symbol.get(_normalize_lookup_value(symbol))
        if internal_id is None:
            return None
        return self._security_by_id.get(internal_id)

    def resolve_cash_reference(
        self,
        *,
        symbol: str,
        currency: str,
    ) -> Optional[SecurityReference]:
        aliases = [symbol, currency, "CASH", f"CASH_{currency}", f"{currency}_CASH"]
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
        primary_exchange: str,
        local_symbol: str,
        sec_type: str,
        currency: str = "",
        multiplier: float | None = None,
    ) -> str:
        runtime_security = security.with_runtime_contract(
            con_id=con_id,
            symbol=symbol,
            exchange=exchange,
            primary_exchange=primary_exchange,
            local_symbol=local_symbol,
            sec_type=sec_type,
            currency=currency,
            multiplier=multiplier,
        )
        self.upsert_security(runtime_security)
        self.upsert_mapping(
            SecurityMapping(source="ibkr", external_id=con_id, internal_id=runtime_security.internal_id)
        )
        return runtime_security.internal_id

    def to_security_lookup(self) -> Dict[str, SecurityReference]:
        return dict(self._security_by_id)

    def to_rows(self) -> List[SecurityReference]:
        return [
            self._security_by_id[internal_id]
            for internal_id in sorted(self._security_by_id)
            if self._security_by_id[internal_id].mapping_status == "mapped"
        ]

    def to_proposed_rows(self) -> List[SecurityReference]:
        return [
            self._security_by_id[internal_id]
            for internal_id in sorted(self._security_by_id)
            if self._security_by_id[internal_id].mapping_status == "unmapped"
        ]

    def to_universe_proposal_rows(self) -> List[Dict[str, str]]:
        return [
            security.to_universe_proposal_row(proposal_reason="unmapped_security")
            for security in self.to_proposed_rows()
        ]

    def search_by_ibkr_symbol_sec_type(
        self,
        *,
        symbol: str,
        sec_type: str,
    ) -> List[SecurityReference]:
        normalized_symbol = _normalize_lookup_value(symbol)
        normalized_sec_type = _normalize_lookup_value(sec_type)
        if normalized_sec_type == "FUT":
            normalized_symbol = normalize_contract_root(normalized_symbol)

        matches: List[SecurityReference] = []
        for security in self._security_by_id.values():
            if security.mapping_status != "mapped":
                continue
            candidate_symbol = _normalize_lookup_value(
                security.ibkr_symbol or security.symbol or security.canonical_symbol
            )
            candidate_sec_type = _normalize_lookup_value(security.ibkr_sec_type)
            if candidate_sec_type == "FUT":
                candidate_symbol = normalize_contract_root(candidate_symbol)
            if candidate_symbol == normalized_symbol and candidate_sec_type == normalized_sec_type:
                matches.append(security)
        return sorted(matches, key=lambda item: item.internal_id)

    def find_cached_security_for_universe_row(
        self,
        row: SecurityUniverseRow,
    ) -> SecurityReference | None:
        exact = self.get_security(row.internal_id)
        if exact is not None:
            return exact
        alias = self.resolve_by_ibkr_alias(
            symbol=row.ibkr_symbol,
            sec_type=row.resolved_ibkr_sec_type,
            exchange=row.ibkr_exchange,
        )
        if alias is not None:
            return alias
        if row.asset_class == "CASH":
            cash = self.resolve_cash_reference(symbol=row.ibkr_symbol, currency=row.ibkr_symbol)
            if cash is not None:
                return cash
        matches = self.search_by_ibkr_symbol_sec_type(
            symbol=row.ibkr_symbol,
            sec_type=row.resolved_ibkr_sec_type,
        )
        if len(matches) == 1:
            return matches[0]
        return None

    def _normalize_ibkr_alias(self, *, symbol: str, sec_type: str, exchange: str) -> IbkrAliasKey:
        normalized_symbol = _normalize_lookup_value(symbol)
        normalized_sec_type = _normalize_lookup_value(sec_type)
        normalized_exchange = _normalize_lookup_value(exchange)
        if normalized_sec_type == "FUT":
            normalized_symbol = normalize_contract_root(normalized_symbol)
        return (normalized_symbol, normalized_sec_type, normalized_exchange)


def build_security_reference_table(
    *,
    universe_path: str | Path | None = None,
    reference_path: str | Path | None = None,
) -> SecurityReferenceTable:
    universe = SecurityUniverseTable.from_csv(universe_path or DEFAULT_SECURITY_UNIVERSE_PATH)
    prior = _load_prior_reference_table(reference_path or DEFAULT_SECURITY_REFERENCE_PATH)
    table = SecurityReferenceTable()
    for row in universe.rows:
        prior_row = prior.find_cached_security_for_universe_row(row) if prior is not None else None
        table.upsert_security(row.to_reference_seed(prior_row))
    return table


def sync_security_reference_csv(
    *,
    universe_path: str | Path | None = None,
    reference_path: str | Path | None = None,
) -> Path:
    destination = Path(reference_path or DEFAULT_SECURITY_REFERENCE_PATH)
    table = build_security_reference_table(
        universe_path=universe_path,
        reference_path=destination,
    )
    return export_security_reference_csv(table.to_rows(), destination)


def export_security_reference_csv(
    rows: Iterable[SecurityReference],
    output_path: str | Path,
    *,
    validate_curated: bool = True,
) -> Path:
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=SECURITY_REFERENCE_HEADERS)
        writer.writeheader()
        for row in rows:
            writer.writerow(row.to_csv_row(validate_curated=validate_curated))
    return destination


def export_security_universe_proposal_csv(
    rows: Iterable[Mapping[str, object] | SecurityReference],
    output_path: str | Path,
) -> Path:
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=SECURITY_UNIVERSE_PROPOSAL_HEADERS)
        writer.writeheader()
        for row in rows:
            if isinstance(row, SecurityReference):
                materialized = row.to_universe_proposal_row(proposal_reason="unmapped_security")
            else:
                materialized = {
                    column: _clean_optional_str(row.get(column))
                    for column in SECURITY_UNIVERSE_PROPOSAL_HEADERS
                }
            writer.writerow(materialized)
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


def build_internal_security_id(
    *,
    ibkr_sec_type: str,
    canonical_symbol: str,
    primary_exchange: str,
) -> str:
    safe_sec_type = _internal_id_component(ibkr_sec_type or "UNKNOWN")
    safe_symbol = _internal_id_component(canonical_symbol)
    safe_exchange = _internal_id_component(primary_exchange or "GENERIC")
    return f"{safe_sec_type}:{safe_symbol}:{safe_exchange}"


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


def _load_prior_reference_table(path: str | Path) -> SecurityReferenceTable | None:
    try:
        return SecurityReferenceTable.from_csv(path)
    except FileNotFoundError:
        return None


def _default_currency_for_universe_row(row: SecurityUniverseRow) -> str:
    if row.asset_class == "CASH" and row.ibkr_exchange == "MANUAL":
        return row.ibkr_symbol
    return "USD"


def _default_primary_exchange_for_universe_row(row: SecurityUniverseRow) -> str:
    if row.ibkr_exchange == "SMART":
        return ""
    return row.ibkr_exchange


def _has_cached_lookup(security: SecurityReference) -> bool:
    return bool(
        security.ibkr_conid
        or security.primary_exchange
        or security.currency
        or security.last_verified_at
        or security.lookup_status
    )


def _legacy_asset_class(row: Mapping[str, object]) -> str:
    risk_bucket = _clean_optional_str(row.get("risk_bucket")).upper()
    if risk_bucket in ALLOWED_ASSET_CLASSES:
        return risk_bucket
    universe_type = _clean_optional_str(row.get("universe_type")).upper()
    if universe_type == "CASH":
        return "CASH"
    if universe_type in {"FI_FUT", "FI"}:
        return "FI"
    if universe_type in {"FX_FUT", "FX"}:
        return "FX"
    if risk_bucket == "GOLD":
        return "CM"
    if universe_type == "EQ":
        return "EQ"
    return "EQ"


def _infer_asset_class_from_security(security: SecurityReference) -> str:
    if security.asset_class:
        return security.asset_class
    if security.ibkr_sec_type == "CASH":
        return "CASH"
    if security.ibkr_sec_type == "FUT":
        symbol = security.ibkr_symbol or security.canonical_symbol
        if symbol in {"AUD", "CAD", "CHF", "EUR", "GBP", "JPY", "MXN", "NZD"}:
            return "FX"
        if symbol in {"ZN", "ZF", "ZT", "TY", "US"}:
            return "FI"
        return "CM"
    return "EQ"


def _is_new_reference_schema(fieldnames: list[str]) -> bool:
    return all(column in fieldnames for column in SECURITY_REFERENCE_HEADERS)


def _is_legacy_reference_schema(fieldnames: list[str]) -> bool:
    return all(column in fieldnames for column in LEGACY_SECURITY_REFERENCE_HEADERS)


def _normalize_source(value: str) -> str:
    return _clean_optional_str(value).lower()


def _normalize_lookup_value(value: object) -> str:
    return _clean_optional_str(value).upper()


def _internal_id_component(value: object) -> str:
    upper = _clean_optional_str(value).upper()
    return re.sub(r"[^A-Z0-9]+", "_", upper).strip("_")


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
    return "{value:.12g}".format(value=value)


def _stringify_optional_float(value: float | None) -> str:
    if value is None:
        return ""
    return _stringify_float(value)
