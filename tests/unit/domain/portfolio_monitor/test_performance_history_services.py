from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pytest

import market_helper.data_sources.ibkr.flex.performance as flex_performance_module
from market_helper.data_sources.yahoo_finance import YahooFinanceClient
from market_helper.domain.portfolio_monitor.services.nav_cashflow_history import (
    build_horizon_rows_from_nav_cashflow_history,
    extract_classified_deposit_withdrawal_frame,
    load_nav_cashflow_history,
    rebuild_nav_cashflow_history_feather,
)
from market_helper.domain.portfolio_monitor.services.performance_analytics import (
    annualized_return,
    annualized_vol,
    build_twr_index,
    build_window_metric_row,
    build_yearly_metric_rows,
    dollar_cumulative_plot_frame,
    dollar_drawdown_plot_frame,
    drawdown_series,
    percent_cumulative_plot_frame,
    sharpe_ratio,
    slice_history_for_window,
)


def test_rebuild_nav_cashflow_history_round_trips_and_marks_latest_tail_provisional(tmp_path: Path) -> None:
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    _write_nav_cashflow_xml(
        raw_dir / "ibkr_flex_2025_full.xml",
        from_date="20250101",
        to_date="20251231",
        totals=[
            ("2024-12-31", 100.0),
            ("2025-06-30", 110.0),
            ("2025-12-31", 120.0),
        ],
    )
    _write_nav_cashflow_xml(
        raw_dir / "ibkr_flex_2026_latest.xml",
        from_date="20260101",
        to_date="20260105",
        totals=[
            ("2025-12-31", 120.0),
            ("2026-01-02", 126.0),
            ("2026-01-05", 132.0),
        ],
    )

    history_path = rebuild_nav_cashflow_history_feather(
        raw_dir=raw_dir,
        output_path=tmp_path / "nav_cashflow_history.feather",
        yahoo_client=_fake_yahoo_client(
            [
                ("2024-12-31", 1.30),
                ("2025-06-30", 1.31),
                ("2025-12-31", 1.32),
                ("2026-01-02", 1.33),
                ("2026-01-05", 1.34),
            ]
        ),
    )

    history = load_nav_cashflow_history(history_path)

    assert history_path.exists()
    assert list(history["date"].dt.strftime("%Y-%m-%d")) == [
        "2024-12-31",
        "2025-06-30",
        "2025-12-31",
        "2026-01-02",
        "2026-01-05",
    ]
    assert bool(history.iloc[-1]["is_final"]) is False
    assert bool(history.iloc[-2]["is_final"]) is True
    assert history.iloc[-1]["nav_eod_sgd"] == pytest.approx(132.0 * 1.34)
    assert history.iloc[-1]["cashflow_usd"] == pytest.approx(0.0)


def test_build_horizon_rows_from_nav_cashflow_history_appends_historical_years(tmp_path: Path) -> None:
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    _write_nav_cashflow_xml(
        raw_dir / "ibkr_flex_2025_full.xml",
        from_date="20250101",
        to_date="20251231",
        totals=[
            ("2024-12-31", 100.0),
            ("2025-12-31", 120.0),
        ],
    )
    _write_nav_cashflow_xml(
        raw_dir / "ibkr_flex_2026_latest.xml",
        from_date="20260101",
        to_date="20260105",
        totals=[
            ("2025-12-31", 120.0),
            ("2026-01-02", 126.0),
            ("2026-01-05", 132.0),
        ],
    )

    history = load_nav_cashflow_history(
        rebuild_nav_cashflow_history_feather(
            raw_dir=raw_dir,
            output_path=tmp_path / "nav_cashflow_history.feather",
            yahoo_client=_fake_yahoo_client(
                [
                    ("2024-12-31", 1.30),
                    ("2025-12-31", 1.32),
                    ("2026-01-02", 1.33),
                    ("2026-01-05", 1.34),
                ]
            ),
        )
    )

    rows, missing_years = build_horizon_rows_from_nav_cashflow_history(
        history,
        archive_start_year=2025,
    )
    y2025_twr_usd = next(
        row
        for row in rows
        if row.horizon == "Y2025" and row.weighting == "time_weighted" and row.currency == "USD"
    )
    ytd_twr_usd = next(
        row
        for row in rows
        if row.horizon == "YTD" and row.weighting == "time_weighted" and row.currency == "USD"
    )

    assert missing_years == []
    assert y2025_twr_usd.return_pct == pytest.approx(0.20)
    assert y2025_twr_usd.source_version == "NavCashflowHistoryFeather"
    assert ytd_twr_usd.return_pct == pytest.approx(0.10)
    assert ytd_twr_usd.source_version == "NavCashflowHistoryFeather+ProvisionalLatest"


