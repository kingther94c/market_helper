import csv
import json
from pathlib import Path

from market_helper.workflows.generate_report import (
    generate_position_report,
    generate_report_mapping_table,
)


def test_generate_position_report_reads_json_and_writes_csv(tmp_path) -> None:
    positions_path = tmp_path / "positions.json"
    prices_path = tmp_path / "prices.json"
    output_path = tmp_path / "outputs" / "position_report.csv"

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

    written_path = generate_position_report(
        positions_path=positions_path,
        prices_path=prices_path,
        output_path=output_path,
    )

    assert written_path == output_path
    with output_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)

    assert len(rows) == 1
    assert rows[0]["internal_id"] == "SEC:SPY"
    assert rows[0]["symbol"] == ""
    assert rows[0]["unrealized_pnl"] == "1000.0"


def test_generate_report_mapping_table_reads_workbook_and_writes_json(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[3]
    workbook_path = repo_root / "outputs" / "reports" / "target_report.xlsx"
    output_path = tmp_path / "outputs" / "target_report_mapping.json"

    written_path = generate_report_mapping_table(
        workbook_path=workbook_path,
        output_path=output_path,
    )

    assert written_path == output_path
    loaded = json.loads(output_path.read_text(encoding="utf-8"))
    assert loaded["source_workbook"].endswith("target_report.xlsx")
    assert any(row["display_ticker"] == "LON:SPYL" for row in loaded["instruments"])
