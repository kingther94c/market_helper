from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from zipfile import ZipFile

from market_helper.portfolio.security_reference import (
    SecurityReference,
    SecurityReferenceTable,
    build_internal_security_id,
    export_security_reference_csv,
    normalize_contract_root,
)


WORKBOOK_NS = {
    "a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "pr": "http://schemas.openxmlformats.org/package/2006/relationships",
}
FUTURES_VENUES = {"CBOT", "CME", "COMEX", "ICE", "NYMEX"}
FX_FUTURE_SYMBOLS = {"AUD", "CAD", "CHF", "EUR", "GBP", "JPY", "MXN", "NZD"}


@dataclass(frozen=True)
class SecurityReferenceSeedTable:
    source_workbook: str
    generated_at: str
    rows: list[SecurityReference]


@dataclass(frozen=True)
class WorkbookCell:
    value: str | None
    formula: str | None


def extract_security_reference_seed(workbook_path: str | Path) -> SecurityReferenceSeedTable:
    workbook = Path(workbook_path)
    sheets = _load_sheet_rows(workbook)
    position_rows = sheets.get("Position", [])
    fx_sources = _extract_fx_sources(position_rows)

    extracted: list[SecurityReference] = []
    for row in position_rows:
        reference = _extract_security_reference_row(row, fx_sources=fx_sources)
        if reference is None:
            continue
        extracted.append(reference)

    return SecurityReferenceSeedTable(
        source_workbook=str(workbook),
        generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        rows=extracted,
    )


def export_security_reference_seed_csv(
    table: SecurityReferenceSeedTable,
    output_path: str | Path,
) -> Path:
    return export_security_reference_csv(table.rows, output_path)


def load_security_reference_seed_table(path: str | Path) -> SecurityReferenceTable:
    return SecurityReferenceTable.from_csv(path)


def normalize_mapping_venue(raw_exchange: str) -> str:
    exchange = raw_exchange.strip().upper()
    if exchange in FUTURES_VENUES:
        return exchange
    if exchange in {"LSEETF", "SBF", "LSE", "SWX", "INTL"}:
        return "INTL"
    return "US"


def normalize_mapping_symbol(raw_symbol: str) -> str:
    symbol = raw_symbol.strip().upper()
    if not symbol:
        return symbol
    if ":" in symbol:
        left, right = symbol.split(":", 1)
        if right in FUTURES_VENUES:
            return normalize_contract_root(left)
        if left in {"LON", "NYSE", "NASDAQ", "PAR"}:
            return right
    return normalize_contract_root(symbol)


def risk_bucket_for_category(category: str) -> str:
    normalized = category.strip().upper()
    if normalized in {"DMEQ", "EMEQ", "EQ"}:
        return "EQ"
    if normalized == "FI":
        return "FI"
    if normalized == "GOLD":
        return "GOLD"
    if normalized in {"CM", "OIL"}:
        return "CM"
    if normalized == "CASH":
        return "CASH"
    if normalized in {"MACRO", "FX"}:
        return "MACRO"
    return normalized or "EQ"


