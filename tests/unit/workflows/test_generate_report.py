import csv
import json
from datetime import date, datetime, timezone
from pathlib import Path
import warnings

import pytest

import market_helper.domain.portfolio_monitor.pipelines.generate_portfolio_report as portfolio_report_pipeline
import market_helper.data_sources.ibkr.flex.performance as flex_performance_module
from market_helper.data_sources.yahoo_finance import YahooFinanceClient
from market_helper.domain.portfolio_monitor.services.performance_history import load_performance_history
from market_helper.workflows.generate_report import (
    backfill_ibkr_flex_full_years,
    generate_etf_sector_sync,
    generate_ibkr_flex_performance_report,
    generate_position_report,
    generate_report_mapping_table,
    refresh_current_year_latest_flex_xml,
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
            from_date,
            to_date,
            period,
            poll_interval_seconds: float,
            max_attempts: int,
        ) -> str:
            captured["query_id"] = query_id
            captured["from_date"] = from_date
            captured["to_date"] = to_date
            captured["period"] = period
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

    with pytest.warns(UserWarning, match="2020, 2021, 2022, 2023, 2024, 2025"):
        written_path = generate_ibkr_flex_performance_report(
            output_dir=output_dir,
            query_id="1462703",
            token="secret-token",
            from_date="2026-04-01",
            to_date="2026-04-02",
            xml_output_path=xml_output_path,
            poll_interval_seconds=2.5,
            max_attempts=4,
            client=FakeFlexClient(),
        )

    assert written_path.name == "performance_report_20260402.csv"
    assert xml_output_path.exists()
    with written_path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    mtd_mwr_usd = [
        row
        for row in rows
        if row["horizon"] == "MTD" and row["weighting"] == "money_weighted" and row["currency"] == "USD"
    ][0]
    assert mtd_mwr_usd["source_version"].startswith("PerformanceHistoryFeather")
    assert float(mtd_mwr_usd["dollar_pnl"]) == pytest.approx(1000.0)
    assert float(mtd_mwr_usd["return_pct"]) == pytest.approx(0.01)
    assert captured == {
        "query_id": "1462703",
        "from_date": "2026-04-01",
        "to_date": "2026-04-02",
        "period": None,
        "poll_interval_seconds": 2.5,
        "max_attempts": 4,
    }


def test_backfill_ibkr_flex_full_years_skips_existing_full_file_without_rechecking(tmp_path: Path) -> None:
    raw_dir = tmp_path / "outputs" / "raw"
    raw_dir.mkdir(parents=True)
    full_path = raw_dir / "ibkr_flex_2025_full.xml"
    full_path.write_text("not-even-xml", encoding="utf-8")

    class FakeFlexClient:
        def fetch_statement(self, *args, **kwargs) -> str:
            raise AssertionError("should not fetch when a trusted _full file already exists")

    records = backfill_ibkr_flex_full_years(
        output_dir=tmp_path / "outputs",
        query_id="1462703",
        token="secret-token",
        start_year=2025,
        end_year=2025,
        client=FakeFlexClient(),
    )

    assert len(records) == 1
    assert records[0].status == "skipped"
    assert records[0].target_path == full_path


def test_backfill_ibkr_flex_full_years_promotes_complete_nonfull_xml(tmp_path: Path) -> None:
    output_dir = tmp_path / "outputs"
    raw_dir = output_dir / "raw"
    raw_dir.mkdir(parents=True)
    candidate_path = raw_dir / "ibkr_flex_20260410_102343.xml"
    candidate_xml = """
<FlexQueryResponse>
  <FlexStatements>
    <FlexStatement accountId="U2935967" fromDate="20250101" toDate="20251231" whenGenerated="20260101;010101">
      <ChangeInNAV reportDate="2025-12-31" startingValue="100" endingValue="110" depositWithdrawal="0"/>
      <PerformanceSummary ytdMoneyWeightedUsdPnl="10" ytdMoneyWeightedUsdReturn="0.10" />
    </FlexStatement>
  </FlexStatements>
</FlexQueryResponse>
""".strip()
    candidate_path.write_text(candidate_xml, encoding="utf-8")

    class FakeFlexClient:
        def fetch_statement(self, *args, **kwargs) -> str:
            raise AssertionError("should promote an existing complete file before fetching")

    records = backfill_ibkr_flex_full_years(
        output_dir=output_dir,
        query_id="1462703",
        token="secret-token",
        start_year=2025,
        end_year=2025,
        client=FakeFlexClient(),
    )

    full_path = raw_dir / "ibkr_flex_2025_full.xml"
    assert len(records) == 1
    assert records[0].status == "promoted"
    assert records[0].source_file == candidate_path
    assert full_path.exists()
    assert full_path.read_text(encoding="utf-8") == candidate_xml


