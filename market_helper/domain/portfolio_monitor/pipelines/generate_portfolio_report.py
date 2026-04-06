from __future__ import annotations

"""Pipeline entrypoints for portfolio-monitor reporting flows."""

from dataclasses import dataclass
import json
from pathlib import Path

from market_helper.common.models import (
    DEFAULT_SECURITY_REFERENCE_PATH,
    PortfolioPositionSnapshot,
    PortfolioPriceSnapshot,
    SecurityReference,
    SecurityMapping,
    SecurityReferenceTable,
    build_security_reference_table,
    build_price_lookup,
    export_security_reference_csv,
    export_security_universe_proposal_csv,
    sync_security_reference_csv,
)
from market_helper.data_sources.ibkr.adapters import (
    normalize_ibkr_latest_prices,
    normalize_ibkr_positions,
)
from market_helper.data_sources.ibkr.tws import (
    TwsIbAsyncClient,
    account_values_to_ibkr_cash_position_rows,
    choose_tws_account,
    portfolio_items_to_ibkr_position_rows,
    portfolio_items_to_ibkr_price_rows,
)
from market_helper.presentation.exporters.csv import export_position_report_csv
from market_helper.presentation.exporters.security_reference_seed import (
    export_security_reference_seed_csv,
    extract_security_reference_seed,
)
from market_helper.presentation.html.portfolio_risk_report import build_risk_html_report
from market_helper.presentation.tables.portfolio_report import (
    PositionReportRow,
    build_position_report_rows,
)
from market_helper.portfolio.ibkr import enrich_security_from_contract_details


@dataclass(frozen=True)
class LiveIbkrRowSource:
    raw_position: dict[str, object]
    portfolio_item: object | None = None


def generate_position_report(
    *,
    positions_path: str | Path,
    prices_path: str | Path,
    output_path: str | Path,
) -> Path:
    """Build a plain CSV report from already-normalized snapshots."""
    positions = _load_positions(positions_path)
    prices = _load_prices(prices_path)
    rows = build_position_report_rows(positions, build_price_lookup(prices))
    return export_position_report_csv(rows, output_path)


def generate_ibkr_position_report(
    *,
    ibkr_positions_path: str | Path,
    ibkr_prices_path: str | Path,
    output_path: str | Path,
    as_of: str | None = None,
) -> Path:
    """Normalize raw IBKR payload dumps, then render the standard report shape."""
    reference_table = build_security_reference_table(reference_path=DEFAULT_SECURITY_REFERENCE_PATH)
    raw_positions = _load_json_rows(ibkr_positions_path)
    raw_prices = _load_json_rows(ibkr_prices_path)
    positions = normalize_ibkr_positions(raw_positions, reference_table, as_of=as_of)
    prices = normalize_ibkr_latest_prices(raw_prices, reference_table, as_of=as_of)
    rows = build_position_report_rows(
        positions,
        build_price_lookup(prices),
        reference_table.to_security_lookup(),
    )
    written_path = export_position_report_csv(rows, output_path)
    _write_generated_security_reference_csv(reference_table)
    _write_proposed_security_universe_csv(reference_table, output_path=written_path)
    return written_path


def generate_live_ibkr_position_report(
    *,
    output_path: str | Path,
    host: str = "127.0.0.1",
    port: int = 7497,
    client_id: int = 1,
    account_id: str | None = None,
    timeout: float = 4.0,
    as_of: str | None = None,
    client: object | None = None,
) -> Path:
    """Pull live TWS portfolio data and route it through the same normalization path."""
    live_client = client or TwsIbAsyncClient(
        host=host,
        port=port,
        client_id=client_id,
        timeout=timeout,
        account=account_id or "",
    )
    connect = getattr(live_client, "connect")
    disconnect = getattr(live_client, "disconnect", None)
    connect()
    try:
        selected_account_id = _load_live_account_id(live_client, account_id)
        portfolio_items = _load_live_portfolio_items(live_client, selected_account_id)
        cash_values = _load_live_account_values(live_client, selected_account_id)
        sources, rows, reference_table = _build_live_ibkr_report_rows(
            portfolio_items,
            cash_values,
            as_of=as_of,
        )
        _refresh_live_security_lookups(
            reference_table=reference_table,
            live_client=live_client,
            sources=sources,
        )
        written_path = export_position_report_csv(rows, output_path)
        _write_generated_security_reference_csv(reference_table)
        _write_proposed_security_universe_csv(reference_table, output_path=written_path)
        return written_path
    finally:
        if callable(disconnect):
            disconnect()


