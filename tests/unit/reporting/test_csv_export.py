import csv

from market_helper.reporting import PositionReportRow, export_position_report_csv


def test_export_position_report_csv_writes_expected_headers_and_rows(tmp_path) -> None:
    output_path = tmp_path / "position_report.csv"
    rows = [
        PositionReportRow(
            as_of="2026-03-26T00:00:00+00:00",
            account="U12345",
            internal_id="SEC:SPY",
            source="ibkr",
            quantity=100,
            avg_cost=500.0,
            latest_price=510.0,
            market_value=51000.0,
            cost_basis=50000.0,
            unrealized_pnl=1000.0,
            weight=0.25,
        )
    ]

    written_path = export_position_report_csv(rows, output_path)

    assert written_path == output_path
    with output_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        loaded_rows = list(reader)

    assert loaded_rows == [
        {
            "as_of": "2026-03-26T00:00:00+00:00",
            "account": "U12345",
            "internal_id": "SEC:SPY",
            "source": "ibkr",
            "quantity": "100",
            "avg_cost": "500.0",
            "latest_price": "510.0",
            "market_value": "51000.0",
            "cost_basis": "50000.0",
            "unrealized_pnl": "1000.0",
            "weight": "0.25",
        }
    ]
