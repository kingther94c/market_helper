from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from zipfile import ZipFile


WORKBOOK_NS = {
    "a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "pr": "http://schemas.openxmlformats.org/package/2006/relationships",
}
FUTURES_VENUES = {"CBOT", "CME", "COMEX", "ICE", "NYMEX"}
MONTH_CODES = "FGHJKMNQUVXZ"
DEFAULT_TEN_YEAR_EQUIV_DURATION = 7.627


@dataclass(frozen=True)
class LiveDataSource:
    provider: str
    symbol: str


@dataclass(frozen=True)
class InstrumentMappingRow:
    symbol_key: str
    venue: str
    display_ticker: str
    display_name: str
    category: str
    risk_bucket: str
    instrument_type: str
    multiplier: float
    duration: float | None = None
    expected_vol: float | None = None
    quote_source: LiveDataSource | None = None


@dataclass(frozen=True)
class FxSourceRow:
    currency_pair: str
    provider: str
    symbol: str


@dataclass(frozen=True)
class RiskProxySourceRow:
    risk_bucket: str
    provider: str
    symbol: str
    proxy_name: str
    unit: str
    tail_level: float | None = None


@dataclass(frozen=True)
class ReportMappingTable:
    source_workbook: str
    generated_at: str
    ten_year_equiv_duration: float
    instruments: list[InstrumentMappingRow]
    fx_sources: list[FxSourceRow]
    risk_proxies: list[RiskProxySourceRow]


@dataclass(frozen=True)
class WorkbookCell:
    value: str | None
    formula: str | None


def extract_report_mapping_table(workbook_path: str | Path) -> ReportMappingTable:
    workbook = Path(workbook_path)
    sheets = _load_sheet_rows(workbook)
    position_rows = sheets.get("Position", [])
    risk_rows = sheets.get("Risk", [])

    instruments = _extract_instrument_rows(position_rows)
    fx_sources = _extract_fx_sources(position_rows)
    risk_proxies = _extract_risk_proxy_sources(risk_rows)

    ten_year_equiv_duration = next(
        (
            row.duration
            for row in instruments
            if row.symbol_key == "ZN" and row.venue == "CBOT" and row.duration is not None
        ),
        DEFAULT_TEN_YEAR_EQUIV_DURATION,
    )

    return ReportMappingTable(
        source_workbook=str(workbook),
        generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        ten_year_equiv_duration=ten_year_equiv_duration,
        instruments=instruments,
        fx_sources=fx_sources,
        risk_proxies=risk_proxies,
    )


def export_report_mapping_table_json(
    table: ReportMappingTable,
    output_path: str | Path,
) -> Path:
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(asdict(table), indent=2, sort_keys=True), encoding="utf-8")
    return destination


def load_report_mapping_table(path: str | Path) -> ReportMappingTable:
    loaded = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError("Expected mapping table JSON object")

    instruments = [
        InstrumentMappingRow(
            symbol_key=str(row["symbol_key"]),
            venue=str(row["venue"]),
            display_ticker=str(row["display_ticker"]),
            display_name=str(row["display_name"]),
            category=str(row["category"]),
            risk_bucket=str(row["risk_bucket"]),
            instrument_type=str(row["instrument_type"]),
            multiplier=float(row["multiplier"]),
            duration=_optional_float(row.get("duration")),
            expected_vol=_optional_float(row.get("expected_vol")),
            quote_source=_load_live_data_source(row.get("quote_source")),
        )
        for row in loaded.get("instruments", [])
        if isinstance(row, dict)
    ]
    fx_sources = [
        FxSourceRow(
            currency_pair=str(row["currency_pair"]),
            provider=str(row["provider"]),
            symbol=str(row["symbol"]),
        )
        for row in loaded.get("fx_sources", [])
        if isinstance(row, dict)
    ]
    risk_proxies = [
        RiskProxySourceRow(
            risk_bucket=str(row["risk_bucket"]),
            provider=str(row["provider"]),
            symbol=str(row["symbol"]),
            proxy_name=str(row["proxy_name"]),
            unit=str(row.get("unit", "")),
            tail_level=_optional_float(row.get("tail_level")),
        )
        for row in loaded.get("risk_proxies", [])
        if isinstance(row, dict)
    ]
    return ReportMappingTable(
        source_workbook=str(loaded.get("source_workbook", "")),
        generated_at=str(loaded.get("generated_at", "")),
        ten_year_equiv_duration=float(
            loaded.get("ten_year_equiv_duration", DEFAULT_TEN_YEAR_EQUIV_DURATION)
        ),
        instruments=instruments,
        fx_sources=fx_sources,
        risk_proxies=risk_proxies,
    )


def build_instrument_mapping_indexes(
    table: ReportMappingTable,
) -> tuple[dict[tuple[str, str], InstrumentMappingRow], dict[str, InstrumentMappingRow]]:
    exact: dict[tuple[str, str], InstrumentMappingRow] = {}
    counts: dict[str, int] = {}
    last_seen: dict[str, InstrumentMappingRow] = {}

    for row in table.instruments:
        key = (row.symbol_key.upper(), row.venue.upper())
        exact[key] = row
        counts[row.symbol_key.upper()] = counts.get(row.symbol_key.upper(), 0) + 1
        last_seen[row.symbol_key.upper()] = row

    unique = {
        symbol_key: last_seen[symbol_key]
        for symbol_key, count in counts.items()
        if count == 1
    }
    return exact, unique