def test_refresh_current_year_latest_flex_xml_writes_latest_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(portfolio_report_pipeline, "_current_local_date", lambda: date(2026, 4, 10))
    captured: dict[str, object] = {}

    class FakeFlexClient:
        def fetch_statement(
            self,
            query_id: str,
            *,
            from_date,
            to_date,
            period=None,
            poll_interval_seconds: float,
            max_attempts: int,
        ) -> str:
            captured["query_id"] = query_id
            captured["from_date"] = from_date
            captured["to_date"] = to_date
            captured["period"] = period
            captured["poll_interval_seconds"] = poll_interval_seconds
            captured["max_attempts"] = max_attempts
            return """
<FlexQueryResponse>
  <FlexStatements>
    <FlexStatement accountId="U2935967" fromDate="20260101" toDate="20260410" whenGenerated="20260410;010101">
      <ChangeInNAV reportDate="2026-04-10" startingValue="100" endingValue="110" depositWithdrawal="0"/>
      <PerformanceSummary ytdMoneyWeightedUsdPnl="10" ytdMoneyWeightedUsdReturn="0.10" />
    </FlexStatement>
  </FlexStatements>
</FlexQueryResponse>
""".strip()

    record = refresh_current_year_latest_flex_xml(
        output_dir=tmp_path / "outputs",
        query_id="1462703",
        token="secret-token",
        client=FakeFlexClient(),
    )

    assert record.target_path.name == "ibkr_flex_2026_latest.xml"
    assert record.target_path.exists()
    assert captured == {
        "query_id": "1462703",
        "from_date": date(2026, 1, 1),
        "to_date": date(2026, 4, 10),
        "period": None,
        "poll_interval_seconds": 5.0,
        "max_attempts": 10,
    }


