from market_helper.data_sources.ibkr.flex import (
    export_flex_horizon_report_csv,
    export_flex_performance_csv,
    parse_flex_performance_xml,
)


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
