import csv
import json
from pathlib import Path

from market_helper.workflows.generate_report import (
    generate_etf_sector_sync,
    generate_position_report,
    generate_report_mapping_table,
)
from tests.helpers.target_report_workbook import write_target_report_workbook


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


def test_generate_report_mapping_table_reads_workbook_and_writes_csv(tmp_path: Path) -> None:
    workbook_path = write_target_report_workbook(tmp_path / "target_report.xlsx")
    output_path = tmp_path / "outputs" / "target_report_security_reference.csv"

    written_path = generate_report_mapping_table(
        workbook_path=workbook_path,
        output_path=output_path,
    )

    assert written_path == output_path
    with output_path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))

    assert any(row["display_ticker"] == "LON:SPYL" for row in rows)
    assert any(row["display_ticker"] == "ZNW00:CBOT" for row in rows)


def test_generate_etf_sector_sync_updates_json_lookthrough_store(tmp_path: Path) -> None:
    output_path = tmp_path / "us_sector_lookthrough.json"
    output_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "provider": "alpha_vantage",
                "daily_call_limit": 25,
                "api_usage": {"date": "", "count": 0},
                "symbols": {
                    "SPY": {
                        "updated_at": "2000-01-01",
                        "status": "ok",
                        "error_message": "",
                        "sectors": [{"sector": "Technology", "weight": 0.31}],
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    class FakeClient:
        def fetch_etf_sector_weightings(self, symbol: str):
            assert symbol == "SOXX"
            from market_helper.data_sources.alpha_vantage import (
                AlphaVantageEtfSectorWeight,
            )

            return [
                AlphaVantageEtfSectorWeight(
                    symbol="SOXX",
                    sector="INFORMATION TECHNOLOGY",
                    weight=0.8,
                ),
                AlphaVantageEtfSectorWeight(
                    symbol="SOXX",
                    sector="FINANCIALS",
                    weight=0.2,
                ),
            ]

    written_path = generate_etf_sector_sync(
        symbols=["SOXX"],
        output_path=output_path,
        client=FakeClient(),
    )

    assert written_path == output_path
    payload = json.loads(output_path.read_text(encoding="utf-8"))

    assert payload["symbols"]["SPY"]["sectors"] == [{"sector": "Technology", "weight": 0.31}]
    assert payload["symbols"]["SOXX"]["sectors"] == [
        {"sector": "Technology", "weight": 0.8},
        {"sector": "Financials", "weight": 0.2},
    ]
    assert payload["symbols"]["SOXX"]["status"] == "ok"