def normalize_mapping_venue(raw_exchange: str) -> str:
    exchange = raw_exchange.strip().upper()
    if exchange in FUTURES_VENUES:
        return exchange
    if exchange in {"LSEETF", "SBF", "LSE", "SWX"}:
        return "INTL"
    return "US"


def normalize_mapping_symbol(raw_symbol: str) -> str:
    symbol = raw_symbol.strip().upper()
    if not symbol:
        return symbol
    if ":" in symbol:
        left, right = symbol.split(":", 1)
        if right in FUTURES_VENUES:
            return _normalize_contract_root(left)
        if left in {"LON", "NYSE", "NASDAQ"}:
            return right
    return _normalize_contract_root(symbol)


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


def _load_live_data_source(value: object) -> LiveDataSource | None:
    if not isinstance(value, dict):
        return None
    provider = value.get("provider")
    symbol = value.get("symbol")
    if provider in (None, "") or symbol in (None, ""):
        return None
    return LiveDataSource(provider=str(provider), symbol=str(symbol))


def _extract_instrument_rows(
    rows: list[dict[str, WorkbookCell]],
) -> list[InstrumentMappingRow]:
    extracted: list[InstrumentMappingRow] = []

    for row in rows:
        category = _cell_value(row, "H")
        display_ticker = _cell_value(row, "I")
        display_name = _cell_value(row, "J")
        instrument_type = _cell_value(row, "O")
        if category in (None, "", "Category"):
            continue
        if display_ticker in (None, "", "Ticker"):
            continue
        if instrument_type in (None, "", "Type"):
            continue
        if str(display_ticker).startswith("CURRENCY:"):
            continue

        symbol_key = normalize_mapping_symbol(display_ticker)
        venue = _mapping_venue_for_ticker(display_ticker)
        quote_formula = _cell_formula(row, "M")
        extracted.append(
            InstrumentMappingRow(
                symbol_key=symbol_key,
                venue=venue,
                display_ticker=str(display_ticker),
                display_name=str(display_name or display_ticker),
                category=str(category),
                risk_bucket=risk_bucket_for_category(str(category)),
                instrument_type=str(instrument_type),
                multiplier=_optional_float(_cell_value(row, "L")) or 1.0,
                duration=_optional_float(_cell_value(row, "P")),
                expected_vol=_optional_float(_cell_value(row, "T")),
                quote_source=LiveDataSource(
                    provider=_provider_from_formula(quote_formula),
                    symbol=str(display_ticker),
                ),
            )
        )

    return extracted


def _extract_fx_sources(rows: list[dict[str, WorkbookCell]]) -> list[FxSourceRow]:
    extracted: list[FxSourceRow] = []

    for row in rows:
        symbol = _cell_value(row, "I")
        if symbol is None or not str(symbol).startswith("CURRENCY:"):
            continue
        currency_pair = str(symbol).split(":", 1)[1]
        extracted.append(
            FxSourceRow(
                currency_pair=currency_pair,
                provider=_provider_from_formula(_cell_formula(row, "J")),
                symbol=str(symbol),
            )
        )

    return extracted


def _extract_risk_proxy_sources(
    rows: list[dict[str, WorkbookCell]],
) -> list[RiskProxySourceRow]:
    extracted: list[RiskProxySourceRow] = []

    for row in rows:
        category = _cell_value(row, "A")
        symbol = _cell_value(row, "B")
        if category in (None, "", "Latest") or symbol in (None, ""):
            continue
        if ":" not in str(symbol):
            continue

        proxy_name = str(symbol).split(":", 1)[1]
        extracted.append(
            RiskProxySourceRow(
                risk_bucket=risk_bucket_for_category(str(category)),
                provider=_provider_from_formula(_cell_formula(row, "C")),
                symbol=str(symbol),
                proxy_name=proxy_name,
                unit=str(_cell_value(row, "J") or ""),
                tail_level=_optional_float(_cell_value(row, "I")),
            )
        )

    return extracted


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


def _mapping_venue_for_ticker(display_ticker: str) -> str:
    ticker = display_ticker.strip().upper()
    if ticker.startswith("LON:"):
        return "INTL"
    if ":" in ticker:
        _left, right = ticker.split(":", 1)
        if right in FUTURES_VENUES:
            return right
    return "US"


def _normalize_contract_root(symbol: str) -> str:
    upper = symbol.strip().upper()
    if "_" in upper:
        return upper
    if upper.endswith("W00") and len(upper) > 3:
        return upper[:-3]

    match = re.match(rf"^([A-Z0-9]+?)[{MONTH_CODES}]\d{{1,2}}$", upper)
    if match is not None:
        return match.group(1)
    return upper


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
