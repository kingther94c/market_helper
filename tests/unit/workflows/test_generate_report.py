import csv
import json
from datetime import date, datetime, timezone
from pathlib import Path
import warnings

import pytest

from market_helper.common.progress import RecordingProgressReporter
import market_helper.domain.portfolio_monitor.pipelines.generate_portfolio_report as portfolio_report_pipeline
import market_helper.data_sources.ibkr.flex.performance as flex_performance_module
from market_helper.data_sources.yahoo_finance import YahooFinanceClient
from market_helper.domain.portfolio_monitor.services.nav_cashflow_history import load_nav_cashflow_history
from market_helper.providers.flex import FlexWebServicePendingError
from market_helper.workflows.generate_report import (
    FlexBackfillBatchError,
    backfill_ibkr_flex_full_years,
    generate_etf_sector_sync,
    generate_ibkr_flex_performance_report,
    generate_position_report,
    generate_report_mapping_table,
    refresh_current_year_latest_flex_xml,
)
from tests.helpers.target_report_workbook import write_target_report_workbook


def _full_year_flex_xml(year: int) -> str:
    return f"""
<FlexQueryResponse>
  <FlexStatements>
    <FlexStatement accountId="U2935967" fromDate="{year}0101" toDate="{year}1231" whenGenerated="{year + 1}0101;010101">
      <ChangeInNAV reportDate="{year}-12-31" startingValue="100" endingValue="110" depositWithdrawal="0"/>
      <PerformanceSummary ytdMoneyWeightedUsdPnl="10" ytdMoneyWeightedUsdReturn="0.10" />
    </FlexStatement>
  </FlexStatements>
</FlexQueryResponse>
""".strip()


def _fake_yahoo_client(levels: list[tuple[str, float]]) -> YahooFinanceClient:
    def _epoch(raw: str) -> int:
        return int(datetime.strptime(raw, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp())

    flex_performance_module._YAHOO_FX_HISTORY_CACHE.clear()
    return YahooFinanceClient(
        downloader=lambda _url: {
            "chart": {
                "result": [
                    {
                        "meta": {"currency": "SGD"},
                        "timestamp": [_epoch(raw_date) for raw_date, _ in levels],
                        "indicators": {
                            "quote": [{"close": [level for _, level in levels]}],
                            "adjclose": [{"adjclose": [level for _, level in levels]}],
                        },
                    }
                ]
            }
        }
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
                "daily_call_limit": 20,
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
            from market_helper.data_sources.alpha_vantage import AlphaVantageEtfSectorWeight

            return [
                AlphaVantageEtfSectorWeight(symbol="SOXX", sector="Technology", weight=0.8),
                AlphaVantageEtfSectorWeight(symbol="SOXX", sector="Financial Services", weight=0.2),
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


def test_generate_etf_sector_sync_reports_progress(tmp_path: Path) -> None:
    output_path = tmp_path / "us_sector_lookthrough.json"
    output_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "provider": "alpha_vantage",
                "daily_call_limit": 20,
                "api_usage": {"date": "", "count": 0},
                "symbols": {},
            }
        ),
        encoding="utf-8",
    )
    reporter = RecordingProgressReporter()

    class FakeClient:
        def fetch_etf_sector_weightings(self, symbol: str):
            from market_helper.data_sources.alpha_vantage import AlphaVantageEtfSectorWeight

            return [AlphaVantageEtfSectorWeight(symbol=symbol, sector="Technology", weight=1.0)]

    generate_etf_sector_sync(
        symbols=["SOXX", "QQQ"],
        output_path=output_path,
        client=FakeClient(),
        progress=reporter,
    )

    assert reporter.events == [
        {"kind": "stage", "label": "ETF sector sync", "current": 0, "total": 2},
        {
            "kind": "update",
            "label": "ETF sector sync",
            "completed": 1,
            "total": 2,
            "detail": "QQQ ok",
        },
        {
            "kind": "update",
            "label": "ETF sector sync",
            "completed": 2,
            "total": 2,
            "detail": "SOXX ok",
        },
    ]


def test_previous_weekday_steps_back_one_business_day() -> None:
    assert portfolio_report_pipeline._previous_weekday(date(2026, 4, 21)) == date(2026, 4, 20)