def build_live_ibkr_position_security_table(
    *,
    host: str = "127.0.0.1",
    port: int = 7497,
    client_id: int = 1,
    account_id: str | None = None,
    timeout: float = 4.0,
    as_of: str | None = None,
    client: object | None = None,
) -> list[dict[str, object]]:
    """Pull live TWS positions and flatten position, reference, and contract detail data."""
    live_client = client or TwsIbAsyncClient(
        host=host,
        port=port,
        client_id=client_id,
        timeout=timeout,
        account=account_id or "",
    )
    connect = getattr(live_client, "connect")
    disconnect = getattr(live_client, "disconnect", None)
    connect()
    try:
        selected_account_id = _load_live_account_id(live_client, account_id)
        portfolio_items = _load_live_portfolio_items(live_client, selected_account_id)
        cash_values = _load_live_account_values(live_client, selected_account_id)
        sources, report_rows, reference_table = _build_live_ibkr_report_rows(
            portfolio_items,
            cash_values,
            as_of=as_of,
        )
        rows: list[dict[str, object]] = []
        for source, report_row in zip(sources, report_rows):
            contract_details: dict[str, object] = {}
            security = reference_table.get_security(report_row.internal_id)
            if source.portfolio_item is not None:
                contract_details = _fetch_live_contract_details(live_client, source.portfolio_item)
                security = _refresh_live_security_lookup(
                    reference_table=reference_table,
                    security=security,
                    portfolio_item=source.portfolio_item,
                    details=contract_details,
                )
            rows.append(
                _build_live_ibkr_position_security_row(
                raw_position=source.raw_position,
                report_row=report_row,
                security=security,
                contract_details=contract_details,
            )
            )
        return rows
    finally:
        if callable(disconnect):
            disconnect()


def generate_risk_html_report(
    *,
    positions_csv_path: str | Path,
    output_path: str | Path,
    returns_path: str | Path | None = None,
    proxy_path: str | Path | None = None,
    regime_path: str | Path | None = None,
    security_reference_path: str | Path | None = None,
) -> Path:
    """Render the HTML risk report from a previously generated position CSV."""
    reference_path = Path(security_reference_path) if security_reference_path is not None else DEFAULT_SECURITY_REFERENCE_PATH
    sync_security_reference_csv(reference_path=reference_path)
    return build_risk_html_report(
        positions_csv_path=positions_csv_path,
        output_path=output_path,
        returns_path=returns_path,
        proxy_path=proxy_path,
        regime_path=regime_path,
        security_reference_path=reference_path,
    )


def generate_security_reference_sync(
    *,
    output_path: str | Path | None = None,
) -> Path:
    return sync_security_reference_csv(reference_path=output_path or DEFAULT_SECURITY_REFERENCE_PATH)


def generate_report_mapping_table(
    *,
    workbook_path: str | Path,
    output_path: str | Path,
) -> Path:
    """Convert the workbook seed into the tracked security-reference CSV format."""
    table = extract_security_reference_seed(workbook_path)
    return export_security_reference_seed_csv(table, output_path)


def _load_positions(path: str | Path) -> list[PortfolioPositionSnapshot]:
    payload = _load_json_rows(path)
    return [
        PortfolioPositionSnapshot(
            as_of=str(row["as_of"]),
            account=str(row["account"]),
            internal_id=str(row["internal_id"]),
            source=str(row["source"]),
            quantity=float(row["quantity"]),
            avg_cost=_optional_float(row.get("avg_cost")),
            market_value=_optional_float(row.get("market_value")),
        )
        for row in payload
    ]


