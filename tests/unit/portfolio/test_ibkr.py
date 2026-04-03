import pytest

from market_helper.portfolio import (
    SecurityReferenceTable,
    normalize_ibkr_latest_prices,
    normalize_ibkr_positions,
)


class FakeIbkrRow:
    def __init__(self, **kwargs: object) -> None:
        for key, value in kwargs.items():
            setattr(self, key, value)


def test_normalize_ibkr_positions_matches_curated_equity_row() -> None:
    table = SecurityReferenceTable.from_default_csv()
    positions = normalize_ibkr_positions(
        [
            {
                "account": "U12345",
                "con_id": "756733",
                "sec_type": "STK",
                "symbol": "SPY",
                "currency": "USD",
                "exchange": "ARCA",
                "position": "20",
                "avg_cost": "210.5",
                "market_value": "4300",
            }
        ],
        table,
        as_of="2026-03-25T00:00:00+00:00",
    )

    assert positions[0].internal_id == "STK:SPY:ARCA"
    assert table.require_internal_id("ibkr", "756733") == "STK:SPY:ARCA"


def test_normalize_ibkr_positions_matches_futures_family_alias() -> None:
    table = SecurityReferenceTable.from_default_csv()
    positions = normalize_ibkr_positions(
        [
            {
                "account": "U12345",
                "con_id": "999001",
                "sec_type": "FUT",
                "symbol": "ZN",
                "currency": "USD",
                "exchange": "CBOT",
                "local_symbol": "ZNM6",
                "multiplier": "1000",
                "position": "1",
                "avg_cost": "110",
                "market_value": "111000",
            }
        ],
        table,
        as_of="2026-03-25T00:00:00+00:00",
    )

    assert positions[0].internal_id == "FUT:ZN:CBOT"
    assert table.require_internal_id("ibkr", "999001") == "FUT:ZN:CBOT"


def test_normalize_ibkr_latest_prices_uses_fallback_price_fields() -> None:
    table = SecurityReferenceTable.from_default_csv()
    normalize_ibkr_positions(
        [
            {
                "account": "U12345",
                "con_id": "756733",
                "sec_type": "STK",
                "symbol": "SPY",
                "currency": "USD",
                "exchange": "ARCA",
                "position": "20",
            }
        ],
        table,
        as_of="2026-03-25T00:00:00+00:00",
    )

    prices = normalize_ibkr_latest_prices(
        [{"con_id": "756733", "close": "215.1"}],
        table,
        as_of="2026-03-25T00:01:00+00:00",
    )

    assert prices[0].last_price == 215.1
    assert prices[0].internal_id == "STK:SPY:ARCA"


def test_normalize_ibkr_positions_accepts_camel_case_and_object_payload() -> None:
    table = SecurityReferenceTable.from_default_csv()
    positions = normalize_ibkr_positions(
        [
            FakeIbkrRow(
                account="U12345",
                conId="999002",
                secType="FUT",
                symbol="ZF",
                currency="USD",
                exchange="CBOT",
                localSymbol="ZFM6",
                multiplier="1000",
                position="3",
                averageCost="106.25",
                marketValue="318750",
            )
        ],
        table,
        as_of="2026-03-25T00:00:00+00:00",
    )

    assert positions[0].internal_id == "FUT:ZF:CBOT"
    assert positions[0].avg_cost == 106.25
    assert positions[0].market_value == 318750
    assert table.require_internal_id("ibkr", "999002") == "FUT:ZF:CBOT"


def test_normalize_ibkr_positions_marks_options_outside_scope() -> None:
    table = SecurityReferenceTable.from_default_csv()
    positions = normalize_ibkr_positions(
        [
            {
                "account": "U12345",
                "con_id": "701332964",
                "sec_type": "OPT",
                "symbol": "SPY",
                "currency": "USD",
                "exchange": "AMEX",
                "local_symbol": "SPY   260618P00620000",
                "position": "1",
                "market_value": "-100",
            }
        ],
        table,
        as_of="2026-03-26T00:00:00+00:00",
    )

    assert positions[0].internal_id == "OUTSIDE_SCOPE:OPT:SPY:AMEX"
    assert table.get_security("OUTSIDE_SCOPE:OPT:SPY:AMEX").mapping_status == "outside_scope"


def test_normalize_ibkr_positions_marks_unmapped_instruments() -> None:
    table = SecurityReferenceTable.from_default_csv()
    positions = normalize_ibkr_positions(
        [
            {
                "accountId": "U12345",
                "conid": "888888",
                "secType": "STK",
                "symbol": "AAPL",
                "currency": "USD",
                "exchange": "SMART",
                "position": "20",
                "avgCost": "210.5",
                "marketValue": "4300",
            }
        ],
        table,
        as_of="2026-03-26T00:00:00+00:00",
    )

    assert positions[0].account == "U12345"
    assert positions[0].avg_cost == 210.5
    assert positions[0].internal_id == "STK:AAPL:SMART"
    assert table.get_security("STK:AAPL:SMART").mapping_status == "unmapped"


def test_normalize_ibkr_positions_prefers_primary_exchange_and_unique_symbol_match() -> None:
    table = SecurityReferenceTable.from_default_csv()
    positions = normalize_ibkr_positions(
        [
            {
                "accountId": "U12345",
                "conid": "756733",
                "secType": "STK",
                "symbol": "SPY",
                "currency": "USD",
                "exchange": "SMART",
                "primaryExchange": "ARCA",
                "position": "20",
            }
        ],
        table,
        as_of="2026-03-26T00:00:00+00:00",
    )

    assert positions[0].internal_id == "STK:SPY:ARCA"


def test_normalize_ibkr_latest_prices_accepts_market_price_alias() -> None:
    table = SecurityReferenceTable.from_default_csv()
    normalize_ibkr_positions(
        [
            {
                "account": "U12345",
                "con_id": "756733",
                "sec_type": "STK",
                "symbol": "SPY",
                "currency": "USD",
                "exchange": "ARCA",
                "position": "20",
            }
        ],
        table,
    )

    prices = normalize_ibkr_latest_prices(
        [{"conId": "756733", "marketPrice": "214.8"}],
        table,
    )
    assert prices[0].last_price == 214.8


def test_normalize_ibkr_latest_prices_raises_when_no_price_fields() -> None:
    table = SecurityReferenceTable.from_default_csv()
    normalize_ibkr_positions(
        [
            {
                "account": "U12345",
                "con_id": "756733",
                "sec_type": "STK",
                "symbol": "SPY",
                "currency": "USD",
                "exchange": "ARCA",
                "position": "20",
            }
        ],
        table,
    )

    with pytest.raises(ValueError):
        normalize_ibkr_latest_prices([{"con_id": "756733"}], table)
