from __future__ import annotations

"""Pipeline entrypoints for portfolio-monitor reporting flows."""

import json
from pathlib import Path

from market_helper.common.models import (
    PortfolioPositionSnapshot,
    PortfolioPriceSnapshot,
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
from market_helper.presentation.tables.portfolio_report import build_position_report_rows


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
        accounts = live_client.list_accounts()
        selected_account_id = choose_tws_account(accounts, account_id)
        portfolio_items = live_client.list_portfolio(selected_account_id)

        # The report pipeline always works from normalized snapshots so that
        # live, raw JSON, and local-file workflows stay behaviorally aligned.
        reference_table = SecurityReferenceTable.from_default_csv()
        positions = normalize_ibkr_positions(
            portfolio_items_to_ibkr_position_rows(portfolio_items),
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
        return export_position_report_csv(rows, output_path)
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


__all__ = [
    "generate_ibkr_position_report",
    "generate_live_ibkr_position_report",
    "generate_position_report",
    "generate_report_mapping_table",
    "generate_risk_html_report",
]
