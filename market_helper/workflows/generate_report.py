from __future__ import annotations

import json
from pathlib import Path

from market_helper.portfolio import (
    ClientPortalClient,
    PriceSnapshot,
    PositionSnapshot,
    SecurityReferenceTable,
    build_price_lookup,
    choose_account,
    ensure_authenticated_session,
    normalize_ibkr_latest_prices,
    normalize_ibkr_positions,
    position_rows_to_price_rows,
)
from market_helper.reporting import build_position_report_rows, export_position_report_csv


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
    rows = build_position_report_rows(positions, build_price_lookup(prices))
    return export_position_report_csv(rows, output_path)


def generate_live_ibkr_position_report(
    *,
    output_path: str | Path,
    base_url: str = "https://localhost:5000/v1/api",
    account_id: str | None = None,
    verify_ssl: bool = False,
    as_of: str | None = None,
    client: ClientPortalClient | None = None,
) -> Path:
    live_client = client or ClientPortalClient(base_url=base_url, verify_ssl=verify_ssl)
    ensure_authenticated_session(live_client)
    live_client.tickle()

    accounts = live_client.list_accounts()
    selected_account_id = choose_account(accounts, account_id)
    raw_positions = live_client.list_positions(selected_account_id)

    reference_table = SecurityReferenceTable()
    positions = normalize_ibkr_positions(raw_positions, reference_table, as_of=as_of)
    prices = normalize_ibkr_latest_prices(
        position_rows_to_price_rows(raw_positions),
        reference_table,
        as_of=as_of,
    )
    rows = build_position_report_rows(positions, build_price_lookup(prices))
    return export_position_report_csv(rows, output_path)


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