def test_rebuild_nav_cashflow_history_aggregates_multicurrency_cashflows_by_report_date(tmp_path: Path) -> None:
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    _write_nav_cashflow_xml(
        raw_dir / "ibkr_flex_2026_latest.xml",
        from_date="20260101",
        to_date="20260402",
        currency="SGD",
        totals=[
            ("2025-12-31", 100.0),
            ("2026-04-01", 160.0),
            ("2026-04-02", 166.0),
        ],
        cash_transactions=[
            ("2026-04-01", "SGD", 40.0, "Deposits/Withdrawals", None, "CASH RECEIPTS / ELECTRONIC FUND TRANSFERS"),
            ("2026-04-01", "USD", -10.0, "Deposits/Withdrawals", None, "DISBURSEMENT"),
            ("2026-04-01", "USD", 999.0, "Broker Interest Received"),
        ],
    )

    history = load_nav_cashflow_history(
        rebuild_nav_cashflow_history_feather(
            raw_dir=raw_dir,
            output_path=tmp_path / "nav_cashflow_history.feather",
            yahoo_client=_fake_yahoo_client(
                [
                    ("2025-12-31", 2.0),
                    ("2026-04-01", 2.0),
                    ("2026-04-02", 2.0),
                ]
            ),
        )
    )

    flow_row = history.loc[history["date"].eq(pd.Timestamp("2026-04-01"))].iloc[0]
    pnl_row = history.loc[history["date"].eq(pd.Timestamp("2026-04-02"))].iloc[0]

    assert flow_row["cashflow_sgd"] == pytest.approx(20.0)
    assert flow_row["cashflow_usd"] == pytest.approx(10.0)
    assert flow_row["pnl_amt_usd"] == pytest.approx(20.0)
    assert flow_row["pnl_usd"] == pytest.approx(0.40)
    assert pnl_row["pnl_amt_usd"] == pytest.approx(3.0)
    assert pnl_row["pnl_usd"] == pytest.approx(3.0 / 80.0)


def test_cash_transaction_uses_report_date_before_settle_date_and_datetime(tmp_path: Path) -> None:
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    _write_nav_cashflow_xml(
        raw_dir / "ibkr_flex_2026_latest.xml",
        from_date="20260101",
        to_date="20260403",
        totals=[
            ("2026-04-01", 100.0),
            ("2026-04-02", 100.0),
            ("2026-04-03", 125.0),
        ],
        cash_transactions=[
            ("2026-04-03", "USD", 25.0, "Deposits/Withdrawals", "2026-04-02T23:59:00", "CASH RECEIPTS / ELECTRONIC FUND TRANSFERS", "2026-04-02"),
        ],
    )

    history = load_nav_cashflow_history(
        rebuild_nav_cashflow_history_feather(
            raw_dir=raw_dir,
            output_path=tmp_path / "nav_cashflow_history.feather",
            yahoo_client=_fake_yahoo_client(
                [
                    ("2026-04-01", 1.3),
                    ("2026-04-02", 1.3),
                    ("2026-04-03", 1.3),
                ]
            ),
        )
    )

    row = history.loc[history["date"].eq(pd.Timestamp("2026-04-02"))].iloc[0]
    assert row["cashflow_usd"] == pytest.approx(25.0)
    assert row["pnl_amt_usd"] == pytest.approx(-25.0)


