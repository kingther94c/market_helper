from __future__ import annotations

"""Pipeline entrypoints for portfolio-monitor reporting flows."""

import json
from pathlib import Path

from market_helper.common.models import (
    PortfolioPositionSnapshot,
    PortfolioPriceSnapshot,
    SecurityReference,
    SecurityReferenceTable,
    build_price_lookup,
)
from market_helper.data_sources.ibkr.adapters import (
    normalize_ibkr_latest_prices,
    normalize_ibkr_positions,
)
from market_helper.data_sources.ibkr.tws import (
    TwsIbAsyncClient,
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
    reference_table = SecurityReferenceTable.from_default_csv()
    raw_positions = _load_json_rows(ibkr_positions_path)
    raw_prices = _load_json_rows(ibkr_prices_path)
    positions = normalize_ibkr_positions(raw_positions, reference_table, as_of=as_of)
    prices = normalize_ibkr_latest_prices(raw_prices, reference_table, as_of=as_of)
    rows = build_position_report_rows(
        positions,
        build_price_lookup(prices),
        reference_table.to_security_lookup(),
    )
    return export_position_report_csv(rows, output_path)


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
        portfolio_items = _load_live_portfolio_items(live_client, account_id)
        _, rows, _ = _build_live_ibkr_report_rows(portfolio_items, as_of=as_of)
        return export_position_report_csv(rows, output_path)
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
        portfolio_items = _load_live_portfolio_items(live_client, account_id)
        raw_positions, report_rows, reference_table = _build_live_ibkr_report_rows(
            portfolio_items,
            as_of=as_of,
        )
        security_lookup = reference_table.to_security_lookup()
        return [
            _build_live_ibkr_position_security_row(
                raw_position=raw_position,
                report_row=report_row,
                security=security_lookup.get(report_row.internal_id),
                contract_details=_fetch_live_contract_details(live_client, portfolio_item),
            )
            for portfolio_item, raw_position, report_row in zip(
                portfolio_items,
                raw_positions,
                report_rows,
                strict=True,
            )
        ]
    finally:
        if callable(disconnect):
            disconnect()


def generate_risk_html_report(
    *,
    positions_csv_path: str | Path,
    returns_path: str | Path,
    output_path: str | Path,
    proxy_path: str | Path | None = None,
    regime_path: str | Path | None = None,
    security_reference_path: str | Path | None = None,
) -> Path:
    """Render the HTML risk report from a previously generated position CSV."""
    return build_risk_html_report(
        positions_csv_path=positions_csv_path,
        returns_path=returns_path,
        output_path=output_path,
        proxy_path=proxy_path,
        regime_path=regime_path,
        security_reference_path=security_reference_path,
    )


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


def _load_live_portfolio_items(
    live_client: object,
    account_id: str | None,
) -> list[object]:
    accounts = live_client.list_accounts()
    selected_account_id = choose_tws_account(accounts, account_id)
    return list(live_client.list_portfolio(selected_account_id))


def _build_live_ibkr_report_rows(
    portfolio_items: list[object],
    *,
    as_of: str | None,
) -> tuple[list[dict[str, object]], list[PositionReportRow], SecurityReferenceTable]:
    # Keep live normalization identical to the CSV/report pipeline so notebook
    # exploration and exported reports stay aligned.
    reference_table = SecurityReferenceTable.from_default_csv()
    raw_positions = portfolio_items_to_ibkr_position_rows(portfolio_items)
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
    rows = build_position_report_rows(
        positions,
        build_price_lookup(prices),
        reference_table.to_security_lookup(),
    )
    return raw_positions, rows, reference_table


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
            "security_universe_type": "",
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
            "security_google_symbol": "",
            "security_yahoo_symbol": "",
            "security_bbg_symbol": "",
            "security_report_category": "",
            "security_risk_bucket": "",
            "security_mod_duration": None,
            "security_default_expected_vol": None,
            "security_price_source_provider": "",
            "security_price_source_symbol": "",
            "security_fx_source_provider": "",
            "security_fx_source_symbol": "",
            "security_runtime_local_symbol": "",
        }

    return {
        "security_mapping_status": security.mapping_status,
        "security_is_active": security.is_active,
        "security_universe_type": security.universe_type,
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
        "security_google_symbol": security.google_symbol,
        "security_yahoo_symbol": security.yahoo_symbol,
        "security_bbg_symbol": security.bbg_symbol,
        "security_report_category": security.report_category,
        "security_risk_bucket": security.risk_bucket,
        "security_mod_duration": security.mod_duration,
        "security_default_expected_vol": security.default_expected_vol,
        "security_price_source_provider": security.price_source_provider,
        "security_price_source_symbol": security.price_source_symbol,
        "security_fx_source_provider": security.fx_source_provider,
        "security_fx_source_symbol": security.fx_source_symbol,
        "security_runtime_local_symbol": security.runtime_local_symbol,
    }


__all__ = [
    "build_live_ibkr_position_security_table",
    "generate_ibkr_position_report",
    "generate_live_ibkr_position_report",
    "generate_position_report",
    "generate_report_mapping_table",
    "generate_risk_html_report",
]