def test_generate_ibkr_flex_performance_report_default_live_flow_adds_previous_full_year(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    output_dir = tmp_path / "outputs"
    monkeypatch.setattr(portfolio_report_pipeline, "_current_local_date", lambda: date(2026, 4, 10))
    monkeypatch.setattr(portfolio_report_pipeline, "DEFAULT_IBKR_FLEX_ARCHIVE_START_YEAR", 2025)
    calls: list[dict[str, object]] = []

    class FakeFlexClient:
        def fetch_statement(
            self,
            query_id: str,
            *,
            from_date,
            to_date,
            period=None,
            poll_interval_seconds: float,
            max_attempts: int,
        ) -> str:
            calls.append(
                {
                    "query_id": query_id,
                    "from_date": from_date,
                    "to_date": to_date,
                    "period": period,
                    "poll_interval_seconds": poll_interval_seconds,
                    "max_attempts": max_attempts,
                }
            )
            if from_date == date(2025, 1, 1):
                return """
<FlexQueryResponse>
  <FlexStatements>
    <FlexStatement accountId="U2935967" fromDate="20250101" toDate="20251231" whenGenerated="20260101;010101">
      <ChangeInNAV reportDate="2025-12-31" startingValue="100" endingValue="120" depositWithdrawal="0"/>
      <PerformanceSummary ytdMoneyWeightedUsdPnl="20" ytdMoneyWeightedUsdReturn="0.20" ytdTimeWeightedUsdPnl="18" ytdTimeWeightedUsdReturn="0.18" />
    </FlexStatement>
  </FlexStatements>
</FlexQueryResponse>
""".strip()
            return """
<FlexQueryResponse>
  <FlexStatements>
    <FlexStatement accountId="U2935967" fromDate="20260101" toDate="20260410" whenGenerated="20260410;010101">
      <ChangeInNAV reportDate="2026-04-10" startingValue="200" endingValue="220" depositWithdrawal="0"/>
      <PerformanceSummary
        mtdMoneyWeightedUsdPnl="4"
        mtdMoneyWeightedUsdReturn="0.02"
        ytdMoneyWeightedUsdPnl="20"
        ytdMoneyWeightedUsdReturn="0.10"
        oneMonthMoneyWeightedUsdPnl="6"
        oneMonthMoneyWeightedUsdReturn="0.03"
        mtdTimeWeightedUsdPnl="4"
        mtdTimeWeightedUsdReturn="0.02"
        ytdTimeWeightedUsdPnl="18"
        ytdTimeWeightedUsdReturn="0.09"
        oneMonthTimeWeightedUsdPnl="5"
        oneMonthTimeWeightedUsdReturn="0.025"
      />
    </FlexStatement>
  </FlexStatements>
</FlexQueryResponse>
""".strip()

    with warnings.catch_warnings(record=True) as recorded:
        warnings.simplefilter("always")
        written_path = generate_ibkr_flex_performance_report(
            output_dir=output_dir,
            query_id="1462703",
            token="secret-token",
            client=FakeFlexClient(),
        )
    assert recorded == []

    assert written_path.name == "performance_report_20260410.csv"
    assert (output_dir / "raw" / "ibkr_flex_2025_full.xml").exists()
    assert (output_dir / "raw" / "ibkr_flex_2026_latest.xml").exists()
    history = load_performance_history(output_dir / "performance_history.feather")
    assert bool(history.iloc[-1]["is_final"]) is False

    with written_path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    horizons = [row["horizon"] for row in rows]
    assert "Y2025" in horizons
    assert horizons.index("Y2025") > horizons.index("1M")

    assert calls == [
        {
            "query_id": "1462703",
            "from_date": date(2025, 1, 1),
            "to_date": date(2025, 12, 31),
            "period": None,
            "poll_interval_seconds": 5.0,
            "max_attempts": 10,
        },
        {
            "query_id": "1462703",
            "from_date": date(2026, 1, 1),
            "to_date": date(2026, 4, 10),
            "period": None,
            "poll_interval_seconds": 5.0,
            "max_attempts": 10,
        },
    ]


def test_generate_ibkr_flex_performance_report_warns_when_historical_full_year_is_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output_dir = tmp_path / "outputs"
    xml_path = tmp_path / "current.xml"
    xml_path.write_text(
        """
<FlexQueryResponse>
  <FlexStatements>
    <FlexStatement accountId="U2935967" fromDate="20260101" toDate="20260410" whenGenerated="20260410;010101">
      <ChangeInNAV reportDate="2026-04-10" startingValue="200" endingValue="220" depositWithdrawal="0"/>
      <PerformanceSummary
        mtdMoneyWeightedUsdPnl="4"
        mtdMoneyWeightedUsdReturn="0.02"
        ytdMoneyWeightedUsdPnl="20"
        ytdMoneyWeightedUsdReturn="0.10"
        oneMonthMoneyWeightedUsdPnl="6"
        oneMonthMoneyWeightedUsdReturn="0.03"
        mtdTimeWeightedUsdPnl="4"
        mtdTimeWeightedUsdReturn="0.02"
        ytdTimeWeightedUsdPnl="18"
        ytdTimeWeightedUsdReturn="0.09"
        oneMonthTimeWeightedUsdPnl="5"
        oneMonthTimeWeightedUsdReturn="0.025"
      />
    </FlexStatement>
  </FlexStatements>
</FlexQueryResponse>
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.setattr(portfolio_report_pipeline, "DEFAULT_IBKR_FLEX_ARCHIVE_START_YEAR", 2025)

    with pytest.warns(UserWarning, match="2025"):
        generate_ibkr_flex_performance_report(
            output_dir=output_dir,
            flex_xml_path=xml_path,
        )


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

    flex_performance_module._YAHOO_FX_HISTORY_CACHE.clear()
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

    with pytest.warns(UserWarning, match="2020, 2021, 2022, 2023, 2024, 2025"):
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