def test_deposit_withdrawal_audit_frame_keeps_all_descriptions_and_report_dates(tmp_path: Path) -> None:
    xml_path = tmp_path / "flex.xml"
    _write_nav_cashflow_xml(
        xml_path,
        from_date="20240601",
        to_date="20240630",
        totals=[
            ("2024-06-10", 249287.45),
            ("2024-06-11", 4456.73),
            ("2024-06-12", 4579.08),
            ("2024-06-14", 20755.89),
            ("2024-06-18", 20884.94),
            ("2024-06-19", 265656.40),
        ],
        currency="SGD",
        cash_transactions=[
            ("2024-06-12", "SGD", 244773.0, "Deposits/Withdrawals", "2024-06-11;092643", "CANCELLATION", "2024-06-12"),
            ("2024-06-12", "SGD", -244773.0, "Deposits/Withdrawals", "2024-06-11;092643", "DISBURSEMENT INITIATED BY Jinze Chen", "2024-06-11"),
            ("2024-06-14", "SGD", -244773.0, "Deposits/Withdrawals", "2024-06-11;092643", "DISBURSEMENT INITIATED BY Jinze Chen", "2024-06-12"),
            ("2024-06-18", "SGD", 244773.0, "Deposits/Withdrawals", "2024-06-18", "CASH RECEIPTS / ELECTRONIC FUND TRANSFERS", "2024-06-19"),
            ("2024-08-08", "USD", 14279.85, "Deposits/Withdrawals", "2024-08-08;220753", "ADJUSTMENT: DEPOSIT ADVANCE", "2024-08-09"),
        ],
    )

    frame = extract_classified_deposit_withdrawal_frame(xml_path)
    assert set(frame["classification"]) == {"DEPOSITS_WITHDRAWALS"}

    cancellation = frame.loc[frame["description"].eq("CANCELLATION")].iloc[0]
    advance = frame.loc[frame["description"].eq("ADJUSTMENT: DEPOSIT ADVANCE")].iloc[0]
    receipt = frame.loc[frame["description"].eq("CASH RECEIPTS / ELECTRONIC FUND TRANSFERS")].iloc[0]
    initiated = frame.loc[frame["description"].eq("DISBURSEMENT INITIATED BY Jinze Chen")]

    assert pd.Timestamp(cancellation["event_date"]) == pd.Timestamp("2024-06-12")
    assert pd.Timestamp(receipt["event_date"]) == pd.Timestamp("2024-06-19")
    assert cancellation["classification"] == "DEPOSITS_WITHDRAWALS"
    assert advance["classification"] == "DEPOSITS_WITHDRAWALS"
    assert set(initiated["classification"]) == {"DEPOSITS_WITHDRAWALS"}
    assert receipt["classification"] == "DEPOSITS_WITHDRAWALS"


def test_unknown_deposit_withdrawal_description_is_included_in_history(tmp_path: Path) -> None:
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    _write_nav_cashflow_xml(
        raw_dir / "ibkr_flex_2026_latest.xml",
        from_date="20260101",
        to_date="20260402",
        currency="USD",
        totals=[
            ("2026-04-01", 100.0),
            ("2026-04-02", 105.0),
        ],
        cash_transactions=[
            ("2026-04-02", "USD", 25.0, "Deposits/Withdrawals", None, "SOMETHING ELSE"),
        ],
    )

    frame = extract_classified_deposit_withdrawal_frame(raw_dir / "ibkr_flex_2026_latest.xml")
    assert frame.iloc[0]["classification"] == "DEPOSITS_WITHDRAWALS"

    history = load_nav_cashflow_history(
        rebuild_nav_cashflow_history_feather(
            raw_dir=raw_dir,
            output_path=tmp_path / "nav_cashflow_history.feather",
            yahoo_client=_fake_yahoo_client(
                [
                    ("2026-04-01", 1.3),
                    ("2026-04-02", 1.3),
                ]
            ),
        )
    )

    row = history.loc[history["date"].eq(pd.Timestamp("2026-04-02"))].iloc[0]
    assert row["cashflow_usd"] == pytest.approx(25.0)
    assert row["pnl_amt_usd"] == pytest.approx(-20.0)


