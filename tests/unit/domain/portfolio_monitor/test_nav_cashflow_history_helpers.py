from __future__ import annotations

"""Unit tests for the pure-helper functions inside
`domain.portfolio_monitor.services.nav_cashflow_history`.

`test_performance_history_services.py` covers end-to-end rebuilds of the
NAV/cashflow history feather from sample Flex XML. These tests are narrower:
they lock the behaviour of the *individual* helper functions so a future
change to (e.g.) the report-date precedence is caught at the unit level
without having to read a 200-line integration scenario.
"""

from datetime import date

import pytest

from market_helper.domain.portfolio_monitor.services.nav_cashflow_history import (
    NAV_CASHFLOW_HISTORY_COLUMNS,
    NavCashflowHistorySource,
    _build_source_descriptor,
    _classify_deposit_withdrawal_description,
    _extract_cashflow_date,
    _parse_float_or_none,
    _parse_statement_date,
)


# ---------------------------------------------------------------------------
# _extract_cashflow_date precedence: reportDate > settleDate > dateTime
# (Hot-memory gotcha: Flex XML cashflow attribution uses reportDate, not
# settleDate. The precedence is the load-bearing invariant.)
# ---------------------------------------------------------------------------


def test_extract_cashflow_date_prefers_report_date_when_all_present() -> None:
    attrs = {
        "reportDate": "20240115",
        "settleDate": "20240117",
        "dateTime": "20240116;120000",
    }
    assert _extract_cashflow_date(attrs) == date(2024, 1, 15)


def test_extract_cashflow_date_falls_back_to_settle_date_when_report_missing() -> None:
    attrs = {
        "reportDate": "",
        "settleDate": "20240117",
        "dateTime": "20240116;120000",
    }
    assert _extract_cashflow_date(attrs) == date(2024, 1, 17)


def test_extract_cashflow_date_falls_back_to_date_time_when_others_missing() -> None:
    attrs = {
        "reportDate": "",
        "settleDate": "",
        "dateTime": "20240116;120000",
    }
    assert _extract_cashflow_date(attrs) == date(2024, 1, 16)


def test_extract_cashflow_date_returns_none_when_all_absent() -> None:
    assert _extract_cashflow_date({"reportDate": "", "settleDate": "", "dateTime": ""}) is None
    assert _extract_cashflow_date({}) is None


def test_extract_cashflow_date_skips_invalid_report_date_and_uses_settle() -> None:
    attrs = {"reportDate": "not-a-date", "settleDate": "20240117", "dateTime": ""}
    assert _extract_cashflow_date(attrs) == date(2024, 1, 17)


# ---------------------------------------------------------------------------
# _parse_statement_date: accepts yyyymmdd compact form AND ISO yyyy-mm-dd
# ---------------------------------------------------------------------------


def test_parse_statement_date_yyyymmdd_compact_form() -> None:
    assert _parse_statement_date("20240315") == date(2024, 3, 15)


def test_parse_statement_date_iso_form() -> None:
    assert _parse_statement_date("2024-03-15") == date(2024, 3, 15)


def test_parse_statement_date_handles_whitespace() -> None:
    assert _parse_statement_date("  20240315  ") == date(2024, 3, 15)


def test_parse_statement_date_returns_none_for_empty_or_invalid() -> None:
    assert _parse_statement_date("") is None
    assert _parse_statement_date("   ") is None
    assert _parse_statement_date("not-a-date") is None
    assert _parse_statement_date("20241332") is None  # invalid month/day


# ---------------------------------------------------------------------------
# _parse_float_or_none: tolerates commas (thousands separator) and blanks
# ---------------------------------------------------------------------------


def test_parse_float_or_none_plain_number() -> None:
    assert _parse_float_or_none("1234.56") == pytest.approx(1234.56)


def test_parse_float_or_none_strips_commas() -> None:
    assert _parse_float_or_none("1,234,567.89") == pytest.approx(1234567.89)


def test_parse_float_or_none_negative_value() -> None:
    assert _parse_float_or_none("-1,500.25") == pytest.approx(-1500.25)


def test_parse_float_or_none_returns_none_for_blank_or_invalid() -> None:
    assert _parse_float_or_none("") is None
    assert _parse_float_or_none("   ") is None
    assert _parse_float_or_none("abc") is None


# ---------------------------------------------------------------------------
# _build_source_descriptor: filename convention drives source-kind + priority
# (priority lower wins; full=0, latest=2, neither=None → caller uses adhoc=1)
# ---------------------------------------------------------------------------


def test_build_source_descriptor_full_keyword_priority_zero(tmp_path) -> None:
    path = tmp_path / "ibkr_flex_full_20240101_20241231.xml"
    path.write_text("<FlexQueryResponse/>", encoding="utf-8")
    descriptor = _build_source_descriptor(path)
    assert isinstance(descriptor, NavCashflowHistorySource)
    assert descriptor.source_kind == "full"
    assert descriptor.priority == 0


def test_build_source_descriptor_latest_keyword_priority_two(tmp_path) -> None:
    path = tmp_path / "ibkr_flex_latest_20250101.xml"
    path.write_text("<FlexQueryResponse/>", encoding="utf-8")
    descriptor = _build_source_descriptor(path)
    assert isinstance(descriptor, NavCashflowHistorySource)
    assert descriptor.source_kind == "latest"
    assert descriptor.priority == 2


def test_build_source_descriptor_unknown_pattern_returns_none(tmp_path) -> None:
    path = tmp_path / "some_other_naming.xml"
    path.write_text("<FlexQueryResponse/>", encoding="utf-8")
    assert _build_source_descriptor(path) is None


# ---------------------------------------------------------------------------
# _classify_deposit_withdrawal_description: today always returns the single
# "DEPOSITS_WITHDRAWALS" classification. Lock that so any future expansion
# (e.g. distinguishing INTERNAL_TRANSFER) is a deliberate change.
# ---------------------------------------------------------------------------


def test_classify_deposit_withdrawal_description_constant() -> None:
    assert _classify_deposit_withdrawal_description("Ach Deposit") == "DEPOSITS_WITHDRAWALS"
    assert _classify_deposit_withdrawal_description("WIRE OUT") == "DEPOSITS_WITHDRAWALS"
    assert _classify_deposit_withdrawal_description("") == "DEPOSITS_WITHDRAWALS"


# ---------------------------------------------------------------------------
# NAV_CASHFLOW_HISTORY_COLUMNS schema lock — downstream readers depend on
# both presence and ordering of these columns in the canonical feather.
# ---------------------------------------------------------------------------


def test_nav_cashflow_history_columns_schema_locked() -> None:
    assert NAV_CASHFLOW_HISTORY_COLUMNS == [
        "date",
        "nav_eod_usd",
        "cashflow_usd",
        "fx_usdsgd_eod",
        "nav_eod_sgd",
        "cashflow_sgd",
        "is_final",
        "pnl_amt_usd",
        "pnl_amt_sgd",
        "pnl_usd",
        "pnl_sgd",
        "source_kind",
        "source_file",
        "source_as_of",
        "bench_spy_return_usd",
        "bench_spy_return_sgd",
        "bench_bil_return_usd",
        "bench_bil_return_sgd",
    ]
