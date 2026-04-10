import csv
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from market_helper.data_sources.yahoo_finance import YahooFinanceClient
from market_helper.workflows.generate_report import (
    generate_etf_sector_sync,
    generate_ibkr_flex_performance_report,
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
                "provider": "fmp",
                "daily_call_limit": 250,
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
            from market_helper.data_sources.fmp import FmpEtfSectorWeight

            return [
                FmpEtfSectorWeight(symbol="SOXX", sector="Technology", weight=0.8),
                FmpEtfSectorWeight(symbol="SOXX", sector="Financial Services", weight=0.2),
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


def test_generate_ibkr_flex_performance_report_fetches_statement_from_web_service(tmp_path: Path) -> None:
    output_dir = tmp_path / "outputs"
    xml_output_path = tmp_path / "downloaded_flex.xml"
    captured: dict[str, object] = {}

    class FakeFlexClient:
        def fetch_statement(
            self,
            query_id: str,
            *,
            poll_interval_seconds: float,
            max_attempts: int,
        ) -> str:
            captured["query_id"] = query_id
            captured["poll_interval_seconds"] = poll_interval_seconds
            captured["max_attempts"] = max_attempts
            return """
<FlexQueryResponse>
  <FlexStatements>
    <FlexStatement>
      <ChangeInNAV reportDate="2026-04-02" startingValue="100000" endingValue="101000" depositWithdrawal="0"/>
      <PerformanceSummary mtdMoneyWeightedUsdPnl="1000" mtdMoneyWeightedUsdReturn="0.01" />
    </FlexStatement>
  </FlexStatements>
</FlexQueryResponse>
""".strip()

    written_path = generate_ibkr_flex_performance_report(
        output_dir=output_dir,
        query_id="1462703",
        token="secret-token",
        xml_output_path=xml_output_path,
        poll_interval_seconds=2.5,
        max_attempts=4,
        client=FakeFlexClient(),
    )

    assert written_path.name == "performance_report_20260402.csv"
    assert xml_output_path.exists()
    assert "PerformanceSummary,MTD,money_weighted,USD,1000,0.01" in written_path.read_text(encoding="utf-8")
    assert captured == {
        "query_id": "1462703",
        "poll_interval_seconds": 2.5,
        "max_attempts": 4,
    }


def test_generate_ibkr_flex_performance_report_fills_usd_rows_from_yahoo_fx(tmp_path: Path) -> None:
    output_dir = tmp_path / "outputs"
    xml_path = tmp_path / "flex.xml"
    xml_path.write_text(
        """
<FlexQueryResponse>
  <FlexStatements>
    <FlexStatement toDate="20260407" whenGenerated="20260408;080634">
      <EquitySummaryInBase>
        <EquitySummaryByReportDateInBase currency="SGD" reportDate="20260307" total="95000" />
        <EquitySummaryByReportDateInBase currency="SGD" reportDate="20260331" total="100000" />
        <EquitySummaryByReportDateInBase currency="SGD" reportDate="20260407" total="110000" />
      </EquitySummaryInBase>
      <MTDYTDPerformanceSummary>
        <MTDYTDPerformanceSummaryUnderlying description="Total" mtmMTD="8000" mtmYTD="15000" />
      </MTDYTDPerformanceSummary>
    </FlexStatement>
  </FlexStatements>
</FlexQueryResponse>
""".strip(),
        encoding="utf-8",
    )

    def _epoch(raw: str) -> int:
        return int(datetime.strptime(raw, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp())

    yahoo_client = YahooFinanceClient(
        downloader=lambda _url: {
            "chart": {
                "result": [
                    {
                        "meta": {"currency": "SGD"},
                        "timestamp": [
                            _epoch("2026-03-07"),
                            _epoch("2026-03-31"),
                            _epoch("2026-04-07"),
                        ],
                        "indicators": {
                            "quote": [{"close": [1.30, 1.31, 1.32]}],
                            "adjclose": [{"adjclose": [1.30, 1.31, 1.32]}],
                        },
                    }
                ]
            }
        }
    )

    written_path = generate_ibkr_flex_performance_report(
        output_dir=output_dir,
        flex_xml_path=xml_path,
        yahoo_client=yahoo_client,
    )

    with written_path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    mtd_mwr_usd = [
        row
        for row in rows
        if row["horizon"] == "MTD" and row["weighting"] == "money_weighted" and row["currency"] == "USD"
    ][0]

    assert written_path.name == "performance_report_20260407.csv"
    assert mtd_mwr_usd["source_version"] == "MTDYTDPerformanceSummaryTotal+YahooFinanceFX"
    assert float(mtd_mwr_usd["dollar_pnl"]) == pytest.approx(8000.0 / 1.32)
    assert float(mtd_mwr_usd["return_pct"]) == pytest.approx((8000.0 / 1.32) / (100000.0 / 1.31))