def test_unsupported_base_currency_raises(tmp_path: Path) -> None:
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    _write_nav_cashflow_xml(
        raw_dir / "ibkr_flex_2026_latest.xml",
        from_date="20260101",
        to_date="20260402",
        currency="EUR",
        totals=[("2026-04-02", 100.0)],
    )

    with pytest.raises(ValueError, match="Unsupported IBKR Flex base currency"):
        rebuild_nav_cashflow_history_feather(
            raw_dir=raw_dir,
            output_path=tmp_path / "nav_cashflow_history.feather",
            yahoo_client=_fake_yahoo_client([("2026-04-02", 1.3)]),
        )


def test_performance_analytics_default_to_finalized_history() -> None:
    history = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-01-01", "2026-01-02", "2026-01-03", "2026-01-06"]),
            "nav_eod_usd": [100.0, 110.0, 99.0, 103.95],
            "nav_eod_sgd": [130.0, 143.0, 128.7, 135.135],
            "cashflow_usd": [0.0, 0.0, 0.0, 0.0],
            "cashflow_sgd": [0.0, 0.0, 0.0, 0.0],
            "fx_usdsgd_eod": [1.30, 1.30, 1.30, 1.30],
            "pnl_amt_usd": [pd.NA, 10.0, -11.0, 4.95],
            "pnl_amt_sgd": [pd.NA, 13.0, -14.3, 6.435],
            "pnl_usd": [pd.NA, 0.10, -0.10, 0.05],
            "pnl_sgd": [pd.NA, 0.10, -0.10, 0.05],
            "is_final": [True, True, True, False],
            "source_kind": ["latest"] * 4,
            "source_file": ["demo.xml"] * 4,
            "source_as_of": pd.to_datetime(["2026-01-06"] * 4),
        }
    )

    index = build_twr_index(history, "USD")
    drawdown = drawdown_series(history, "USD")

    assert list(index.index.strftime("%Y-%m-%d")) == ["2026-01-02", "2026-01-03"]
    assert index.iloc[-1] == pytest.approx(0.99)
    assert drawdown.min() == pytest.approx(-0.10)
    assert annualized_return(history, "USD") is None
    assert annualized_return(history, "USD", include_provisional=True) is None


def test_slice_history_for_window_adds_opening_row_and_handles_trailing_windows() -> None:
    history = _demo_history_frame()

    ytd = slice_history_for_window(history, window="YTD", include_provisional=True)
    trailing_1y = slice_history_for_window(history, window="1Y", include_provisional=True)
    trailing_5y = slice_history_for_window(history, window="5Y", include_provisional=True)

    assert list(ytd["date"].dt.strftime("%Y-%m-%d")) == ["2025-12-31", "2026-01-31", "2026-03-31"]
    assert len(trailing_1y) >= 3
    assert len(trailing_5y) == len(history)


def test_build_window_metric_row_returns_na_metrics_when_samples_are_insufficient() -> None:
    history = _demo_history_frame().iloc[-2:].copy()

    metrics = build_window_metric_row(
        history,
        window="3Y",
        primary_currency="USD",
        secondary_currency="SGD",
        include_provisional=True,
    )

    assert metrics.label == "3Y"
    assert metrics.twr_return is None
    assert metrics.mwr_return is None
    assert metrics.secondary_twr_return is None


def test_build_yearly_metric_rows_only_returns_complete_years() -> None:
    history = _demo_history_frame()

    rows = build_yearly_metric_rows(
        history,
        primary_currency="USD",
        secondary_currency="SGD",
    )

    assert [row.label for row in rows] == ["2024", "2025"]
    assert rows[0].twr_return is not None
    assert rows[-1].secondary_twr_return is not None


