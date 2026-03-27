from __future__ import annotations

import json
from pathlib import Path

from market_helper.portfolio import (
    PriceSnapshot,
    PositionSnapshot,
    SecurityReferenceTable,
    build_price_lookup,
    normalize_ibkr_latest_prices,
    normalize_ibkr_positions,
)
from market_helper.providers.tws_ib_async import (
    TwsIbAsyncClient,
    choose_tws_account,
    portfolio_items_to_ibkr_position_rows,
    portfolio_items_to_ibkr_price_rows,
)
from market_helper.reporting import (
    build_position_report_rows,
    build_risk_html_report,
    export_position_report_csv,
)


def generate_position_report(
    *,
    positions_path: str | Path,
    prices_path: str | Path,
    output_path: str | Path,
) -> Path:
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
    reference_table = SecurityReferenceTable()
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

        reference_table = SecurityReferenceTable()
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
    duration_path: str | Path | None = None,
    futures_dv01_path: str | Path | None = None,
    strict_futures_dv01: bool = False,
) -> Path:
    return build_risk_html_report(
        positions_csv_path=positions_csv_path,
        returns_path=returns_path,
        output_path=output_path,
        proxy_path=proxy_path,
        duration_path=duration_path,
        futures_dv01_path=futures_dv01_path,
        strict_futures_dv01=strict_futures_dv01,
    )

def _load_positions(path: str | Path) -> list[PositionSnapshot]:
    payload = _load_json_rows(path)
    return [
        PositionSnapshot(
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


def _load_prices(path: str | Path) -> list[PriceSnapshot]:
    payload = _load_json_rows(path)
    return [
        PriceSnapshot(
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
        for key in ("rows", "positions", "prices", "data"):
            value = loaded.get(key)
            if isinstance(value, list):
                return [dict(row) for row in value]
    raise ValueError("Expected a JSON array of snapshot rows or a wrapper object containing one")


def _optional_float(value: object) -> float | None:
    if value in (None, ""):
        return None
    return float(value)
