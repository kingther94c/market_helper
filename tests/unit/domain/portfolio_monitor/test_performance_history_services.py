from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd
import pytest

import market_helper.data_sources.ibkr.flex.performance as flex_performance_module
from market_helper.data_sources.yahoo_finance import YahooFinanceClient
from market_helper.domain.portfolio_monitor.services.performance_analytics import (
    annualized_return,
    build_twr_index,
    drawdown_series,
)
from market_helper.domain.portfolio_monitor.services.performance_history import (
    build_horizon_rows_from_performance_history,
    load_performance_history,
    rebuild_performance_history_feather,
)


def test_rebuild_performance_history_feather_round_trips_and_marks_latest_tail_provisional(tmp_path: Path) -> None:
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    _write_nav_snapshot_xml(
        raw_dir / "ibkr_flex_2025_full.xml",
        from_date="20250101",
        to_date="20251231",
        totals=[
            ("2024-12-31", 100.0),
            ("2025-06-30", 110.0),
            ("2025-12-31", 120.0),
        ],
    )
    _write_nav_snapshot_xml(
        raw_dir / "ibkr_flex_2026_latest.xml",
        from_date="20260101",
        to_date="20260105",
        totals=[
            ("2025-12-31", 120.0),
            ("2026-01-02", 126.0),
            ("2026-01-05", 132.0),
        ],
    )

    history_path = rebuild_performance_history_feather(
        raw_dir=raw_dir,
        output_path=tmp_path / "performance_history.feather",
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

    history = load_performance_history(history_path)

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
    assert history.iloc[-1]["nav_close_sgd"] == pytest.approx(132.0 * 1.34)


def test_build_horizon_rows_from_performance_history_appends_historical_years(tmp_path: Path) -> None:
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    _write_nav_snapshot_xml(
        raw_dir / "ibkr_flex_2025_full.xml",
        from_date="20250101",
        to_date="20251231",
        totals=[
            ("2024-12-31", 100.0),
            ("2025-12-31", 120.0),
        ],
    )
    _write_nav_snapshot_xml(
        raw_dir / "ibkr_flex_2026_latest.xml",
        from_date="20260101",
        to_date="20260105",
        totals=[
            ("2025-12-31", 120.0),
            ("2026-01-02", 126.0),
            ("2026-01-05", 132.0),
        ],
    )
    history_path = rebuild_performance_history_feather(
        raw_dir=raw_dir,
        output_path=tmp_path / "performance_history.feather",
        yahoo_client=_fake_yahoo_client(
            [
                ("2024-12-31", 1.30),
                ("2025-12-31", 1.32),
                ("2026-01-02", 1.33),
                ("2026-01-05", 1.34),
            ]
        ),
    )
    history = load_performance_history(history_path)

    rows, missing_years = build_horizon_rows_from_performance_history(
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
    assert y2025_twr_usd.source_version == "PerformanceHistoryFeather+SimpleNavFallback"
    assert ytd_twr_usd.return_pct == pytest.approx(0.10)
    assert ytd_twr_usd.source_version == "PerformanceHistoryFeather+SimpleNavFallback+ProvisionalLatest"


def test_rebuild_performance_history_infers_multicurrency_cash_flows_from_statement_history(tmp_path: Path) -> None:
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    _write_statement_with_cash_report(
        raw_dir / "ibkr_flex_20260401_010101.xml",
        from_date="20260101",
        to_date="20260401",
        totals=[
            ("2025-12-31", 100.0),
            ("2026-04-01", 100.0),
        ],
        cash_currency_rows=[
            ("SGD", 40.0),
            ("USD", 10.0),
        ],
    )
    _write_statement_with_cash_report(
        raw_dir / "ibkr_flex_20260402_010101.xml",
        from_date="20260101",
        to_date="20260402",
        totals=[
            ("2025-12-31", 100.0),
            ("2026-04-01", 100.0),
            ("2026-04-02", 166.0),
        ],
        cash_currency_rows=[
            ("SGD", 40.0),
            ("USD", 10.0),
        ],
    )

    history_path = rebuild_performance_history_feather(
        raw_dir=raw_dir,
        output_path=tmp_path / "performance_history.feather",
        yahoo_client=_fake_yahoo_client(
            [
                ("2025-12-31", 2.0),
                ("2026-04-01", 2.0),
                ("2026-04-02", 2.0),
            ]
        ),
    )
    history = load_performance_history(history_path)

    flow_row = history.loc[history["date"].eq(pd.Timestamp("2026-04-01"))].iloc[0]
    assert flow_row["cash_flow_sgd"] == pytest.approx(60.0)
    assert flow_row["cash_flow_usd"] == pytest.approx(30.0)

    rows, missing_years = build_horizon_rows_from_performance_history(
        history,
        archive_start_year=2026,
    )
    ytd_twr_usd = next(
        row
        for row in rows
        if row.horizon == "YTD" and row.weighting == "time_weighted" and row.currency == "USD"
    )
    ytd_twr_sgd = next(
        row
        for row in rows
        if row.horizon == "YTD" and row.weighting == "time_weighted" and row.currency == "SGD"
    )

    assert missing_years == []
    assert ytd_twr_usd.source_version == "PerformanceHistoryFeather"
    assert ytd_twr_sgd.source_version == "PerformanceHistoryFeather"
    assert ytd_twr_usd.return_pct == pytest.approx(-0.336)
    assert ytd_twr_sgd.return_pct == pytest.approx(-0.336)


def test_performance_analytics_default_to_finalized_history() -> None:
    history = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-01-01", "2026-01-02", "2026-01-03", "2026-01-06"]),
            "nav_close_usd": [100.0, 110.0, 99.0, 103.95],
            "nav_close_sgd": [130.0, 143.0, 128.7, 135.135],
            "cash_flow_usd": [pd.NA, 0.0, 0.0, 0.0],
            "cash_flow_sgd": [pd.NA, 0.0, 0.0, 0.0],
            "fx_usdsgd_eod": [1.30, 1.30, 1.30, 1.30],
            "twr_return_usd": [pd.NA, 0.10, -0.10, 0.05],
            "twr_return_sgd": [pd.NA, 0.10, -0.10, 0.05],
            "is_final": [True, True, True, False],
            "source_kind": ["latest", "latest", "latest", "latest"],
            "source_file": ["demo.xml"] * 4,
            "source_as_of": pd.to_datetime(["2026-01-06"] * 4),
        }
    )

    index = build_twr_index(history, "USD")
    drawdown = drawdown_series(history, "USD")

    assert list(index.index.strftime("%Y-%m-%d")) == ["2026-01-02", "2026-01-03"]
    assert index.iloc[-1] == pytest.approx(0.99)
    assert drawdown.min() == pytest.approx(-0.10)
    assert annualized_return(history, "USD") < 0
    assert annualized_return(history, "USD", include_provisional=True) > 0