def _load_prices(path: str | Path) -> list[PortfolioPriceSnapshot]:
    payload = _load_json_rows(path)
    return [
        PortfolioPriceSnapshot(
            as_of=str(row["as_of"]),
            internal_id=str(row["internal_id"]),
            source=str(row["source"]),
            last_price=float(row["last_price"]),
        )
        for row in payload
    ]


def _load_json_rows(path: str | Path) -> list[dict[str, object]]:
    loaded = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(loaded, list):
        return [dict(row) for row in loaded]
    if isinstance(loaded, dict):
        # Keep accepting legacy wrapper shapes so notebook artifacts and older
        # fixtures do not all have to move in lockstep with the new pipelines.
        for key in ("rows", "positions", "prices", "data"):
            value = loaded.get(key)
            if isinstance(value, list):
                return [dict(row) for row in value]
    raise ValueError("Expected a JSON array of snapshot rows or a wrapper object containing one")


def _optional_float(value: object) -> float | None:
    if value in (None, ""):
        return None
    return float(value)


def _load_live_account_id(live_client: object, account_id: str | None) -> str:
    accounts = live_client.list_accounts()
    return choose_tws_account(accounts, account_id)


def _load_live_portfolio_items(
    live_client: object,
    account_id: str,
) -> list[object]:
    return list(live_client.list_portfolio(account_id))


def _load_live_account_values(
    live_client: object,
    account_id: str,
) -> list[object]:
    list_account_values = getattr(live_client, "list_account_values", None)
    if not callable(list_account_values):
        return []
    return list(list_account_values(account_id))


def _build_live_ibkr_report_rows(
    portfolio_items: list[object],
    cash_values: list[object],
    *,
    as_of: str | None,
) -> tuple[list[LiveIbkrRowSource], list[PositionReportRow], SecurityReferenceTable]:
    # Keep live normalization identical to the CSV/report pipeline so notebook
    # exploration and exported reports stay aligned.
    reference_table = build_security_reference_table(reference_path=DEFAULT_SECURITY_REFERENCE_PATH)
    sources = [
        LiveIbkrRowSource(raw_position=row, portfolio_item=item)
        for item, row in zip(
            portfolio_items,
            portfolio_items_to_ibkr_position_rows(portfolio_items),
        )
    ]
    sources.extend(
        LiveIbkrRowSource(raw_position=row)
        for row in account_values_to_ibkr_cash_position_rows(cash_values)
    )
    raw_positions = [source.raw_position for source in sources]
    positions = normalize_ibkr_positions(
        raw_positions,
        reference_table,
        as_of=as_of,
    )
    prices = normalize_ibkr_latest_prices(
        portfolio_items_to_ibkr_price_rows(portfolio_items),
        reference_table,
        as_of=as_of,
    )
    prices.extend(_build_live_cash_price_rows(positions, reference_table))
    rows = build_position_report_rows(
        positions,
        build_price_lookup(prices),
        reference_table.to_security_lookup(),
    )
    return sources, rows, reference_table


def _build_live_cash_price_rows(
    positions: list[PortfolioPositionSnapshot],
    reference_table: SecurityReferenceTable,
) -> list[PortfolioPriceSnapshot]:
    lookup = reference_table.to_security_lookup()
    rows: list[PortfolioPriceSnapshot] = []
    for position in positions:
        security = lookup.get(position.internal_id)
        if security is None or security.ibkr_sec_type != "CASH":
            continue
        rows.append(
            PortfolioPriceSnapshot(
                as_of=position.as_of,
                internal_id=position.internal_id,
                source=position.source,
                last_price=1.0,
            )
        )
    return rows


def _refresh_live_security_lookups(
    *,
    reference_table: SecurityReferenceTable,
    live_client: object,
    sources: list[LiveIbkrRowSource],
) -> None:
    if not _supports_live_contract_lookup(live_client):
        return
    for source in sources:
        portfolio_item = source.portfolio_item
        if portfolio_item is None:
            continue
        contract = getattr(portfolio_item, "contract", None)
        con_id = getattr(contract, "conId", None)
        if con_id in (None, ""):
            continue
        internal_id = reference_table.resolve_internal_id("ibkr", str(con_id))
        if internal_id is None:
            continue
        security = reference_table.get_security(internal_id)
        if security is None or security.mapping_status == "outside_scope":
            continue
        details = _fetch_live_contract_details(live_client, portfolio_item)
        _refresh_live_security_lookup(
            reference_table=reference_table,
            security=security,
            portfolio_item=portfolio_item,
            details=details,
        )


