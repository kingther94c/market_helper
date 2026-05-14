from __future__ import annotations

import csv
from dataclasses import asdict
from pathlib import Path
from typing import Iterable

from .tables import PositionReportRow


POSITION_REPORT_HEADERS = [
    "as_of",
    "account",
    "internal_id",
    "con_id",
    "symbol",
    "local_symbol",
    "exchange",
    "currency",
    "source",
    "quantity",
    "avg_cost",
    "latest_price",
    "market_value",
    "cost_basis",
    "unrealized_pnl",
    "weight",
    "option_delta",
    "option_underlying_price",
    "option_delta_exposure_usd",
    "option_implied_vol",
    "option_greeks_source",
    "option_greeks_status",
    "option_underlying_symbol",
    "option_underlying_internal_id",
]


def export_position_report_csv(
    rows: Iterable[PositionReportRow],
    path: str | Path,
) -> Path:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=POSITION_REPORT_HEADERS)
        writer.writeheader()
        for row in rows:
            writer.writerow(asdict(row))

    return output_path