def test_previous_weekday_skips_weekend_from_monday() -> None:
    assert portfolio_report_pipeline._previous_weekday(date(2026, 4, 20)) == date(2026, 4, 17)


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
            yahoo_client=_fake_yahoo_client([("2026-04-02", 1.30)]),
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
    assert mtd_mwr_usd["source_version"].startswith("PerformanceSummary")
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


def test_backfill_ibkr_flex_full_years_batches_up_to_three_requests_and_polls_round_robin(tmp_path: Path) -> None:
    events: list[str] = []
    sleeps: list[float] = []

    class FakeFlexClient:
        def __init__(self) -> None:
            self.reference_to_year: dict[str, int] = {}
            self.poll_outcomes = {
                2022: ["success"],
                2023: ["pending", "success"],
                2024: ["pending", "success"],
                2025: ["success"],
            }

        def send_request(self, query_id: str, *, from_date, to_date, period=None) -> str:
            assert query_id == "1462703"
            assert period is None
            assert from_date == date(from_date.year, 1, 1)
            assert to_date == date(from_date.year, 12, 31)
            events.append(f"send:{from_date.year}")
            reference_code = f"ref-{from_date.year}"
            self.reference_to_year[reference_code] = from_date.year
            return reference_code

        def get_statement(self, reference_code: str) -> str:
            year = self.reference_to_year[reference_code]
            events.append(f"get:{year}")
            outcome = self.poll_outcomes[year].pop(0)
            if outcome == "pending":
                raise FlexWebServicePendingError(f"{year} pending")
            return _full_year_flex_xml(year)

        def sleep(self, seconds: float) -> None:
            sleeps.append(seconds)
            events.append(f"sleep:{seconds}")

    records = backfill_ibkr_flex_full_years(
        output_dir=tmp_path / "outputs",
        query_id="1462703",
        token="secret-token",
        start_year=2022,
        end_year=2025,
        poll_interval_seconds=1.5,
        max_attempts=3,
        max_inflight_requests=3,
        client=FakeFlexClient(),
    )

    assert [record.year for record in records] == [2022, 2023, 2024, 2025]
    assert [record.status for record in records] == ["downloaded", "downloaded", "downloaded", "downloaded"]
    assert events[:7] == ["send:2022", "send:2023", "send:2024", "get:2022", "get:2023", "get:2024", "send:2025"]
    assert events[7:] == ["sleep:1.5", "get:2023", "get:2024", "get:2025"]
    assert sleeps == [1.5]


def test_backfill_ibkr_flex_full_years_reports_progress(tmp_path: Path) -> None:
    reporter = RecordingProgressReporter()

    class FakeFlexClient:
        def __init__(self) -> None:
            self.reference_to_year: dict[str, int] = {}

        def send_request(self, query_id: str, *, from_date, to_date, period=None) -> str:
            reference_code = f"ref-{from_date.year}"
            self.reference_to_year[reference_code] = from_date.year
            return reference_code

        def get_statement(self, reference_code: str) -> str:
            return _full_year_flex_xml(self.reference_to_year[reference_code])

        def sleep(self, seconds: float) -> None:
            return None

    backfill_ibkr_flex_full_years(
        output_dir=tmp_path / "outputs",
        query_id="1462703",
        token="secret-token",
        start_year=2024,
        end_year=2025,
        client=FakeFlexClient(),
        progress=reporter,
    )

    assert reporter.events[0] == {"kind": "stage", "label": "Flex backfill", "current": 0, "total": 2}
    assert any(
        event == {
            "kind": "spinner",
            "label": "Batch polling > Flex polling",
            "detail": "inflight=2 queued=0",
        }
        for event in reporter.events
    )
    assert reporter.events[-1] == {
        "kind": "done",
        "label": "Flex backfill",
        "detail": "2 years processed",
    }