def _supports_live_contract_lookup(live_client: object) -> bool:
    return callable(getattr(live_client, "lookup_security", None)) or callable(
        getattr(live_client, "require_security_info", None)
    )


def _refresh_live_security_lookup(
    *,
    reference_table: SecurityReferenceTable,
    security: SecurityReference | None,
    portfolio_item: object,
    details: dict[str, object],
) -> SecurityReference | None:
    if security is None or security.mapping_status == "outside_scope":
        return security

    contract = getattr(portfolio_item, "contract", None)
    con_id = str(
        details.get("conId")
        or getattr(contract, "conId", "")
        or security.ibkr_conid
    )
    if not con_id:
        return security

    if security.mapping_status == "unmapped":
        remapped_security = reference_table.resolve_runtime_contract_match(
            symbol=str(
                details.get("symbol")
                or getattr(contract, "symbol", "")
                or security.ibkr_symbol
                or security.symbol
            ).upper(),
            sec_type=str(
                details.get("secType")
                or getattr(contract, "secType", "")
                or security.ibkr_sec_type
            ).upper(),
            exchange=str(
                details.get("exchange")
                or getattr(contract, "exchange", "")
                or security.exchange
            ).upper(),
            primary_exchange=str(
                details.get("primaryExchange")
                or details.get("exchange")
                or getattr(contract, "primaryExchange", "")
                or security.primary_exchange
            ).upper(),
            exclude_internal_ids={security.internal_id},
        )
        if remapped_security is not None:
            reference_table.remove_security(security.internal_id)
            reference_table.register_runtime_contract(
                security=remapped_security,
                con_id=con_id,
                symbol=str(
                    details.get("symbol")
                    or getattr(contract, "symbol", "")
                    or remapped_security.ibkr_symbol
                    or remapped_security.symbol
                ).upper(),
                exchange=str(
                    details.get("exchange")
                    or getattr(contract, "exchange", "")
                    or remapped_security.exchange
                    or remapped_security.primary_exchange
                    or remapped_security.ibkr_exchange
                ).upper(),
                primary_exchange=str(
                    details.get("primaryExchange")
                    or details.get("exchange")
                    or getattr(contract, "primaryExchange", "")
                    or remapped_security.primary_exchange
                    or remapped_security.ibkr_exchange
                ).upper(),
                local_symbol=str(
                    details.get("localSymbol")
                    or getattr(contract, "localSymbol", "")
                    or remapped_security.runtime_local_symbol
                    or remapped_security.symbol
                ),
                sec_type=str(
                    details.get("secType")
                    or getattr(contract, "secType", "")
                    or remapped_security.ibkr_sec_type
                ).upper(),
                currency=str(
                    details.get("currency")
                    or getattr(contract, "currency", "")
                    or remapped_security.currency
                ).upper(),
                multiplier=_optional_float(
                    details.get("multiplier")
                    or getattr(contract, "multiplier", None)
                ),
            )
            return reference_table.get_security(remapped_security.internal_id)
        enriched = enrich_security_from_contract_details(security, details)
        reference_table.upsert_security(enriched)
        reference_table.upsert_mapping(
            SecurityMapping(
                source="ibkr",
                external_id=con_id,
                internal_id=enriched.internal_id,
            )
        )
        return enriched

    symbol = str(
        details.get("symbol")
        or getattr(contract, "symbol", "")
        or security.ibkr_symbol
        or security.symbol
    ).upper()
    exchange = str(
        details.get("exchange")
        or getattr(contract, "exchange", "")
        or security.exchange
        or security.primary_exchange
        or security.ibkr_exchange
    ).upper()
    primary_exchange = str(
        details.get("primaryExchange")
        or details.get("exchange")
        or getattr(contract, "primaryExchange", "")
        or exchange
        or security.primary_exchange
    ).upper()
    local_symbol = str(
        details.get("localSymbol")
        or getattr(contract, "localSymbol", "")
        or security.runtime_local_symbol
        or security.symbol
    )
    sec_type = str(
        details.get("secType")
        or getattr(contract, "secType", "")
        or security.ibkr_sec_type
    ).upper()
    currency = str(
        details.get("currency")
        or getattr(contract, "currency", "")
        or security.currency
    ).upper()
    multiplier = _optional_float(
        details.get("multiplier")
        or getattr(contract, "multiplier", None)
    )
    reference_table.register_runtime_contract(
        security=security,
        con_id=con_id,
        symbol=symbol,
        exchange=exchange,
        primary_exchange=primary_exchange,
        local_symbol=local_symbol,
        sec_type=sec_type,
        currency=currency,
        multiplier=multiplier,
    )
    return reference_table.get_security(security.internal_id)