def _extract_security_reference_row(
    row: dict[str, WorkbookCell],
    *,
    fx_sources: dict[str, tuple[str, str]],
) -> SecurityReference | None:
    category = _cell_value(row, "H")
    display_ticker = _cell_value(row, "I")
    display_name = _cell_value(row, "J")
    instrument_type = _cell_value(row, "O")
    if category in (None, "", "Category"):
        return None
    if display_ticker in (None, "", "Ticker"):
        return None
    if instrument_type in (None, "", "Type"):
        return None
    if str(display_ticker).startswith("CURRENCY:"):
        return None

    normalized_category = str(category).strip().upper()
    symbol_key = normalize_mapping_symbol(str(display_ticker))
    venue = _mapping_venue_for_ticker(str(display_ticker))
    risk_bucket = risk_bucket_for_category(normalized_category)
    universe_type = _infer_universe_type(
        symbol_key=symbol_key,
        instrument_type=str(instrument_type),
        risk_bucket=risk_bucket,
    )
    ibkr_sec_type = _ibkr_sec_type_for_universe(universe_type)
    primary_exchange = _ibkr_exchange_for_venue(venue)
    quote_formula = _cell_formula(row, "M")
    price_provider = _provider_from_formula(quote_formula)
    price_symbol = str(display_ticker).strip()
    fx_provider, fx_symbol = _fx_hint_for_row(
        display_ticker=str(display_ticker).strip(),
        venue=venue,
        fx_sources=fx_sources,
    )
    return SecurityReference(
        internal_id=_build_internal_id(
            ibkr_sec_type=ibkr_sec_type,
            canonical_symbol=symbol_key,
            primary_exchange=primary_exchange,
        ),
        is_active=True,
        universe_type=universe_type,
        canonical_symbol=_canonical_symbol(symbol_key),
        display_ticker=str(display_ticker).strip(),
        display_name=str(display_name or display_ticker).strip(),
        currency="USD",
        primary_exchange=primary_exchange,
        multiplier=_optional_float(_cell_value(row, "L")) or 1.0,
        ibkr_sec_type=ibkr_sec_type,
        ibkr_symbol=symbol_key,
        ibkr_exchange=primary_exchange,
        google_symbol=price_symbol if price_provider == "google_finance" else "",
        yahoo_symbol=price_symbol if price_provider == "yahoo_finance" else "",
        bbg_symbol="",
        report_category=normalized_category,
        risk_bucket=risk_bucket,
        mod_duration=_optional_float(_cell_value(row, "P")),
        default_expected_vol=_optional_float(_cell_value(row, "T")),
        price_source_provider=price_provider,
        price_source_symbol=price_symbol,
        fx_source_provider=fx_provider,
        fx_source_symbol=fx_symbol,
    )


def _load_sheet_rows(workbook_path: Path) -> dict[str, list[dict[str, WorkbookCell]]]:
    with ZipFile(workbook_path) as archive:
        shared_strings = _load_shared_strings(archive)
        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        relations = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        relation_map = {
            relation.attrib["Id"]: relation.attrib["Target"]
            for relation in relations.findall("pr:Relationship", WORKBOOK_NS)
        }

        sheets: dict[str, list[dict[str, WorkbookCell]]] = {}
        for sheet in workbook.find("a:sheets", WORKBOOK_NS):
            name = sheet.attrib["name"]
            relation_id = sheet.attrib[
                "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
            ]
            target = relation_map[relation_id]
            if not target.startswith("xl/"):
                target = f"xl/{target}"
            sheets[name] = _load_single_sheet_rows(archive, target, shared_strings)
        return sheets


def _load_single_sheet_rows(
    archive: ZipFile,
    target: str,
    shared_strings: list[str],
) -> list[dict[str, WorkbookCell]]:
    root = ET.fromstring(archive.read(target))
    rows: list[dict[str, WorkbookCell]] = []

    for row in root.findall(".//a:sheetData/a:row", WORKBOOK_NS):
        materialized: dict[str, WorkbookCell] = {}
        for cell in row.findall("a:c", WORKBOOK_NS):
            ref = cell.attrib.get("r", "")
            column = "".join(ch for ch in ref if ch.isalpha())
            materialized[column] = _load_cell(cell, shared_strings)
        rows.append(materialized)

    return rows


def _load_cell(cell: ET.Element, shared_strings: list[str]) -> WorkbookCell:
    value_node = cell.find("a:v", WORKBOOK_NS)
    formula_node = cell.find("a:f", WORKBOOK_NS)
    inline_node = cell.find("a:is", WORKBOOK_NS)
    cell_type = cell.attrib.get("t")

    value: str | None = None
    if inline_node is not None:
        value = "".join(text.text or "" for text in inline_node.iterfind(".//a:t", WORKBOOK_NS))
    elif value_node is not None:
        raw = value_node.text
        if cell_type == "s" and raw is not None:
            idx = int(raw)
            value = shared_strings[idx] if idx < len(shared_strings) else raw
        else:
            value = raw

    formula = formula_node.text if formula_node is not None and formula_node.text else None
    return WorkbookCell(value=value, formula=formula)