def test_backfill_ibkr_flex_full_years_preserves_preflight_skip_promote_and_download_states(tmp_path: Path) -> None:
    output_dir = tmp_path / "outputs"
    raw_dir = output_dir / "raw"
    raw_dir.mkdir(parents=True)
    (raw_dir / "ibkr_flex_2022_full.xml").write_text("trusted-full-file", encoding="utf-8")
    promoted_candidate = raw_dir / "ibkr_flex_20260410_102343.xml"
    promoted_candidate.write_text(_full_year_flex_xml(2023), encoding="utf-8")
    calls: list[str] = []

    class FakeFlexClient:
        def send_request(self, query_id: str, *, from_date, to_date, period=None) -> str:
            assert query_id == "1462703"
            assert from_date == date(2024, 1, 1)
            assert to_date == date(2024, 12, 31)
            calls.append("send:2024")
            return "ref-2024"

        def get_statement(self, reference_code: str) -> str:
            assert reference_code == "ref-2024"
            calls.append("get:2024")
            return _full_year_flex_xml(2024)

        def sleep(self, seconds: float) -> None:
            raise AssertionError("sleep should not be needed for an immediately ready statement")

    records = backfill_ibkr_flex_full_years(
        output_dir=output_dir,
        query_id="1462703",
        token="secret-token",
        start_year=2022,
        end_year=2024,
        max_inflight_requests=3,
        client=FakeFlexClient(),
    )

    assert [record.status for record in records] == ["skipped", "promoted", "downloaded"]
    assert records[0].target_path == raw_dir / "ibkr_flex_2022_full.xml"
    assert records[1].source_file == promoted_candidate
    assert records[2].target_path == raw_dir / "ibkr_flex_2024_full.xml"
    assert calls == ["send:2024", "get:2024"]


def test_backfill_ibkr_flex_full_years_overwrites_existing_full_file_when_requested(tmp_path: Path) -> None:
    output_dir = tmp_path / "outputs"
    raw_dir = output_dir / "raw"
    raw_dir.mkdir(parents=True)
    target_path = raw_dir / "ibkr_flex_2025_full.xml"
    target_path.write_text("stale-content", encoding="utf-8")

    class FakeFlexClient:
        def send_request(self, query_id: str, *, from_date, to_date, period=None) -> str:
            assert query_id == "1462703"
            assert from_date == date(2025, 1, 1)
            assert to_date == date(2025, 12, 31)
            return "ref-2025"

        def get_statement(self, reference_code: str) -> str:
            assert reference_code == "ref-2025"
            return _full_year_flex_xml(2025)

        def sleep(self, seconds: float) -> None:
            raise AssertionError("sleep should not be needed for an immediately ready statement")

    records = backfill_ibkr_flex_full_years(
        output_dir=output_dir,
        query_id="1462703",
        token="secret-token",
        start_year=2025,
        end_year=2025,
        overwrite_existing=True,
        max_inflight_requests=3,
        client=FakeFlexClient(),
    )

    assert [record.status for record in records] == ["overwritten"]
    assert target_path.read_text(encoding="utf-8") == _full_year_flex_xml(2025)


def test_backfill_ibkr_flex_full_years_raises_batch_error_after_timeout_with_partial_results(tmp_path: Path) -> None:
    sleeps: list[float] = []

    class FakeFlexClient:
        def __init__(self) -> None:
            self.reference_to_year = {
                "ref-2024": 2024,
                "ref-2025": 2025,
            }
            self.poll_outcomes = {
                2024: ["pending", "pending"],
                2025: ["success"],
            }

        def send_request(self, query_id: str, *, from_date, to_date, period=None) -> str:
            assert query_id == "1462703"
            return f"ref-{from_date.year}"

        def get_statement(self, reference_code: str) -> str:
            year = self.reference_to_year[reference_code]
            outcome = self.poll_outcomes[year].pop(0)
            if outcome == "pending":
                raise FlexWebServicePendingError("Statement is not available.")
            return _full_year_flex_xml(year)

        def sleep(self, seconds: float) -> None:
            sleeps.append(seconds)

    with pytest.raises(FlexBackfillBatchError) as exc_info:
        backfill_ibkr_flex_full_years(
            output_dir=tmp_path / "outputs",
            query_id="1462703",
            token="secret-token",
            start_year=2024,
            end_year=2025,
            poll_interval_seconds=2.0,
            max_attempts=2,
            max_inflight_requests=2,
            client=FakeFlexClient(),
        )

    assert exc_info.value.failed_years == [2024]
    assert [record.status for record in exc_info.value.records] == ["failed", "downloaded"]
    assert "Polling exhausted after 2 attempts" in (exc_info.value.records[0].error_message or "")
    assert exc_info.value.records[1].target_path.exists()
    assert sleeps == [2.0]