def _write_generated_security_reference_csv(
    reference_table: SecurityReferenceTable,
) -> Path:
    return export_security_reference_csv(
        reference_table.to_rows(),
        DEFAULT_SECURITY_REFERENCE_PATH,
    )


def _write_proposed_security_universe_csv(
    reference_table: SecurityReferenceTable,
    *,
    output_path: str | Path,
) -> Path | None:
    proposed_rows = reference_table.to_universe_proposal_rows()
    if not proposed_rows:
        return None

    proposed_path = Path(output_path).with_name("security_universe_PROPOSED.csv")
    export_security_universe_proposal_csv(proposed_rows, proposed_path)
    print(
        "Universe gaps were normalized with runtime contract info. "
        "Review {path} ({count} rows) and merge any approved rows into configs/security_universe.csv.".format(
            path=proposed_path,
            count=len(proposed_rows),
        )
    )
    return proposed_path


def _fetch_live_contract_details(
    live_client: object,
    portfolio_item: object,
) -> dict[str, object]:
    contract = getattr(portfolio_item, "contract", None)
    if contract is None:
        raise AttributeError("TWS portfolio item is missing contract; cannot fetch IBKR contract details.")

    lookup_security = getattr(live_client, "lookup_security", None)
    if callable(lookup_security):
        details = lookup_security(contract=contract)
        return dict(details)

    require_security_info = getattr(live_client, "require_security_info", None)
    if not callable(require_security_info):
        raise AttributeError(
            "Live TWS client must expose lookup_security() for contract enrichment."
        )

    details = require_security_info(contract=contract)
    return dict(details)