def _load_shared_strings(archive: ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in archive.namelist():
        return []

    root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
    return [
        "".join(text.text or "" for text in item.iterfind(".//a:t", WORKBOOK_NS))
        for item in root.findall("a:si", WORKBOOK_NS)
    ]


def _extract_fx_sources(rows: list[dict[str, WorkbookCell]]) -> dict[str, tuple[str, str]]:
    extracted: dict[str, tuple[str, str]] = {}

    for row in rows:
        symbol = _cell_value(row, "I")
        if symbol is None or not str(symbol).startswith("CURRENCY:"):
            continue
        currency_pair = str(symbol).split(":", 1)[1].upper()
        extracted[currency_pair] = (
            _provider_from_formula(_cell_formula(row, "J")),
            str(symbol).strip(),
        )

    return extracted


def _build_internal_id(
    *,
    ibkr_sec_type: str,
    canonical_symbol: str,
    primary_exchange: str,
) -> str:
    return build_internal_security_id(
        ibkr_sec_type=ibkr_sec_type,
        canonical_symbol=canonical_symbol,
        primary_exchange=primary_exchange,
    )


def _canonical_symbol(value: str) -> str:
    upper = value.strip().upper()
    return re.sub(r"[^A-Z0-9]+", "_", upper).strip("_")


def _infer_universe_type(
    *,
    symbol_key: str,
    instrument_type: str,
    risk_bucket: str,
) -> str:
    normalized_type = instrument_type.strip().upper()
    if normalized_type == "CASH":
        return "CASH"
    if normalized_type == "FUTURES":
        if risk_bucket == "FI":
            return "FI_FUT"
        if symbol_key in FX_FUTURE_SYMBOLS or risk_bucket == "MACRO":
            return "FX_FUT"
        return "OTHER_FUT"
    if symbol_key in {"TSLA"}:
        return "EQ"
    return "ETF"


def _ibkr_sec_type_for_universe(universe_type: str) -> str:
    if universe_type in {"FI_FUT", "FX_FUT", "OTHER_FUT"}:
        return "FUT"
    if universe_type == "CASH":
        return "CASH"
    return "STK"


def _ibkr_exchange_for_venue(venue: str) -> str:
    if venue == "INTL":
        return "LSEETF"
    if venue == "US":
        return "SMART"
    return venue


def _fx_hint_for_row(
    *,
    display_ticker: str,
    venue: str,
    fx_sources: dict[str, tuple[str, str]],
) -> tuple[str, str]:
    if venue == "INTL" and "GBPUSD" in fx_sources:
        return fx_sources["GBPUSD"]
    if display_ticker.upper().startswith("CASH (SGD") and "SGDUSD" in fx_sources:
        return fx_sources["SGDUSD"]
    return ("", "")


def _mapping_venue_for_ticker(display_ticker: str) -> str:
    ticker = display_ticker.strip().upper()
    if ticker.startswith("LON:"):
        return "INTL"
    if ":" in ticker:
        _left, right = ticker.split(":", 1)
        if right in FUTURES_VENUES:
            return right
    return "US"


def _provider_from_formula(formula: str | None) -> str:
    if formula is None:
        return "manual"
    upper = formula.upper()
    if "GOOGLEFINANCE" in upper or "GOOGLE.COM/FINANCE" in upper:
        return "google_finance"
    if "YAHOO" in upper:
        return "yahoo_finance"
    if "IBKR" in upper:
        return "ibkr"
    return "manual"


def _cell_value(row: dict[str, WorkbookCell], column: str) -> str | None:
    cell = row.get(column)
    if cell is None:
        return None
    return cell.value


def _cell_formula(row: dict[str, WorkbookCell], column: str) -> str | None:
    cell = row.get(column)
    if cell is None:
        return None
    return cell.formula


def _optional_float(value: object) -> float | None:
    if value in (None, ""):
        return None
    return float(value)