def test_backfill_ibkr_flex_full_years_aggregates_nonretryable_failures_and_keeps_successes(tmp_path: Path) -> None:
    class FakeFlexClient:
        def send_request(self, query_id: str, *, from_date, to_date, period=None) -> str:
            assert query_id == "1462703"
            return f"ref-{from_date.year}"

        def get_statement(self, reference_code: str) -> str:
            if reference_code == "ref-2024":
                raise RuntimeError("token revoked mid-backfill")
            return _full_year_flex_xml(2025)

        def sleep(self, seconds: float) -> None:
            raise AssertionError("sleep should not be needed when nothing remains pending")

    with pytest.raises(FlexBackfillBatchError) as exc_info:
        backfill_ibkr_flex_full_years(
            output_dir=tmp_path / "outputs",
            query_id="1462703",
            token="secret-token",
            start_year=2024,
            end_year=2025,
            max_inflight_requests=2,
            client=FakeFlexClient(),
        )

    assert exc_info.value.failed_years == [2024]
    assert [record.status for record in exc_info.value.records] == ["failed", "downloaded"]
    assert exc_info.value.records[0].error_message == "token revoked mid-backfill"
    assert exc_info.value.records[1].target_path.exists()


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
      <EquitySummaryInBase>
        <EquitySummaryByReportDateInBase currency="USD" reportDate="2024-12-31" total="100" />
        <EquitySummaryByReportDateInBase currency="USD" reportDate="2025-12-31" total="120" />
      </EquitySummaryInBase>
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
      <EquitySummaryInBase>
        <EquitySummaryByReportDateInBase currency="USD" reportDate="2025-12-31" total="120" />
        <EquitySummaryByReportDateInBase currency="USD" reportDate="2026-04-10" total="220" />
      </EquitySummaryInBase>
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
            yahoo_client=_fake_yahoo_client(
                [
                    ("2024-12-31", 1.30),
                    ("2025-12-31", 1.31),
                    ("2026-04-10", 1.32),
                ]
            ),
        )
    assert recorded == []

    assert written_path.name == "performance_report_20260410.csv"
    assert (output_dir / "raw" / "ibkr_flex_2025_full.xml").exists()
    assert (output_dir / "raw" / "ibkr_flex_2026_latest.xml").exists()
    history = load_nav_cashflow_history(output_dir / "nav_cashflow_history.feather")
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
            yahoo_client=_fake_yahoo_client([("2026-04-10", 1.30)]),
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
    assert mtd_mwr_usd["source_version"] == "NavCashflowHistoryFeather"
    assert float(mtd_mwr_usd["dollar_pnl"]) > 0
    assert float(mtd_mwr_usd["return_pct"]) > 0


def test_merge_horizon_rows_keeps_history_values_when_simple_nav_fallback_has_data() -> None:
    primary = [
        flex_performance_module.FlexHorizonPerformanceRow(
            as_of=date(2021, 12, 31),
            source_version="PerformanceHistoryFeather+SimpleNavFallback",
            horizon="Y2021",
            weighting="time_weighted",
            currency="USD",
            dollar_pnl=54443.73,
            return_pct=0.542996856,
        )
    ]
    fallback = [
        flex_performance_module.FlexHorizonPerformanceRow(
            as_of=date(2021, 12, 31),
            source_version="DailyNavRebuilt+HistoricalYear",
            horizon="Y2021",
            weighting="time_weighted",
            currency="USD",
            dollar_pnl=53433.86,
            return_pct=0.532924894,
        )
    ]

    merged = portfolio_report_pipeline._merge_horizon_rows_by_key(
        primary=primary,
        fallback=fallback,
    )

    assert len(merged) == 1
    assert merged[0].source_version == "PerformanceHistoryFeather+SimpleNavFallback"
    assert merged[0].dollar_pnl == pytest.approx(54443.73)
    assert merged[0].return_pct == pytest.approx(0.542996856)