def _build_live_ibkr_position_security_row(
    *,
    raw_position: dict[str, object],
    report_row: PositionReportRow,
    security: SecurityReference | None,
    contract_details: dict[str, object],
) -> dict[str, object]:
    runtime_local_symbol = (
        raw_position.get("localSymbol")
        or contract_details.get("localSymbol")
        or report_row.local_symbol
    )
    row = {
        "as_of": report_row.as_of,
        "account": report_row.account,
        "internal_id": report_row.internal_id,
        "con_id": report_row.con_id,
        "symbol": report_row.symbol,
        "local_symbol": runtime_local_symbol,
        "exchange": report_row.exchange,
        "currency": report_row.currency,
        "source": report_row.source,
        "quantity": report_row.quantity,
        "avg_cost": report_row.avg_cost,
        "latest_price": report_row.latest_price,
        "market_value": report_row.market_value,
        "cost_basis": report_row.cost_basis,
        "unrealized_pnl": report_row.unrealized_pnl,
        "weight": report_row.weight,
        "ibkr_conid": raw_position.get("conId"),
        "ibkr_sec_type": raw_position.get("secType"),
        "ibkr_symbol": raw_position.get("symbol"),
        "ibkr_currency": raw_position.get("currency"),
        "ibkr_exchange": raw_position.get("exchange"),
        "ibkr_local_symbol": raw_position.get("localSymbol"),
        "ibkr_multiplier": raw_position.get("multiplier"),
        "ibkr_position": raw_position.get("position"),
        "ibkr_avg_cost": raw_position.get("avgCost"),
        "ibkr_market_value": raw_position.get("marketValue"),
        "ibkr_cash_tag": raw_position.get("cashTag"),
        "ibkr_cash_target_currency": raw_position.get("cashTargetCurrency"),
        "ibkr_cash_source_currencies": raw_position.get("cashSourceCurrencies"),
        "ibkr_cash_conversion_mode": raw_position.get("cashConversionMode"),
        "contract_conid": contract_details.get("conId"),
        "contract_symbol": contract_details.get("symbol"),
        "contract_sec_type": contract_details.get("secType"),
        "contract_currency": contract_details.get("currency"),
        "contract_exchange": contract_details.get("exchange"),
        "contract_primary_exchange": contract_details.get("primaryExchange"),
        "contract_local_symbol": contract_details.get("localSymbol"),
        "contract_market_name": contract_details.get("marketName"),
        "contract_min_tick": contract_details.get("minTick"),
        "contract_price_magnifier": contract_details.get("priceMagnifier"),
        "contract_order_types": contract_details.get("orderTypes"),
        "contract_valid_exchanges": contract_details.get("validExchanges"),
        "contract_trading_hours": contract_details.get("tradingHours"),
        "contract_liquid_hours": contract_details.get("liquidHours"),
        "contract_long_name": contract_details.get("longName"),
        "contract_industry": contract_details.get("industry"),
        "contract_category": contract_details.get("category"),
        "contract_subcategory": contract_details.get("subcategory"),
    }
    row.update(_security_enrichment_fields(security))
    row["security_runtime_local_symbol"] = row["security_runtime_local_symbol"] or runtime_local_symbol
    return row


def _security_enrichment_fields(
    security: SecurityReference | None,
) -> dict[str, object]:
    if security is None:
        return {
            "security_mapping_status": "",
            "security_is_active": None,
            "security_asset_class": "",
            "security_canonical_symbol": "",
            "security_display_ticker": "",
            "security_display_name": "",
            "security_symbol": "",
            "security_currency": "",
            "security_exchange": "",
            "security_primary_exchange": "",
            "security_description": "",
            "security_multiplier": None,
            "security_ibkr_sec_type": "",
            "security_ibkr_symbol": "",
            "security_ibkr_exchange": "",
            "security_ibkr_conid": "",
            "security_yahoo_symbol": "",
            "security_eq_country": "",
            "security_eq_sector": "",
            "security_dir_exposure": "",
            "security_mod_duration": None,
            "security_fi_tenor": "",
            "security_lookup_status": "",
            "security_last_verified_at": "",
            "security_runtime_local_symbol": "",
        }

    return {
        "security_mapping_status": security.mapping_status,
        "security_is_active": security.is_active,
        "security_asset_class": security.asset_class,
        "security_canonical_symbol": security.canonical_symbol,
        "security_display_ticker": security.display_ticker,
        "security_display_name": security.display_name,
        "security_symbol": security.symbol,
        "security_currency": security.currency,
        "security_exchange": security.exchange,
        "security_primary_exchange": security.primary_exchange,
        "security_description": security.description,
        "security_multiplier": security.multiplier,
        "security_ibkr_sec_type": security.ibkr_sec_type,
        "security_ibkr_symbol": security.ibkr_symbol,
        "security_ibkr_exchange": security.ibkr_exchange,
        "security_ibkr_conid": security.ibkr_conid,
        "security_yahoo_symbol": security.yahoo_symbol,
        "security_eq_country": security.eq_country,
        "security_eq_sector": security.eq_sector,
        "security_dir_exposure": security.dir_exposure,
        "security_mod_duration": security.mod_duration,
        "security_fi_tenor": security.fi_tenor,
        "security_lookup_status": security.lookup_status,
        "security_last_verified_at": security.last_verified_at,
        "security_runtime_local_symbol": security.runtime_local_symbol,
    }


__all__ = [
    "build_live_ibkr_position_security_table",
    "generate_ibkr_position_report",
    "generate_live_ibkr_position_report",
    "generate_position_report",
    "generate_report_mapping_table",
    "generate_risk_html_report",
    "generate_security_reference_sync",
]
