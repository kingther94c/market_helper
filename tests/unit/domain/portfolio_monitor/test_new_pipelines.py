import csv
import json

from market_helper.domain.portfolio_monitor.pipelines.generate_portfolio_report import (
    generate_position_report,
)


def test_generate_position_report_pipeline_writes_csv(tmp_path) -> None:
    positions_path = tmp_path / "positions.json"
    prices_path = tmp_path / "prices.json"
    output_path = tmp_path / "position_report.csv"

    positions_path.write_text(
        json.dumps(
            [
                {
                    "as_of": "2026-03-26T00:00:00+00:00",
                    "account": "U12345",
                    "internal_id": "SEC:SPY",
                    "source": "ibkr",
                    "quantity": 100,
                    "avg_cost": 500.0,
                    "market_value": 51000.0,
                }
            ]
        ),
        encoding="utf-8",
    )
    prices_path.write_text(
        json.dumps(
            [
                {
                    "as_of": "2026-03-26T00:00:00+00:00",
                    "internal_id": "SEC:SPY",
                    "source": "ibkr",
                    "last_price": 510.0,
                }
            ]
        ),
        encoding="utf-8",
    )

    generate_position_report(
        positions_path=positions_path,
        prices_path=prices_path,
        output_path=output_path,
    )

    with output_path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))

    assert rows[0]["internal_id"] == "SEC:SPY"