def _write_nav_snapshot_xml(
    path: Path,
    *,
    from_date: str,
    to_date: str,
    totals: list[tuple[str, float]],
    currency: str = "USD",
) -> None:
    rows = "\n".join(
        f'<EquitySummaryByReportDateInBase currency="{currency}" reportDate="{report_date}" total="{total}" />'
        for report_date, total in totals
    )
    path.write_text(
        f"""
<FlexQueryResponse>
  <FlexStatements>
    <FlexStatement accountId="U2935967" fromDate="{from_date}" toDate="{to_date}" whenGenerated="{to_date};010101">
      <EquitySummaryInBase>
        {rows}
      </EquitySummaryInBase>
    </FlexStatement>
  </FlexStatements>
</FlexQueryResponse>
""".strip(),
        encoding="utf-8",
    )


def _write_statement_with_cash_report(
    path: Path,
    *,
    from_date: str,
    to_date: str,
    totals: list[tuple[str, float]],
    cash_currency_rows: list[tuple[str, float]],
    currency: str = "SGD",
) -> None:
    nav_rows = "\n".join(
        f'<EquitySummaryByReportDateInBase currency="{currency}" reportDate="{report_date}" total="{total}" />'
        for report_date, total in totals
    )
    cash_rows = "\n".join(
        (
            '<CashReportCurrency '
            f'currency="{row_currency}" '
            'levelOfDetail="Currency" '
            f'fromDate="{from_date}" '
            f'toDate="{to_date}" '
            f'depositWithdrawals="{amount}" '
            f'depositWithdrawalsMTD="{amount}" '
            f'depositWithdrawalsYTD="{amount}" />'
        )
        for row_currency, amount in cash_currency_rows
    )
    path.write_text(
        f"""
<FlexQueryResponse>
  <FlexStatements>
    <FlexStatement accountId="U2935967" fromDate="{from_date}" toDate="{to_date}" whenGenerated="{to_date};010101">
      <EquitySummaryInBase>
        {nav_rows}
      </EquitySummaryInBase>
      <CashReport>
        {cash_rows}
      </CashReport>
    </FlexStatement>
  </FlexStatements>
</FlexQueryResponse>
""".strip(),
        encoding="utf-8",
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
