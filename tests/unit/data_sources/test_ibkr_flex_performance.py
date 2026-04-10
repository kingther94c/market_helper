from datetime import datetime, timezone

import pytest

from market_helper.data_sources.ibkr.flex import (
    export_flex_horizon_report_csv,
    export_flex_performance_csv,
    parse_flex_performance_xml,
)
from market_helper.data_sources.yahoo_finance import YahooFinanceClient


def test_parse_flex_performance_xml_extracts_daily_cash_and_horizon_rows(tmp_path) -> None:
    xml_path = tmp_path / "flex.xml"
    xml_path.write_text(
        """
<FlexQueryResponse>
  <FlexStatements>
    <FlexStatement>
      <ChangeInNAV reportDate="2026-04-01" startingValue="100000" endingValue="102000" depositWithdrawal="500"/>
      <ChangeInNAV reportDate="2026-04-02" startingValue="102000" endingValue="101000" depositWithdrawal="-250"/>
      <CashTransactions>
        <CashTransaction reportDate="2026-04-01" amount="500" type="Deposit" description="Deposit"/>
        <CashTransaction reportDate="2026-04-02" amount="-250" type="Withdrawal" description="Withdrawal"/>
      </CashTransactions>
      <PerformanceSummary
        mtdMoneyWeightedUsdPnl="1200"
        mtdMoneyWeightedUsdReturn="0.012"
        mtdTimeWeightedUsdPnl="1000"
        mtdTimeWeightedUsdReturn="0.010"
        ytdMoneyWeightedUsdPnl="3000"
        ytdMoneyWeightedUsdReturn="0.030"
        ytdTimeWeightedUsdPnl="2800"
        ytdTimeWeightedUsdReturn="0.028"
        oneMonthMoneyWeightedUsdPnl="1400"
        oneMonthMoneyWeightedUsdReturn="0.014"
        oneMonthTimeWeightedUsdPnl="1300"
        oneMonthTimeWeightedUsdReturn="0.013"
      />
      <PerformanceSummaryAlt
        mtdMoneyWeightedSgdPnl="900"
      />
    </FlexStatement>
  </FlexStatements>
</FlexQueryResponse>
""".strip(),
        encoding="utf-8",
    )

    dataset = parse_flex_performance_xml(xml_path)

    assert len(dataset.daily_performance) == 2
    assert dataset.daily_performance[0].pnl == 1500.0
    assert dataset.daily_performance[1].pnl == -750.0
    assert len(dataset.cash_flows) == 2

    # Always emit a full 3x2x2 matrix even when some cells are missing.
    assert len(dataset.horizon_rows) == 12
    mtd_mwr_usd = [
        row
        for row in dataset.horizon_rows
        if row.horizon == "MTD" and row.weighting == "money_weighted" and row.currency == "USD"
    ][0]
    assert mtd_mwr_usd.dollar_pnl == 1200.0
    assert mtd_mwr_usd.return_pct == 0.012


def test_parse_flex_performance_xml_rebuilds_distinct_mwr_and_twr_from_daily_cash_flows(tmp_path) -> None:
    xml_path = tmp_path / "flex.xml"
    xml_path.write_text(
        """
<FlexQueryResponse>
  <FlexStatements>
    <FlexStatement toDate="20260403" whenGenerated="20260404;080634">
      <ChangeInNAV reportDate="2026-04-01" startingValue="100" endingValue="110" depositWithdrawal="0"/>
      <ChangeInNAV reportDate="2026-04-02" startingValue="110" endingValue="170" depositWithdrawal="50"/>
      <ChangeInNAV reportDate="2026-04-03" startingValue="170" endingValue="175" depositWithdrawal="0"/>
    </FlexStatement>
  </FlexStatements>
</FlexQueryResponse>
""".strip(),
        encoding="utf-8",
    )

    dataset = parse_flex_performance_xml(xml_path)

    mtd_mwr_usd = [
        row
        for row in dataset.horizon_rows
        if row.horizon == "MTD" and row.weighting == "money_weighted" and row.currency == "USD"
    ][0]
    mtd_twr_usd = [
        row
        for row in dataset.horizon_rows
        if row.horizon == "MTD" and row.weighting == "time_weighted" and row.currency == "USD"
    ][0]

    assert mtd_mwr_usd.source_version == "DailyNavRebuilt+ExplicitCashFlows"
    assert mtd_twr_usd.source_version == "DailyNavRebuilt+ExplicitCashFlows"
    assert mtd_mwr_usd.return_pct == pytest.approx(0.21627887556594488)
    assert mtd_mwr_usd.dollar_pnl == pytest.approx(21.627887556594487)
    assert mtd_twr_usd.return_pct == pytest.approx(0.23529411764705865)
    assert mtd_twr_usd.dollar_pnl == pytest.approx(23.529411764705866)
    assert mtd_mwr_usd.return_pct != pytest.approx(mtd_twr_usd.return_pct)