def test_annualized_metrics_use_consistent_daily_annualization() -> None:
    history = pd.DataFrame(
        {
            "date": pd.bdate_range("2026-01-01", periods=40),
            "nav_eod_usd": [100.0 * (1.001 ** idx) for idx in range(40)],
            "nav_eod_sgd": [130.0 * (1.001 ** idx) for idx in range(40)],
            "cashflow_usd": [0.0] * 40,
            "cashflow_sgd": [0.0] * 40,
            "fx_usdsgd_eod": [1.30] * 40,
            "pnl_amt_usd": [pd.NA] + [100.0 * (1.001 ** (idx - 1)) * 0.001 for idx in range(1, 40)],
            "pnl_amt_sgd": [pd.NA] + [130.0 * (1.001 ** (idx - 1)) * 0.001 for idx in range(1, 40)],
            "pnl_usd": [pd.NA] + [0.001] * 39,
            "pnl_sgd": [pd.NA] + [0.001] * 39,
            "is_final": [True] * 40,
            "source_kind": ["full"] * 40,
            "source_file": ["demo.xml"] * 40,
            "source_as_of": pd.to_datetime(["2026-02-27"] * 40),
        }
    )

    ann_return = annualized_return(history, "USD")
    ann_vol = annualized_vol(history, "USD")
    sharpe = sharpe_ratio(history, "USD")

    assert ann_return is not None
    assert ann_vol is not None
    assert ann_vol == pytest.approx(0.0)
    assert ann_return == pytest.approx((1.001**252) - 1.0, rel=1e-4)
    assert sharpe is None


def test_sparse_history_returns_na_for_risk_metrics_and_builds_dollar_plot_frames() -> None:
    history = _demo_history_frame()

    yearly_rows = build_yearly_metric_rows(history, primary_currency="USD")
    row_1y = build_window_metric_row(
        history,
        window="1Y",
        primary_currency="USD",
        include_provisional=True,
    )
    dollar_cumulative = dollar_cumulative_plot_frame(
        slice_history_for_window(history, window="YTD", include_provisional=True),
        "USD",
        include_provisional=True,
    )
    dollar_drawdown = dollar_drawdown_plot_frame(
        slice_history_for_window(history, window="YTD", include_provisional=True),
        "USD",
        include_provisional=True,
    )

    assert yearly_rows[0].annualized_vol is None
    assert yearly_rows[0].sharpe_ratio is None
    assert yearly_rows[0].max_drawdown is None
    assert row_1y.annualized_vol is None
    assert row_1y.sharpe_ratio is None
    assert list(dollar_cumulative.columns) == ["date", "cumulative_pnl", "drawdown"]
    assert list(dollar_drawdown.columns) == ["date", "drawdown"]
    assert float(dollar_cumulative.iloc[0]["cumulative_pnl"]) == pytest.approx(0.0)


def test_sharpe_matches_annualized_return_divided_by_vol_for_daily_history() -> None:
    returns = [0.01, -0.005] * 20
    nav = [100.0]
    pnl = [pd.NA]
    for daily_return in returns:
        pnl.append(nav[-1] * daily_return)
        nav.append(nav[-1] * (1.0 + daily_return))
    history = pd.DataFrame(
        {
            "date": pd.bdate_range("2026-01-01", periods=len(nav)),
            "nav_eod_usd": nav,
            "nav_eod_sgd": [value * 1.3 for value in nav],
            "cashflow_usd": [0.0] * len(nav),
            "cashflow_sgd": [0.0] * len(nav),
            "fx_usdsgd_eod": [1.30] * len(nav),
            "pnl_amt_usd": pnl,
            "pnl_amt_sgd": [pd.NA if value is pd.NA else float(value) * 1.3 for value in pnl],
            "pnl_usd": [pd.NA, *returns],
            "pnl_sgd": [pd.NA, *returns],
            "is_final": [True] * len(nav),
            "source_kind": ["full"] * len(nav),
            "source_file": ["demo.xml"] * len(nav),
            "source_as_of": pd.to_datetime(["2026-02-27"] * len(nav)),
        }
    )

    ann_return = annualized_return(history, "USD")
    ann_vol = annualized_vol(history, "USD")
    sharpe = sharpe_ratio(history, "USD")

    assert ann_return is not None
    assert ann_vol is not None
    assert sharpe is not None
    assert sharpe == pytest.approx(ann_return / ann_vol)


def _write_nav_cashflow_xml(
    path: Path,
    *,
    from_date: str,
    to_date: str,
    totals: list[tuple[str, float]],
    cash_transactions: list[
        tuple[str, str, float, str]
        | tuple[str, str, float, str, str | None]
        | tuple[str, str, float, str, str | None, str]
        | tuple[str, str, float, str, str | None, str, str]
    ] | None = None,
    currency: str = "USD",
) -> None:
    nav_rows = "\n".join(
        f'<EquitySummaryByReportDateInBase currency="{currency}" reportDate="{report_date}" total="{total}" />'
        for report_date, total in totals
    )
    cash_rows = []
    for item in cash_transactions or []:
        settle_date, row_currency, amount, row_type, *extra = item
        date_time = extra[0] if len(extra) >= 1 else None
        description = extra[1] if len(extra) >= 2 else "External Transfer"
        report_date = extra[2] if len(extra) >= 3 else None
        attrs = [
            f'currency="{row_currency}"',
            f'amount="{amount}"',
            f'type="{row_type}"',
            f'description="{description}"',
            f'settleDate="{settle_date}"',
        ]
        if date_time:
            attrs.append(f'dateTime="{date_time}"')
        if report_date:
            attrs.append(f'reportDate="{report_date}"')
        cash_rows.append(f"<CashTransaction {' '.join(attrs)} />")
    cash_block = "\n".join(cash_rows)
    path.write_text(
        f"""
<FlexQueryResponse>
  <FlexStatements>
    <FlexStatement accountId="U2935967" fromDate="{from_date}" toDate="{to_date}" whenGenerated="{to_date};010101">
      <EquitySummaryInBase>
        {nav_rows}
      </EquitySummaryInBase>
      <CashTransactions>
        {cash_block}
      </CashTransactions>
    </FlexStatement>
  </FlexStatements>
</FlexQueryResponse>
""".strip(),
        encoding="utf-8",
    )


def _demo_history_frame() -> pd.DataFrame:
    returns = [pd.NA, 0.1111111111, 0.20, 0.05, 0.05]
    nav_usd = [90.0, 100.0, 120.0, 126.0, 132.3]
    pnl_amt_usd = [pd.NA]
    for idx in range(1, len(nav_usd)):
        pnl_amt_usd.append(nav_usd[idx] - nav_usd[idx - 1])
    return pd.DataFrame(
        {
            "date": pd.to_datetime(
                [
                    "2023-12-31",
                    "2024-12-31",
                    "2025-12-31",
                    "2026-01-31",
                    "2026-03-31",
                ]
            ),
            "nav_eod_usd": nav_usd,
            "nav_eod_sgd": [117.0, 130.0, 156.0, 163.8, 171.99],
            "cashflow_usd": [0.0] * 5,
            "cashflow_sgd": [0.0] * 5,
            "fx_usdsgd_eod": [1.30] * 5,
            "pnl_amt_usd": pnl_amt_usd,
            "pnl_amt_sgd": [pd.NA if value is pd.NA else float(value) * 1.3 for value in pnl_amt_usd],
            "pnl_usd": returns,
            "pnl_sgd": returns,
            "is_final": [True, True, True, True, False],
            "source_kind": ["full", "full", "full", "latest", "latest"],
            "source_file": ["demo.xml"] * 5,
            "source_as_of": pd.to_datetime(["2026-03-31"] * 5),
        }
    )


def _fake_yahoo_client(levels: list[tuple[str, float]]) -> YahooFinanceClient:
    flex_performance_module._YAHOO_FX_HISTORY_CACHE.clear()
    return YahooFinanceClient(
        downloader=lambda _url: {
            "chart": {
                "result": [
                    {
                        "meta": {"currency": "SGD"},
                        "timestamp": [
                            int(datetime.strptime(raw_date, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp())
                            for raw_date, _ in levels
                        ],
                        "indicators": {
                            "quote": [{"close": [level for _, level in levels]}],
                            "adjclose": [{"adjclose": [level for _, level in levels]}],
                        },
                    }
                ]
            }
        }
    )