def test_export_flex_horizon_report_csv_writes_dated_file(tmp_path) -> None:
    xml_path = tmp_path / "flex.xml"
    xml_path.write_text(
        """
<FlexQueryResponse>
  <FlexStatements>
    <FlexStatement>
      <ChangeInNAV reportDate="2026-04-02" startingValue="100000" endingValue="101000" depositWithdrawal="0"/>
      <PerformanceSummary mtdMoneyWeightedUsdPnl="1000" mtdMoneyWeightedUsdReturn="0.01" />
    </FlexStatement>
  </FlexStatements>
</FlexQueryResponse>
""".strip(),
        encoding="utf-8",
    )

    dataset = parse_flex_performance_xml(xml_path)
    report_path = export_flex_horizon_report_csv(dataset, output_dir=tmp_path)

    assert report_path.name == "performance_report_20260402.csv"
    csv_text = report_path.read_text(encoding="utf-8")
    assert "as_of,source_version,horizon,weighting,currency,dollar_pnl,return_pct" in csv_text
    assert "2026-04-02,PerformanceSummary,MTD,money_weighted,USD,1000,0.01" in csv_text


def test_parse_flex_performance_xml_extracts_total_summary_rows_from_ibkr_statement_shape(tmp_path) -> None:
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

    dataset = parse_flex_performance_xml(xml_path)

    assert len(dataset.horizon_rows) == 12
    mtd_mwr_sgd = [
        row
        for row in dataset.horizon_rows
        if row.horizon == "MTD" and row.weighting == "money_weighted" and row.currency == "SGD"
    ][0]
    one_month_twr_sgd = [
        row
        for row in dataset.horizon_rows
        if row.horizon == "1M" and row.weighting == "time_weighted" and row.currency == "SGD"
    ][0]
    mtd_mwr_usd = [
        row
        for row in dataset.horizon_rows
        if row.horizon == "MTD" and row.weighting == "money_weighted" and row.currency == "USD"
    ][0]

    assert mtd_mwr_sgd.as_of.isoformat() == "2026-04-07"
    assert mtd_mwr_sgd.dollar_pnl == 8000.0
    assert mtd_mwr_sgd.return_pct == 0.08
    assert one_month_twr_sgd.dollar_pnl == 15000.0
    assert round(one_month_twr_sgd.return_pct, 10) == round(15000.0 / 95000.0, 10)
    assert mtd_mwr_usd.dollar_pnl is None
    assert mtd_mwr_usd.return_pct is None


def test_parse_flex_performance_xml_can_fill_usd_rows_from_yahoo_fx(tmp_path) -> None:
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

    dataset = parse_flex_performance_xml(xml_path, yahoo_client=yahoo_client)

    mtd_mwr_usd = [
        row
        for row in dataset.horizon_rows
        if row.horizon == "MTD" and row.weighting == "money_weighted" and row.currency == "USD"
    ][0]
    ytd_twr_usd = [
        row
        for row in dataset.horizon_rows
        if row.horizon == "YTD" and row.weighting == "time_weighted" and row.currency == "USD"
    ][0]

    assert mtd_mwr_usd.source_version == "MTDYTDPerformanceSummaryTotal+YahooFinanceFX"
    assert mtd_mwr_usd.dollar_pnl == pytest.approx(8000.0 / 1.32)
    assert mtd_mwr_usd.return_pct == pytest.approx((8000.0 / 1.32) / (100000.0 / 1.31))
    assert ytd_twr_usd.source_version == "MTDYTDPerformanceSummaryTotal+YahooFinanceFX"
    assert ytd_twr_usd.dollar_pnl == pytest.approx(15000.0 / 1.32)
    assert ytd_twr_usd.return_pct == pytest.approx((15000.0 / 1.32) / (95000.0 / 1.30))


def test_parse_flex_performance_xml_uses_cash_report_summary_when_daily_cash_flow_is_missing(tmp_path) -> None:
    xml_path = tmp_path / "flex.xml"
    xml_path.write_text(
        """
<FlexQueryResponse>
  <FlexStatements>
    <FlexStatement toDate="20260403" whenGenerated="20260404;080634">
      <EquitySummaryInBase>
        <EquitySummaryByReportDateInBase currency="SGD" reportDate="20260331" total="100" />
        <EquitySummaryByReportDateInBase currency="SGD" reportDate="20260401" total="102" />
        <EquitySummaryByReportDateInBase currency="SGD" reportDate="20260402" total="154" />
        <EquitySummaryByReportDateInBase currency="SGD" reportDate="20260403" total="160" />
      </EquitySummaryInBase>
      <CashReport>
        <CashReportCurrency
          currency="BASE_SUMMARY"
          levelOfDetail="BaseCurrency"
          fromDate="20260331"
          toDate="20260403"
          depositWithdrawals="50"
          depositWithdrawalsMTD="50"
          depositWithdrawalsYTD="50"
        />
      </CashReport>
    </FlexStatement>
  </FlexStatements>
</FlexQueryResponse>
""".strip(),
        encoding="utf-8",
    )

    dataset = parse_flex_performance_xml(xml_path)

    mtd_mwr_sgd = [
        row
        for row in dataset.horizon_rows
        if row.horizon == "MTD" and row.weighting == "money_weighted" and row.currency == "SGD"
    ][0]
    mtd_twr_sgd = [
        row
        for row in dataset.horizon_rows
        if row.horizon == "MTD" and row.weighting == "time_weighted" and row.currency == "SGD"
    ][0]

    assert mtd_mwr_sgd.source_version == "DailyNavRebuilt+CashReportSummary"
    assert mtd_twr_sgd.source_version == "DailyNavRebuilt+CashReportSummary"
    assert mtd_mwr_sgd.return_pct == pytest.approx(0.07522824920001768)
    assert mtd_mwr_sgd.dollar_pnl == pytest.approx(7.522824920001768)
    assert mtd_twr_sgd.return_pct == pytest.approx(-0.1843137254901961)
    assert mtd_twr_sgd.dollar_pnl == pytest.approx(-18.43137254901961)
    assert mtd_mwr_sgd.return_pct != pytest.approx(mtd_twr_sgd.return_pct)


def test_export_flex_performance_csv_writes_legacy_detail_files(tmp_path) -> None:
    xml_path = tmp_path / "flex.xml"
    xml_path.write_text(
        """
<FlexQueryResponse>
  <FlexStatements>
    <FlexStatement>
      <ChangeInNAV reportDate="2026-04-01" startingValue="100000" endingValue="101000" depositWithdrawal="0"/>
    </FlexStatement>
  </FlexStatements>
</FlexQueryResponse>
""".strip(),
        encoding="utf-8",
    )

    dataset = parse_flex_performance_xml(xml_path)
    paths = export_flex_performance_csv(dataset, output_dir=tmp_path)

    assert paths.daily_performance_csv.exists()
    assert paths.cash_flows_csv.exists()
